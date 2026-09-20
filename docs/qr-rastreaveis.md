# QR Codes rastreáveis

Fluxo: **QR → origem → interação/avaliação → Maranhão Intelligence → contato opcional no CRM.**
Nada aqui reconstrói o CRM, o painel ou a Intelligence: usa `mi_sinais.emitir`, `crm_identidade` e `leads_crm`.

## Rotas

| Rota | Quem | O quê |
|---|---|---|
| `GET /q/<codigo>` | público | mesma página para qualquer código (não é oráculo de códigos) |
| `GET /api/qr/<codigo>` | público | configuração; inexistente, pausado e revogado respondem igual (404) |
| `POST /api/qr/<codigo>/scan` | público | leitura, uma por sessão de navegação (`chave`) |
| `POST /api/qr/<codigo>/inicio` · `/avaliacao` · `/contato` | público | funil, avaliação (anônima) e contato opcional |
| `GET/POST /api/admin/qr/codigos`, `PATCH …/<id>`, `GET …/<id>/arquivo?formato=svg\|png\|pdf`, `GET /api/admin/qr/painel?dias=` | admin (`X-Admin-Key`) | criar, alterar destino/estado, baixar arte, painel |

## Regras que não mudam

- O código impresso (`codigo_publico`, 10 símbolos opacos) **nunca muda**; muda o destino (`pagina`/`redirecionar`) e o estado (`ativo`/`pausado`/`revogado`; revogado é definitivo).
- Avaliação anônima **não cria lead** e não guarda IP, user-agent nem identificador de aparelho.
- Com contato: dedupe por telefone/e-mail (`crm_identidade`); ambiguidade ou cadastro arquivado **não é fundido em silêncio** (`identidade_pendente`, aparece em duplicados).
- Consentimento de contato e de marketing são campos separados, com a versão do texto exibido.
- `aceita_59` é derivado no servidor da faixa de preço (limite inferior ≥ R$ 59); o navegador só informa a faixa.
- Painel: sem dado → `null` (nunca 0%); todo agregado traz `n`; abaixo de 30 avaliações, `amostra_pequena`. “Outras origens” = avaliações por QR fora da feira; não há base externa importada.

## Sinais emitidos (origem `qr`, sem dado pessoal nem comentário)

`qr_scan`, `avaliacao_iniciada`, `avaliacao_concluida`, `intencao_compra` (só certamente/provavelmente), `preco_aceito` (faixa ≥ R$ 59), `contato_fornecido`, `lead_b2b` (perfil B2B), `interesse_<comprar|servir|amostra|proposta|revenda|distribuicao|parceria>`.

## Artes

`python3 scripts/gerar_qr_artes.py` gera SVG/PNG/PDF em `artes/qr/` (fora do site) a partir da migration 029. Nível de correção Q, zona de silêncio de 4 módulos, módulos escuros sobre bloco creme. Testes leem os arquivos com decodificador independente (zxing-cpp), inclusive degradados. **Leitura em iPhone/Android físicos e em papel impresso é verificação manual e não é coberta por teste automático.**

## Publicação

Migration `029_qr_rastreaveis.sql` (aditiva, idempotente) precisa ser aplicada no banco antes de o deploy da API; sem ela as rotas respondem erro e nada quebra no resto.
