# Correção de transações e recuperação de status

## Base e produção verificadas

Base de código: `7e34856d509a0c91a26523ac64b49b94cfd9ca2d` (origin/main).
Trabalho isolado: branch `codex/omnichannel-transacoes`.
Nenhum arquivo do worktree do Claude ou do ADM foi substituído.

API e site em produção, consultados no Render nesta rodada:
`c4f94fe9fddfacbf3d9a9b4df29db90305759a80`.
API deploy `dep-danj1qegekts739552s0`; site deploy `dep-danj1pv40ujc73c497k0`.
Rollback de código: manter esses deploys como referência. Não reverter migrations
aditivas apagando tabelas ou histórico. Auto Deploy permanece desligado.

## Código testado

- SAVEPOINT isola somente a tentativa de registrar identidade de canal. Apenas
  `UndefinedTable`, com ausência confirmada de `crm_identidades_canal`, permite
  continuar. O rollback ao savepoint preserva o lead e o vínculo da interação.
- Conflitos reais de `crm_identidade.IdentidadePendente` entram em
  `pendente_identidade`; não chamam IA nem criam proposta. Outros erros SQL
  propagam e fazem rollback do vínculo em andamento.
- Status não persistido fica em `status_pendente`, com evento original durável,
  erro tipado e auditoria. Não é marcado como concluído. ACK só depois do commit
  dessa pendência. Se a gravação da pendência também falhar, retorna erro.
- Reentregas de pendências não repetem a tentativa. Recuperação administrativa:
  `POST /api/admin/omnichannel/whatsapp/reprocessar-status`, com autenticação
  administrativa existente e JSON `{"limite":25}` (1–50).
- Cada chamada faz no máximo uma tentativa por evento. Teto total de cinco;
  depois `status_revisao`, visível no painel, exige investigação humana. Nenhum
  novo job. Não há reativação automática de eventos em revisão.
- A recuperação também encontra eventos legados concluídos cuja última evidência
  de status é `status_nao_registrado`. Não reabre eventos com status confirmado.
- Lock transacional por message_id preserva monotonicidade sob concorrência.
- Recuperação não chama IA nem transporte. Aprovação humana e
  `envio_liberado=False` preservados.

## Migrations: revisão, não aplicação em produção

| Migration | Pré-requisitos | Resultado | Risco |
|---|---|---|---|
| 025 | schema com permissão CREATE | canais_diagnostico_historico e dois índices | acesso ao histórico deve permanecer administrativo |
| 026 | fila_respostas_omnichannel.id UUID com chave única; 002/006 operacionais | whatsapp_status_mensagem, FK, CHECK e dois índices | CREATE/index exige locks; não altera estado de envio |
| 027 | leads_crm.id UUID com chave única | crm_identidades_canal, índice único de identidade, crm_fusao_auditoria; três colunas fundido_* em leads_crm | ALTER TABLE requer lock; identidade tem ON DELETE CASCADE, embora a migration não delete dados |

Consulta somente leitura em produção confirmou os tipos UUID e estruturas de
002/006, inclusive whatsapp_message_id. As quatro novas tabelas e as três
colunas fundido_* estavam ausentes. Nenhuma migration foi aplicada em produção.
Não foi localizado runner versionado no checkout; não se presume execução ou
registro automático. Não existe novo endpoint público para migrations.

Procedimento para operador com acesso de escrita já configurado no ambiente:
1. Usar checkout revisado e fixado por SHA; confirmar banco maranhao_cordial.
2. Uma transação SQL, advisory transaction lock para migrations, lock_timeout
   curto e statement_timeout limitado. Executar os três arquivos existentes na
   ordem 025, 026, 027. Qualquer erro deve causar rollback integral.
3. Na mesma transação, conferir tabelas, três colunas, FKs/CHECKs e índices
   definidos nos arquivos. Commit somente com catálogo correspondente.
4. Registrar SHA, hashes dos arquivos e resultado sem URL/token. Não imprimir
   dados pessoais. Havendo estrutura parcial ou incompatível, parar e revisar.
5. Publicar o código testado pelo fluxo manual existente; conferir SHAs live dos
   dois serviços. Não publicar se as migrations não estiverem confirmadas.
6. Diagnóstico autenticado dos canais, somente leitura nas plataformas. Executar
   um lote controlado de recuperação de status, verificar auditoria e pendências.

## Evidência local

- 118 testes Python específicos aprovados, incluindo 10 em PostgreSQL 18 real,
  mais 3 subtests. Rede externa proibida nos testes de transação.
- 4 testes de auditoria de rotas aprovados.
- 22 testes JavaScript de WhatsApp/canais aprovados.
- git diff --check aprovado.
- PostgreSQL temporário: schemas exclusivos, sem DATABASE_URL. Migrations 025–027
  aplicadas duas vezes nesses schemas; catálogo validado. Os testes cobrem
  ausência de 027, vínculo/auditoria/proposta, conflito real, erro SQL distinto,
  status sem 026, replay depois de criar tabela, cinco tentativas, falha de
  auditoria, replay legado, concorrência e autorização do endpoint.
- Pré-requisitos básicos de CRM/omnichannel no teste são fixtures SQL mínimos;
  IA mockada. Isto comprova transações PostgreSQL, não conexão Meta em produção.

## Bloqueios reais

Conector Render de SQL é somente leitura. Não há DATABASE_URL ou RENDER_API_KEY
no processo nem .env no worktree atual. Dashboard Render requer login pessoal.
Sem acesso de escrita confirmado: aplicação em produção, publicação e diagnóstico
remoto autenticado do código novo continuam pendentes.

WhatsApp/CRM: correção interna testada; estado operacional Meta não foi inferido.
TikTok Shop: main contém diagnóstico de Shop separado do TikTok Social; OAuth
social não comprova catálogo/pedidos/loja. Nenhum token ou integração nova foi
configurado nesta rodada. LinkedIn pessoal preservado integralmente.
