"""Páginas HTML autônomas da Central Empresarial (fora do admin.html
principal) -- hoje só o retorno visual do callback OAuth do Gmail, que
antes terminava numa tela JSON crua
(`{"success":true,"mensagem":"Gmail conectado com sucesso."}`), a causa
raiz do item B da ordem "Central Empresarial: UX/calendário/Gmail".

Sem dependência de Flask/psycopg2 -- só monta uma string HTML, por isso
é testável diretamente, sem precisar importar main.py (convenção do
projeto: nada aqui abre banco, sessão ou conexão)."""

_CORES = {'sucesso': '#b99a5d', 'erro': '#c96a4f'}


def _esc(v):
    return (
        str(v if v is not None else 'AGUARDANDO DADOS')
        .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        .replace('"', '&quot;').replace("'", '&#39;')
    )


def _centavos(v):
    return 'R$ ' + f'{(v or 0) / 100:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')


def pagina_visao_investidor_invalida():
    """Link inexistente/expirado/revogado -- nunca revela se o token um
    dia existiu, nunca lista operações, nunca sugere tentar de novo com
    outro valor (superfície de enumeração)."""
    return f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Link indisponível — Maranhão Cordial</title>
<style>body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#07100b;color:#efe7d6;font-family:Arial,Helvetica,sans-serif;padding:24px;box-sizing:border-box}}
.cartao{{max-width:420px;width:100%;padding:32px;border:1px solid rgba(201,106,79,.3);border-radius:14px;
background:rgba(255,255,255,.02);text-align:center}}
.eyebrow{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:{_CORES['erro']};margin:0 0 10px}}
h1{{font-family:Georgia,'Times New Roman',serif;font-weight:400;font-size:22px;margin:0 0 10px}}
p{{font-size:14px;line-height:1.5;color:#c9c2b3;margin:0}}</style></head>
<body><div class="cartao"><p class="eyebrow">MARANHÃO CORDIAL &middot; VISÃO INVESTIDOR</p>
<h1>Link indisponível</h1><p>Este link não existe mais, expirou ou foi revogado pela direção. Solicite um novo acesso.</p>
</div></body></html>"""


def pagina_visao_investidor(visao):
    """Visão somente leitura para um investidor autorizado (token opaco,
    nunca ADMIN_API_KEY). Nunca mostra telefone/email/observações
    internas, prompts, chaves ou controles de execução -- só o que
    visao_investidor() (mi_operacoes.py) já sanitizou. Todo valor
    ausente aparece como AGUARDANDO DADOS, nunca um número inventado."""
    op = visao['operacao']
    equipe_html = ''.join(
        f'<li>{_esc(p["funcao"])} — <span class="estado">{_esc(p["estado"])}</span></li>' for p in visao['equipe_resumo']
    ) or '<li class="vazio">Nenhuma pessoa confirmada ainda.</li>'
    plano_html = ''.join(
        f'<li>{_esc(i["titulo"])} — <span class="estado">{_esc(i["status"])}</span>'
        f'{" · " + _esc(i["data_prevista"]) if i.get("data_prevista") else ""}</li>' for i in visao['plano']
    ) or '<li class="vazio">Nenhum item de plano ainda.</li>'
    indicadores_html = ''.join(
        f'<li><b>{_esc(m["nome"])}</b>: {_esc(m["valor"]) if m["valor"] is not None else "AGUARDANDO DADOS"} '
        f'{_esc(m.get("unidade") or "")} <span class="estado">{_esc(m["estado_dado"])}</span>'
        f'<small>{_esc(m.get("explicacao") or "")}</small></li>' for m in visao['indicadores']
    ) or '<li class="vazio">Nenhum indicador definido ainda.</li>'
    financeiro_html = ''.join(
        f'<li>{_esc(f["categoria"])} ({_esc(f["tipo"])}): {_centavos(f["valor_centavos"])} '
        f'<span class="estado">{_esc(f["estado_dado"])}</span></li>' for f in visao['financeiro_resumo']
    ) or '<li class="vazio">Nenhum lançamento financeiro ainda.</li>'
    return f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(op['titulo'])} — Visão Investidor</title>
<style>
body{{margin:0;background:#07100b;color:#efe7d6;font-family:Arial,Helvetica,sans-serif}}
.env{{max-width:760px;margin:0 auto;padding:32px 20px 60px}}
.eyebrow{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:#b99a5d;margin:0 0 8px}}
h1{{font-family:Georgia,'Times New Roman',serif;font-weight:400;font-size:30px;margin:0 0 6px}}
.meta{{color:#98a49b;font-size:13px;margin:0 0 28px}}
section{{margin-bottom:26px;padding:18px 20px;border:1px solid rgba(185,154,93,.15);border-radius:14px;
background:rgba(255,255,255,.02)}}
section h2{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#d6bd88;margin:0 0 12px}}
ul{{list-style:none;margin:0;padding:0}}
li{{font-size:13px;line-height:1.6;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05)}}
li:last-child{{border-bottom:none}}
li.vazio{{color:#6f7c73}}
.estado{{font-size:10px;text-transform:uppercase;letter-spacing:.05em;color:#b99a5d;margin-left:6px}}
small{{display:block;color:#8e9b92;margin-top:2px}}
footer{{font-size:11px;color:#5f6b62;margin-top:30px}}
</style></head>
<body><div class="env">
<p class="eyebrow">MARANHÃO CORDIAL &middot; VISÃO INVESTIDOR</p>
<h1>{_esc(op['titulo'])}</h1>
<p class="meta">{_esc(op['data_inicio'])} a {_esc(op['data_fim'])} · {_esc(op.get('local'))} · estado: {_esc(op['estado'])}</p>
<section><h2>Equipe</h2><ul>{equipe_html}</ul></section>
<section><h2>Plano</h2><ul>{plano_html}</ul></section>
<section><h2>Indicadores</h2><ul>{indicadores_html}</ul></section>
<section><h2>Financeiro</h2><ul>{financeiro_html}</ul></section>
<footer>Acesso somente leitura, concedido e revogável pela direção da Maranhão Cordial.</footer>
</div></body></html>"""


def pagina_gmail_callback(sucesso, mensagem):
    """Página final do fluxo OAuth do Gmail institucional -- reaproveita
    a identidade visual já usada em toda a Central (fundo #07100b,
    dourado #b99a5d, tipografia Georgia/Arial, mesma paleta de
    mi_presentation_engine.py/mi_chart_engine.py). Se aberta como popup
    (fluxo antigo), avisa a janela que abriu via postMessage no MESMO
    origin e se fecha sozinha; se aberta como navegação normal (fluxo
    atual do botão "Abrir Gmail institucional"), mostra um botão para
    fechar/voltar."""
    cor = _CORES['sucesso'] if sucesso else _CORES['erro']
    titulo = 'Gmail conectado' if sucesso else 'Não foi possível conectar o Gmail'
    mensagem_escapada = (
        str(mensagem)
        .replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        .replace('"', '&quot;').replace("'", '&#39;')
    )
    sucesso_js = 'true' if sucesso else 'false'
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo} — Maranhão Cordial</title>
<style>
  body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
        background:#07100b;color:#efe7d6;font-family:Arial,Helvetica,sans-serif;padding:24px;
        box-sizing:border-box}}
  .cartao{{max-width:420px;width:100%;padding:32px;border:1px solid rgba(185,154,93,.25);
           border-radius:14px;background:rgba(255,255,255,.02);text-align:center}}
  .eyebrow{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:{cor};margin:0 0 10px}}
  h1{{font-family:Georgia,'Times New Roman',serif;font-weight:400;font-size:22px;margin:0 0 10px}}
  p{{font-size:14px;line-height:1.5;color:#c9c2b3;margin:0 0 22px}}
  button{{background:{cor};color:#0a0f0b;border:none;border-radius:8px;padding:10px 18px;
          font-size:13px;font-weight:600;cursor:pointer}}
</style>
</head>
<body>
  <div class="cartao">
    <p class="eyebrow">MARANHÃO CORDIAL &middot; CENTRAL EMPRESARIAL</p>
    <h1>{titulo}</h1>
    <p>{mensagem_escapada}</p>
    <button type="button" onclick="window.close()">Fechar esta aba</button>
  </div>
  <script>
    (function() {{
      try {{
        if (window.opener) {{
          window.opener.postMessage({{tipo: 'gmail-oauth-concluido', sucesso: {sucesso_js}}}, window.location.origin);
          setTimeout(function() {{ window.close(); }}, 1200);
        }}
      }} catch (e) {{}}
    }})();
  </script>
</body>
</html>"""
