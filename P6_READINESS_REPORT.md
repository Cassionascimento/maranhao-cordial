# P6 Readiness Report — Maranhão Intelligence

Data de referência: 2026-09-17
SHA de referência (live, confirmado byte-a-byte no domínio de produção): `e62c172`
Branch canônica: `main`

Este documento é um retrato do estado real do sistema após o fechamento
P0–P5 e a estabilização pós-live (correção do 404 do Admin V2, correção
das 2 falhas de teste pré-existentes, CI mínimo). Ele não propõe nem
começa P6 — apenas descreve o que existe, o que falta, e o que P6 deveria
acrescentar.

---

## 1. Arquitetura atual

```
Contact Central / CRM (leads_crm, interacoes_omnichannel, propostas)
Pedidos (pedidos.sku) ──┐
Fábrica (mi_skus/mi_lotes/mi_unidades/mi_estabelecimentos, read-only) ──┤
                         ▼
        mi_relacionamento_360.py  (P1B — agregador central de leitura)
                         ▼
        mi_sinais_relacionamento.py (P2A — sinais DIRECT/INFERRED/UNKNOWN)
                         ▼
        mi_inteligencia_relacionamento.py (P2B-F — score/segmentos/
        oportunidades/next best action, tudo determinístico, versionado)
                         ▼
        mi_outcome_relacionamento.py (P3A/B, P4, P5 — único ponto de
        ESCRITA: recomendação apresentada → decisão humana → outcome,
        sobre mi_fila_operacional/mi_decisao já existentes)
                         │
        mi_territorio_inteligencia.py (P3C, adapta inteligencia_
        territorial.py existente — não recalcula)
        mi_forecast_readiness.py (P3D — prontidão, nunca forecast real)
                         ▼
        mi_intelligence_api.py (P5 — contrato canônico único: contrato
        por relacionamento, overview executivo, fila de decisão)
                         ▼
        maranhao-intelligence.js (Admin V2 — Command Center, somente
        leitura + apresentação de recomendação, nunca execução)
```

Nenhuma camada nova foi criada nesta fase de estabilização — só correção
de integração (fix do 404) e de dívida de teste.

## 2. Capacidades reais (IMPLEMENTADO + TESTADO + LIVE)

| Capacidade | Estado |
|---|---|
| SKU rastreável em pedido, leitura de fábrica (mi_skus/lotes/unidades/estabelecimentos) | IMPLEMENTADO / TESTADO / LIVE |
| Relationship 360 (pessoa + organização + comercial + produto + comportamento + geografia) | IMPLEMENTADO / TESTADO / LIVE |
| Sinais unificados com proveniência DIRECT/INFERRED/UNKNOWN | IMPLEMENTADO / TESTADO / LIVE |
| Score explicável por dimensão, versionado (`relacionamento_score_v1`) | IMPLEMENTADO / TESTADO / LIVE |
| Segmentação comportamental não excludente | IMPLEMENTADO / TESTADO / LIVE |
| Detecção de oportunidades + Next Best Action (recomendação, nunca execução) | IMPLEMENTADO / TESTADO / LIVE |
| Fila de decisão humana (apresentar → decidir → outcome) sobre `mi_fila_operacional` | IMPLEMENTADO / TESTADO / LIVE |
| Dataset de aprendizado versionado (`relacionamento_learning_v1`), sem treino de ML | IMPLEMENTADO / TESTADO / LIVE |
| Território v1 (adapta `inteligencia_territorial.py`, opt-in via query param) | IMPLEMENTADO / TESTADO / LIVE |
| Forecast readiness (prontidão de série, nunca previsão estatística real) | IMPLEMENTADO / TESTADO / LIVE |
| Contrato canônico de Intelligence (18 campos), Overview executivo, Decision Queue | IMPLEMENTADO / TESTADO / LIVE |
| Admin V2 Command Center consumindo os contratos acima | IMPLEMENTADO / TESTADO / LIVE |
| CI automatizado (Python + JS + auditoria de rotas + integração) | IMPLEMENTADO nesta fase — AGUARDANDO primeira execução real em PR/push |

## 3. Dados disponíveis hoje

- Identidade e organização: dados reais de `leads_crm`/estabelecimentos onde já cadastrados.
- Sinais comportamentais: reais onde há `interacoes_omnichannel`/formulários/eventos.
- Comercial: reais onde há `propostas`/`compras_relacionamento`/`pedidos` vinculados.
- Fila de decisão: vazia em produção até que o próprio sistema (ou um humano) apresente a primeira recomendação — isso é esperado, não é falha.

## 4. Dados insuficientes / AGUARDANDO DADOS

| Área | Critério de maturidade | Estado hoje |
|---|---|---|
| Learning dataset | `ready=true` exige ≥ 20 linhas reais no dataset | AGUARDANDO DADOS — não deve virar `true` artificialmente |
| Território | exige correspondência real de cidade/UF com oportunidade territorial calculada | AGUARDANDO DADOS onde geografia não bate |
| Forecast | exige ≥ 6 meses de série histórica | AGUARDANDO DADOS até haver série suficiente |

