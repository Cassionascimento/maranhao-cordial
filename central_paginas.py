"""Páginas HTML autônomas da Central Empresarial (fora do admin.html
principal) -- hoje só o retorno visual do callback OAuth do Gmail, que
antes terminava numa tela JSON crua
(`{"success":true,"mensagem":"Gmail conectado com sucesso."}`), a causa
raiz do item B da ordem "Central Empresarial: UX/calendário/Gmail".

Sem dependência de Flask/psycopg2 -- só monta uma string HTML, por isso
é testável diretamente, sem precisar importar main.py (convenção do
projeto: nada aqui abre banco, sessão ou conexão)."""

_CORES = {'sucesso': '#b99a5d', 'erro': '#c96a4f'}


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
