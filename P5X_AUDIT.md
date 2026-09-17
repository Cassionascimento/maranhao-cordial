# P5.X Audit — Executive & Creative Layer (Milestone 0)

Auditoria somente-leitura, exigida antes de qualquer implementação da
ordem P5.X (Conselho Multimodal + Presentation Engine + Pirret Creative
Studio). Nenhum código foi escrito nesta etapa. SHA de referência: `main`
em `e62c172` + estabilização pós-live (`chore/estabilizacao-pos-p0-p5`).

> **Correção de nomenclatura (não arquitetural):** a versão original
> deste documento usava "Pires" para o papel de direção criativa
> multimodal. Foi confirmado que "Pires" foi um erro de nomenclatura da
> especificação -- o agente correto e já existente é **Pirret**
> (Marketing). Nenhum agente novo foi ou será criado; a seção 8 abaixo
> foi reescrita para refletir isso.

Convenção de classificação:
- **EXISTE** — já implementado e funcional hoje.
- **REUTILIZAR** — usar exatamente como está, sem modificar.
- **ESTENDER** — módulo existe, precisa de campos/rotas novas dentro dele.
- **CRIAR** — não existe equivalente; precisa nascer do zero.
- **NÃO NECESSÁRIO** — a ordem cobre algo que já é resolvido por outro caminho.

---

## 1. Conselho de Agentes atual

**EXISTE.** `mi_conselho.py` define `AGENTES` (8 especialistas: pirret/
Marketing, standard/Financeiro, zilda/Pessoas, leonard/Vendas, marie/
Produto, rua/Operações, dicio/Jurídico, iris/Dados) e `TIPOS_REGISTRO =
('reuniao', 'conclave', 'relatorio')` persistidos via `registrar_registro`
(migration 016 + 017 payload_hash). `mi_conselho_orquestrador.py` já
resolve prompt de cada agente a partir de `.claude/agents/<agente>.md`.
`mi_conselho_executor.py` chama a OpenAI Responses API
(`cliente.responses.create`, `text.format.json_schema strict`) por
agente, valida o "parecer" contra um schema obrigatório e agrega
divergências/vetos/números citados.

→ **REUTILIZAR** integralmente para M2/M3; a mudança de M2 é só na FORMA
do parecer retornado (ver item 7).

## 2. Modelos de reunião

**EXISTE.** "reuniao"/"conclave"/"relatorio" já são tipos de registro de
primeira classe em `mi_conselho.py` (`registrar_registro`,
`leitura_conselho`, `_ultima_versao_apenas`). Cada reunião já tem
identidade própria (registrada via hash de payload desde a migration 017).

→ **REUTILIZAR**: um artefato (deck/imagem/gráfico) referencia esse
`registro_id`/`meeting_id` existente — não criar uma segunda entidade de
"reunião".

## 3. Decisões

**EXISTE** (P3/P4/P5): `mi_decisao.py` (`registrar_item_fila`,
`avancar_estado_fila`, `TRANSICOES_PERMITIDAS`) + `mi_outcome_
relacionamento.py` (`registrar_recomendacao_apresentada`,
`registrar_decisao_humana`). `decisoes_empresariais` também existe em
`main.py` como tabela separada para decisões de nível empresarial
(fora do Conselho).

→ **REUTILIZAR**: `decision_id` no contrato de artefato (M1) aponta para
uma dessas chaves já existentes (`chave` de `mi_fila_operacional` ou id de
`decisoes_empresariais`), nunca uma tabela nova de decisão.

## 4. Outcomes

**EXISTE** (P3/P4/P5): `mi_outcome_relacionamento.registrar_outcome`,
`historico_decisoes`, `contagem_por_estado`, `exportar_dataset_
aprendizado`. Já versionado (`LEARNING_DATASET_VERSAO`).

→ **REUTILIZAR** sem alteração para M1 (`artifact → outcome`, se algum dia
fizer sentido, é só mais uma referência de chave, nunca lógica nova).

## 5. Sistema de assets/anexos existente

