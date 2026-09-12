# Integração isolada Claude + Codex — 12/09/2026

Base: e605b5b7e5ce1a576ab0e0cfd70663e40c6b6f25 (origin/main).
Branch: integracao/claude-codex. Sem commit, push, deploy, migration ou transporte.
O worktree original permanece em 51a1fc9; nenhum arquivo foi descartado.

## Inventário de decisões

| Grupo | Classe | Tratamento |
|---|---|---|
| acoes_comerciais.py, entrada_segura.py, prospeccao_controle.py | A integrar agora | Deltas locais preservados; testes de digest, pausas, quotas e reservas |
| autonomia_supervisionada.py e testes | A | Integrados como preparação offline; adaptadores explicitamente injetados, nenhum adaptador real registrado |
| main.py | A parcialmente / C versão integral substituída | Somente fábrica compartilhada, briefing por callback explícito e registro de rotas; não copiado sobre remoto |
| gmail_legado.py, cors_sac.py, respostas_publicas.py | A preservar remoto | Intactos; remetente legado continua negando transporte |
| Admin reorganizado / MI | A preservar remoto | Conteúdo remoto preservado, adição pontual da seção TikTok e scripts de leitura |
| painel-executivo.js | C delta direto substituído | Mantida projeção sem rede; monitor local extraído em autonomia-supervisionada.js |
| TikTok módulo/JS/testes | A código / B banco | Espelho manual; sem OAuth, integração de credenciais ou automação. Prompt automático na IA não incorporado nesta rodada |
| services/* e templates/ia/capturar_documento.html | B | Todos os seis arquivos estão vazios; não são componentes funcionais a duplicar |
| scripts aplicar/instalar, backups, preview e relatórios históricos | B | Preservados no original; não necessários ao runtime integrado |
| migrations locais 007/008 | D decisão de schema | Não copiadas nem renomeadas; proposta abaixo |
| WhatsApp | A correção mínima | Prontidão pura vinculada a empresa/conector; transporte continua bloqueado |
| SaaS | B | Nenhuma implantação multi-tenant nesta rodada |

Classe C é decisão sobre conteúdo a integrar, NÃO exclusão de arquivos originais.

## Banco e proposta de numeração (não aplicada)

Informação externa fornecida pelo usuário: MI 007–012 refletido no banco; existe
`tiktok_oauth_credentials`; não se encontrou autonomia_* nem ledger evidente.
Não houve consulta de banco nesta rodada. OAuth não comprova espelho de catálogo.

Proposta: 013_tiktok_shop_espelho.sql e 014_autonomia_supervisionada.sql, sujeita
à confirmação de que não foram reservados outros números e à leitura do catálogo.
Não criados, não renomeados e não executados. Migrations MI 007–012 intactas.

### Contrato local TikTok
- tiktok_shop_registros: loja, tipo (catalogo/pedido/cliente), externo_id, versao,
  dados JSONB, origem, lead_id, atualizado_em. PK(loja,tipo,externo_id).
- tiktok_shop_historico: id BIGSERIAL, loja, tipo, externo_id, versao, dados JSONB,
  origem, lead_id, registrado_em. UNIQUE(loja,tipo,externo_id,versao).
- Ambas referenciam leads_crm(id). Índice tiktok_shop_crm_idx(lead_id).
Não cria OAuth, pedidos internos, estoque ou vendas. Continua necessária se o
espelho não existir. A existência de ambas as tabelas e suas colunas é desconhecida.

### Contrato local autonomia
- autonomia_politicas: versao PK, habilitada (default true), limite_continuacoes
  (0..2, default 2), criado_em; seed supervisionada-v1 sem sobrescrever existente.
- autonomia_execucoes: chave PK, versao FK, tipo, acao_id FK, destinatario,
  digest, estado (reservada/enviada/incerta), resultado JSONB, criado_em, concluido_em.
- autonomia_evidencias: acao_id PK/FK, versao FK, modelo, digest, criado_em.
- Índice autonomia_execucoes_dia(criado_em,tipo).
Depende de acoes_comerciais_propostas (001); operação também depende do schema
CRM, Gmail/P0, campanhas e briefings existente. Continua necessária para persistir
as reservas se não existir schema equivalente. Ausência ainda não confirmada localmente.

Os contratos SQL são reproduzidos somente como literais de testes offline;
não há migration operacional nova. IF NOT EXISTS não valida schema divergente.
Não aplicar os contratos sem verificação das colunas/FKs/índices existentes.

## Conflitos resolvidos

- O legado Gmail extraído permanece bloqueado; o briefing recebe callback
  reservado explicitamente. Não há reinstalação da função antiga em main.
- Navegação, MI, Governança e Visão Geral remotos preservados.
- Monitor de autonomia separado da projeção executiva sem fetch.
- Testes corrigidos com MagicMock para protocolo de context manager, sem retirar
  asserts de commit, rollback/savepoints, concorrência, digest ou reservas.
- Nenhum scheduler é iniciado pela integração, mesmo com flags antigas.

## WhatsApp

Receptor, HMAC, normalização, checkpoints, CRM, IA, fila, aprovação e auditoria
reutilizados. `status_conector` conserva compatibilidade e acrescenta prontidao.
Configuração completa -> configurado; evidência backend válida para empresa,
conector, WABA e Phone Number ID -> conectado; IDs rastreáveis de homologação real
-> homologado. Evidência expirada, futura, incompleta ou de outro ativo não avança.
`envio_liberado=False` em todos os estados. Sem chamadas Meta nem provider de
evidência instalado; estado real connected/homologado NÃO afirmado. A persistência
/verificação confiável das evidências e liberação operacional são futuras.

## Limites antes de operação / SaaS

É checkpoint de integração, não release operacional. Não há validação PostgreSQL
real. O schema de políticas/reservas herdado ainda é global; consultas recebem
factory e transportes recebem adaptadores por contexto, sem novos singletons de
credenciais. Essas fronteiras permitem futura implementação por tenant, mas não
substituem RLS/FKs/contexto de autorização. Nenhuma segunda empresa pode ser
habilitada neste estado. Não se inventou tenant_id nem se atribuiu dados existentes.

A integração de autonomia não é homologação comercial: necessita revisão de
eligibilidade/conteúdo e validação transacional PostgreSQL antes de conectar
adaptadores reais. Mantido teto existente de 2 primeiros contatos/dia.

Antes de commit: revisar este diff e a classificação; é possível commit de checkpoint
sem migrations e sem liberação operacional. Antes de deploy: confirmar schema,
resolver contratos/numeração e validar operações com PostgreSQL isolado.
