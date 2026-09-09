# Referência de origem das ações comerciais

Estado: implementação local, sem migration executada e sem liberação de envios.

## Modelagem

`acoes_comerciais_propostas.origem_tipo` + `origem_id` identificam a entidade
original. Não existe FK heterogênea nem coluna `prospecto_id` nesta tabela nova.

| Tipo | Entidade consultada | ID atual |
| --- | --- | --- |
| `prospecto_fase56` | `prospectos_fabrica_fase56` | UUID |
| `prospecto_fase57` | `prospectos_fase57` | UUID |

O schema usa TEXT para permitir futuros identificadores. A aplicação aceita
somente tipos registrados, valida UUID para os dois adaptadores atuais e verifica
a existência da entidade na tabela correta com SQL fixo e parâmetros. Não aceita
nomes de tabelas fornecidos pelo cliente. Novos tipos exigem adaptador explícito.

A origem também integra `dados` e seu digest aprovado. Trocar o tipo, ID,
destinatário ou mensagem invalida a autorização. O índice composto permite
rastrear as propostas de uma entidade. Não há exclusão em cascata: o ID permanece
no histórico; se a entidade deixar de existir, o executor falha fechado.

## Deduplicação e execução

A chave de primeiro contato é global por e-mail normalizado, sem prefixo da fase.
Assim, Fases 5.6 e 5.7 não criam dois primeiros contatos para o mesmo destinatário.
Respostas usam e-mail + ID da interação recebida, preservado separadamente em
`origem_mensagem`. `ON CONFLICT` preserva integralmente a primeira proposta.

O executor existente de primeiro contato recebe somente origens da Fase 5.7.
A Fase 5.6 pode criar propostas de primeiro contato e resposta; seu primeiro
contato permanece sem transporte habilitado, pois o reservador atual é exclusivo
da Fase 5.7. Não encaminhar IDs da Fase 5.6 a esse reservador e não contornar a
quota. Respostas seguem o executor de respostas aprovadas já existente.

A aprovação não substitui a reserva diária de primeiro contato. O teto de 2/dia,
P0, supressões, deduplicação histórica e ausência de retry incerto permanecem.

## Migration e validação

`migrations/001_acoes_comerciais.sql` é uma primeira instalação transacional, com
timeout de lock de 5s e de instrução de 30s. Usa criação condicional, índice
condicional e inserções idempotentes. Não remove registros. Caso encontre a
coluna preliminar `prospecto_id` numa instalação divergente, aborta integralmente
e exige conversão explícita; não tenta inferir a origem nem reaprovar histórico.

Consultas somente leitura ao PostgreSQL de produção confirmaram:

- PostgreSQL 18.4 e `gen_random_uuid()` disponível;
- tabelas novas ainda ausentes;
- IDs UUID e chaves primárias nas quatro tabelas referenciadas;
- colunas de Gmail e pesquisas compatíveis com a migration;
- 5 pesquisas abandonadas e 1 entrada Gmail pendente;
- privilégio CREATE no schema public para o papel usado na consulta.

Nenhuma instrução da migration foi executada, nem mesmo dentro de rollback.
A compatibilidade do schema foi conferida; execução DDL, tempos reais de locks e
o papel efetivo do futuro deploy ainda requerem validação na janela autorizada.
Os testes locais usam bancos simulados e proíbem transporte real.

`META_APP_SECRET` continua requisito bloqueante da implantação. Não foi buscado,
alterado ou substituído. A configuração correta deve ser confirmada antes de
implantar o webhook que depende dela. Nenhuma pausa é retirada por esta mudança.