**EXISTE, mas para documentos textuais, não para artefatos visuais.**
`documentos_empresariais` (main.py, linha ~1489) já tem exatamente o
padrão de **versionamento/lineage** que a ordem pede para artefatos:
`status_documento` (`vigente`/`rascunho`/`historico`) +
`substitui_documento_id UUID` apontando para o documento anterior — ou
seja, o princípio "nunca sobrescrever silenciosamente, sempre nova versão
com link pro pai" **já é um padrão comprovado em produção** neste projeto,
só que para PDFs/textos administrativos, não para artefatos criativos.

→ **NÃO REUTILIZAR A TABELA** (é de domínio diferente — documento
administrativo, com `nivel_acesso`/`usar_na_ia` que não fazem sentido para
um rótulo ou deck), mas **REUTILIZAR O PADRÃO** de `status` +
`substitui_id` como modelo direto para a tabela nova de artefatos (M1).

## 6. Storage disponível

**EXISTE — Postgres BYTEA, comprovado em produção.**
`documentos_empresariais.conteudo BYTEA NOT NULL` guarda o arquivo inteiro
dentro do Postgres (limite atual de 15 MB por arquivo, aplicado em
`main.py`). Não há nenhum object storage externo configurado (ver item 15).

→ **REUTILIZAR o mesmo mecanismo (BYTEA em Postgres) como o provider
padrão/`LIVE` de `ArtifactStorage`** para a primeira versão (M14) — é a
única forma de persistência real e comprovada disponível hoje, sem exigir
nenhuma configuração nova de infraestrutura. Ressalva a registrar: imagens
e PPTX tendem a ser maiores que os documentos atuais (15 MB) e múltiplas
versões por artefato multiplicam o volume no banco — isso é um risco de
escala a monitorar, não um bloqueio para a primeira entrega.

## 7. Agentes e prompts atuais

**EXISTE.** 8 arquivos `.claude/agents/*.md` (dicio, iris, leonard, marie,
pirret, rua, standard, zilda), cada um com persona e escopo já definidos
(ver listagem de agentes disponíveis desta sessão). O parecer retornado
por `executar_especialista` hoje é **verboso e textual**: `dados_
utilizados`, `conclusao`, `riscos`, `divergencias`, `acao_sugerida`,
`numeros`, `lacunas` — strings longas, não o formato compacto
`{facts, evidence, interpretation, recommendation, confidence,
disagreement, requested_visual}` que a ordem pede em M2.

→ **ESTENDER** o schema JSON de `_extrair_parecer_validado`/
`_CAMPOS_OBRIGATORIOS_PARECER` para incluir `requested_visual` e
reestruturar os campos textuais atuais em arrays curtos — sem reescrever
o mecanismo de chamada (Responses API, json_schema strict, validação de
proveniência de números), que já funciona e é testado.

## 8. Especificamente o agente Pirret (correção: "Pires" foi erro de nomenclatura)