Nenhum desses três é tratado como erro pelo sistema — todos renderizam
`NOT_ENOUGH_DATA`/`ready=false`/`not_requested` explicitamente, tanto no
contrato quanto no Command Center.

## 5. Dívida técnica restante

- Nenhuma dívida de teste conhecida no momento (216→218/218 JS, 1173/1173 Python).
- CI acabou de ser criado e ainda não rodou de verdade em um PR real — precisa da primeira execução para ser considerado validado, não só "implementado".
- `docs/MARANHAO_PLATFORM_AUDIT.md`, `ROADMAP.md`, `TARGET_ARCHITECTURE.md` e `DATA_MOAT_STRATEGY.md` (da fase de auditoria completa) continuam como arquivos não versionados — decisão pendente do usuário sobre se devem entrar no repositório.
- Nenhuma dívida de dado fictício ou mock em produção foi encontrada.

## 6. Testes

- Python: 1173/1173 (unittest, `tests/test_*.py`), zero uso de mocks de banco real — todos os testes de rota usam Flask real + `app.test_client()` + factory/cursor simulados.
- JS: 218/218 (`node --test tests/*.cjs`), zero falha conhecida.
- Auditoria estrutural (`tests/test_main_routes_audit.py`): garante que todo `registrar_rotas*` importado em `main.py` é chamado, e que toda URL usada pelo Command Center resolve a uma rota Flask real.
- Integração ponta-a-ponta do contrato P5 (`tests/test_mi_intelligence_api_integration.py`): autenticação real (`email_seguranca.admin_autorizado`), banco vazio, relacionamento inexistente, dataset de aprendizado vazio — sempre via HTTP real, nunca chamando função interna diretamente.

## 7. CI

Criado nesta fase: `.github/workflows/ci.yml`, dois jobs (`python`, `javascript`),
disparado em `pull_request` e `push` para `main`. Só valida — nenhum deploy.
Usa exatamente os comandos já usados manualmente neste projeto
(`python3 -m unittest discover -s tests -p "test_*.py"`, `node --test
tests/*.cjs`), sem inventar scripts novos. Ainda não rodou em produção do
GitHub — a confirmação real de que passa no ambiente do Actions só existe
após o primeiro PR que o dispare.

## 8. Riscos

- **Zero dado de produção verificado por mim com autenticação real**: os
  checks de smoke test que dependem de `X-Admin-Key` real (score/
  explicabilidade/formato de oportunidades com dados de produção de
  verdade) não foram executados por mim nesta sessão — não tenho, e não
  devo pedir, a chave de admin real. O que confirmei sem credenciais:
  o domínio responde, 401 é retornado sem chave/com chave inválida em
  toda rota `/api/admin/*` (nunca vaza existência de rota), e o arquivo
  JS servido em produção é byte-a-byte idêntico ao corrigido localmente.
- **Deploy fora do controle de versão**: não há `render.yaml`/`Procfile`
  no repositório — a configuração de deploy vive só no painel do Render.
  Isso significa que a infraestrutura de deploy não é auditável via git.
- **CI novo, não validado em produção do GitHub Actions ainda.**

## 9. Redundâncias que devem ser evitadas em P6

Nenhum destes deve ser recriado — todos já existem e devem ser
reaproveitados:
- Território: `inteligencia_territorial.py` (P6 nunca deve recalcular
  agregação territorial do zero).
- Fila operacional/decisão: `mi_fila_operacional`/`mi_decisao.py`
  (único mecanismo de escrita de decisão — P6 não deve introduzir uma
  segunda fila).
- Autenticação admin: `email_seguranca.admin_autorizado` +
  `validar_admin_request` (P6 não deve inventar um segundo esquema de
  chave).
- Score/segmentos/oportunidades: `mi_inteligencia_relacionamento.py`
  (P6 pode consumir, nunca duplicar o cálculo).
- Contrato de leitura do painel: `mi_intelligence_api.py` (qualquer tela
  nova do Command Center deve consumir esse contrato, não inventar um
  novo formato de resposta).

## 10. Proposta objetiva de escopo para P6

P0–P5 fecham o ciclo SINAL → SCORE → RECOMENDAÇÃO → DECISÃO HUMANA →
OUTCOME → DATASET DE APRENDIZADO, mas o dataset nunca é usado para nada
além de ser exportado. A capacidade real que falta, e que nenhuma fase
anterior cobre, é: **usar esse dataset já certificado para calibrar os
pesos hoje fixos do score** (`PESO_CONFIANCA` em
`mi_sinais_relacionamento.py`, dimensões fixas em
`mi_inteligencia_relacionamento.py`) — sem introduzir ML de caixa-preta,
apenas ajuste estatístico simples e auditável (ex.: taxa de outcome
positivo por dimensão de sinal), sempre com um modo de comparação
"score atual vs. score recalibrado" antes de qualquer substituição, e
sempre exigindo o mesmo mínimo de linhas reais (20) já usado para
`learning_status.ready`. Essa é uma capacidade nova (aprendizado real a
partir de decisão humana), não uma reconstrução de nada do P0–P5.

Esta é uma recomendação, não uma decisão — aguardando aprovação explícita
antes de qualquer início de P6.