**EXISTE — RESOLVIDO.** A ordem original mencionava um agente "Pires";
confirmado pelo usuário que isso foi um erro de nomenclatura da
especificação, não uma intenção de criar um agente novo. Busquei "Pires"
em todo o código-fonte na auditoria original: as únicas ocorrências eram
falsos positivos (substring de `EXPIRES_AT` em `x_conector.py`/
`linkedin_conector.py`) — ou seja, não havia nem há necessidade de criar
esse nome. O agente correto e canônico é **Pirret** (`.claude/
agents/pirret.md`, área Marketing, persona "Virgil Abloh x minimalismo
Kanye West", já com a regra "nunca publica nada sozinho").

→ **REUTILIZAR/ESTENDER, nunca CRIAR**: a capacidade de direção criativa
multimodal (M6) é incorporada ao **Pirret existente**, sem renomeá-lo,
sem alterar sua persona/identidade de Marketing já definida, e sem criar
um segundo agente. Pirret ganha a responsabilidade de orquestrar briefing
→ geração visual (via `ImageGenerationProvider`) → artefato versionado,
mas continua sendo, por definição, o agente de Marketing do Conselho —
nunca um "designer" isolado.

## 9. Endpoints do Admin

**EXISTE — inventário completo em `P6_READINESS_REPORT.md`** (21 rotas
P0–P5, 17 GET + 4 POST, todas sob `/api/admin/mi/*`, todas atrás de
`validar_admin_request`/`before_request` global). Documentos empresariais
têm suas próprias rotas (`/api/admin/documentos*`), fora do namespace
`mi/`.

→ **REUTILIZAR o padrão de rota** (`registrar_rotas_leitura`/
`registrar_rotas` por módulo, chamado explicitamente em `main.py`,
auditado por `tests/test_main_routes_audit.py`) para os endpoints novos
de M1/M4/M5/M6.

## 10. Contratos Maranhão Intelligence

**EXISTE.** `mi_intelligence_api.py` (P5): contrato canônico por
relacionamento, overview executivo, fila de decisão — com taxonomia de
proveniência `REAL/DERIVED/INFERRED/SYNTHETIC_TEST/NOT_ENOUGH_DATA` já
estabelecida e testada.

→ **REUTILIZAR a mesma taxonomia de proveniência** para artefatos e
gráficos (M1/M5): um gráfico "aguardando dados" deve usar exatamente
`NOT_ENOUGH_DATA`, nunca inventar um novo vocabulário de estado.

## 11. Bibliotecas Python/JS já instaladas

**EXISTE (`requirements.txt`)**: Flask, Flask-SocketIO, python-dotenv,
requests, gunicorn, `psycopg2-binary`, **openai** (SDK já usado, mas só
via `.responses.create` — nunca `.images.generate`), `pypdf`, Google
Analytics Data + Google API/OAuth libs. JS: só `express`/`socket.io`
(usados pelo `server.js`, não pelos testes/painel, que usam só Node
builtins).

→ **REUTILIZAR o cliente OpenAI já configurado** (mesma env var de API
key, mesmo padrão de timeout/retries) como um dos providers de imagem em
M7 — não é preciso uma segunda credencial só para isso.

## 12. Dependência para PPTX

**NÃO EXISTE.** Nenhuma biblioteca de geração de PPTX no
`requirements.txt` (nem `python-pptx`, nem alternativa).

→ **CRIAR**: adicionar `python-pptx` (biblioteca padrão de mercado, gera
`.pptx` real sem depender de PowerPoint/LibreOffice instalado, licença
MIT) como nova dependência declarada explicitamente em M4.

## 13. Dependência para gráficos

**NÃO EXISTE.** Nenhuma lib de gráfico (`matplotlib`, `plotly`, etc.) no
`requirements.txt`.

→ **CRIAR**: adicionar uma lib de geração de gráfico server-side em M5.
Critério a decidir em M5 (não nesta auditoria): `matplotlib` (mais leve,
gera PNG estático, suficiente para slides de PPTX) é o candidato natural
dado que o M5 pede gráfico **factual embutido no slide**, não interativo.

## 14. Infraestrutura de arquivos no Render

**NÃO VERIFICÁVEL LOCALMENTE — sem acesso ao painel do Render nesta
sessão** (mesma limitação já registrada no fechamento P0–P5: não há
`render.yaml`/`Procfile` versionado, a configuração vive só no dashboard).
O que dá para afirmar com segurança pelo próprio código: main.py já
assume filesystem local só para o `FRONTEND_FOLDER` estático (arquivos do
repositório, não uploads), e todo upload de usuário (`documentos_
empresariais`) já vai para Postgres, não para disco — ou seja, o próprio
projeto já evita depender de disco efêmero do Render para dado do
usuário. Isso é evidência indireta forte de que a equipe já sabia do
problema de efemeridade do Render e o resolveu via banco.

→ **NÃO NECESSÁRIO** reconfirmar isso com o usuário antes de M1: o
padrão-ouro do próprio projeto já é "nunca contar com disco para dado do
usuário" — vou seguir esse mesmo padrão via Postgres BYTEA (item 6).

## 15. Possibilidade de object storage persistente

**NÃO CONFIGURADO.** Nenhuma variável de ambiente, biblioteca (`boto3`,
SDK de Cloudinary/Supabase/R2) ou código de object storage externo
encontrado em todo o repositório.

→ **CRIAR a interface abstrata `ArtifactStorage`** (M14) com o provider
Postgres-BYTEA como `LIVE` desde o primeiro commit, e deixar um segundo
provider (S3-compatível, por exemplo) como stub explicitamente marcado
`NOT_CONFIGURED` até que o usuário decida configurá-lo — nunca fingir que
existe.

## 16. Mecanismos atuais de autenticação/admin

**EXISTE**, já auditado e testado no fechamento P0–P5: `before_request`
global em `main.py` (`proteger_administracao_p0`) intercepta todo
`/api/admin/*`, delega para `validar_admin_request()` →
`email_seguranca.admin_autorizado(chave, namespace)` (comparação
constant-time via `hmac.compare_digest`).

→ **REUTILIZAR sem alteração** para todas as rotas novas de M1/M4/M5/M6 —
elas só precisam viver sob `/api/admin/mi/...` para herdar a proteção
automaticamente.

## 17. Sistema atual de auditoria

**EXISTE, mas distribuído por subsistema, não um log único genérico.**
Cada camada já registra sua própria trilha: `mi_conselho.registrar_
registro` (reuniões/conclaves, com hash de payload desde a migration 017),
`mi_outcome_relacionamento` (apresentação → decisão → outcome, com
timestamps), `mi_decisao`/`mi_fila_operacional` (transições de estado
permitidas, `TRANSICOES_PERMITIDAS`). Não existe uma tabela `auditoria`
genérica cross-domínio.

→ **REUTILIZAR o padrão** (cada subsistema audita a si mesmo com
timestamp + quem/o quê) para artefatos: `created_at`/`approved_at` no
próprio contrato de artefato (M1) já é suficiente e consistente com o
resto do sistema — **NÃO NECESSÁRIO** criar uma tabela de auditoria
central nova.

## 18. Sistema atual de aprovação human-in-the-loop

**EXISTE e é o mecanismo mais maduro do projeto** (P3–P5):
`mi_outcome_relacionamento` never executa nada sozinho — toda
recomendação passa por `registrar_recomendacao_apresentada` →
**decisão humana obrigatória** (`registrar_decisao_humana`) →
`registrar_outcome`. Nenhuma rota de escrita em P0–P5 dispara ação
externa (WhatsApp/Gmail/Meta/pagamento) — confirmado por teste AST
(`NenhumaAcaoExterna.test_modulo_nunca_chama_canais_externos_ou_llm`).

→ **REUTILIZAR exatamente o mesmo desenho** para artefatos: um artefato
gerado nasce em `status=rascunho`/`gerado`, só vira `aprovado` por ação
humana explícita (mesmo padrão de `avancar_estado_fila`), e a publicação
externa (Instagram/WhatsApp/site) continua um passo manual fora do
sistema — nunca automatizado por esta camada (M13).

---

## Resumo por milestone (o que cada um herda desta auditoria)

| Milestone | Classificação predominante | Nota |
|---|---|---|
| M1 Artifact Contract | CRIAR (tabela nova), mas **modelada** no padrão `status`+`substitui_id` de `documentos_empresariais` | — |
| M2 Executive Meeting Contract | ESTENDER (roteamento por assunto **já existe** em `mi_conselho_orquestrador.classificar_especialistas`; só o formato do parecer muda) | Achado importante: não é preciso criar roteamento, só compactar o schema |
| M3 Executive Secretary | CRIAR (papel novo; `mi_diretor.py` existente é um agregador de alerta para humano, não um sintetizador de deliberação — função diferente) | — |
| M4 Presentation Engine | CRIAR (`python-pptx` novo) | — |
| M5 Chart Engine | CRIAR (lib de gráfico nova), mas **REUTILIZAR** a taxonomia `NOT_ENOUGH_DATA` do P5 | — |
| M6 Pirret multimodal (correção: "Pires" era erro de nomenclatura) | ESTENDER o Pirret existente, nunca criar agente novo | Ver item 8 |
| M7 Image Generation Provider | ESTENDER o cliente OpenAI já configurado (novo método, mesma credencial) + CRIAR abstração de provider | — |
| M14 Storage | REUTILIZAR Postgres BYTEA como provider `LIVE`; CRIAR só a interface abstrata | — |
| M16/M18 (auth, aprovação) | REUTILIZAR integralmente, sem alteração | — |

Nenhuma tabela, rota ou serviço P0–P5 precisa ser duplicado para
implementar P5.X. O item 8 (identidade de "Pires") foi resolvido pelo
usuário como correção de nomenclatura: não há mais nenhum ponto em aberto
antes de iniciar M1.
