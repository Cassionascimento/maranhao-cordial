# P0 — proteção de Gmail e envios

Implementação local, sem deploy, sem execução da aplicação e sem migração em produção.
Ponto de reversão: tag `reversao-p0-20260908`, commit `af75d98`.
A tag cobre os arquivos versionados; arquivos locais não versionados preexistentes
foram preservados e não integram a tag.

## Autenticação

As APIs administrativas usam a mesma validação, com falha fechada quando não há
chave. Precedência: `ADMIN_API_KEY`, `ADMIN_KEY`, `ADMIN_SECRET`, `PAINEL_ADMIN_KEY`.
Aliases são fallback, não chaves alternativas simultâneas. Enviar `X-Admin-Key`.
Se valores diferentes estavam configurados, usar a chave canônica no cliente.
Nenhuma variável ou credencial existente foi alterada por esta implementação.

`GET/POST /api/gmail/conectar` e `GET /api/gmail/sincronizar` exigem esse cabeçalho.
O botão "Conectar Gmail institucional" usa a chave da sessão administrativa do painel
e abre `/api/gmail/painel` em uma janela da API. Essa página não contém dados privados
e só aceita a mensagem do opener com origem explicitamente permitida. A chave é
enviada no cabeçalho de um POST same-origin, nunca na URL ou para o Google.
POST devolve JSON com a URL de autorização; a janela navega ao Google após receber
o cookie first-party, evitando dependência de cookies de terceiros entre site e API.
GET autenticado conserva o redirecionamento para compatibilidade.
As rotas Gmail têm CORS com origens explícitas e no-store; não aceitam wildcard.

O callback usa estado autorizado, vinculado ao navegador, válido por dez minutos e
consumido uma única vez no PostgreSQL. Não exige cabeçalho do redirecionamento Google.
Credenciais e PKCE verifier não são mais gravados em cookies; credenciais OAuth
continuam na tabela existente. Callback sem refresh token ou com outra conta
não substitui a conexão existente. Cookies legados são limpos na próxima requisição.

O fallback público da assinatura de sessão foi substituído por segredo aleatório.
`FLASK_SECRET_KEY` deve estar configurado com valor forte, persistente, compartilhado
e de pelo menos 32 caracteres. Sem essa condição OAuth responde 503, sem derrubar
as APIs administrativas nem apagar a conexão Gmail existente no banco. A configuração
real não foi inspecionada nem alterada. Cookies usam HttpOnly, SameSite=Lax e Secure
quando a aplicação roda no Render. A resposta de autorização usa a URI HTTPS
canônica configurada em `GOOGLE_GMAIL_REDIRECT_URI`, sem confiar no Host ou em
X-Forwarded-* fornecidos pelo cliente. Não é necessário desabilitar HTTPS no OAuth
nem ativar ProxyFix indiscriminadamente. O path configurado deve ser `/api/gmail/callback`.

## Job Gmail versionado — alteração futura no Render

O arquivo `gmail_sync_job.py` substitui o comando inline do serviço
`gmail-sync-maranhao-cordial`. Quando autorizado, configurar Start Command:

```sh
python gmail_sync_job.py
```

Manter a agenda existente. Disponibilizar ao job a mesma chave administrativa
canônica usada na API e preservar `FASE58_CRON_SECRET`. Não há variável nova de URL:
o script usa a URL atual da API. O script não importa `main.py`, não instala schemas
nem inicia o briefing. Exige HTTP 200, JSON com success=true, ausência de erros e
prospeccao_permitida=true antes de chamar a rota 5.8A (que já chama 5.8B).
Timeout, redirect, 401/500/502 ou JSON inválido abortam sem prospecção. Não há retry
automático de disparos nem impressão dos corpos das respostas.

O comando/configuração do serviço real NÃO foi alterado. A API e o job devem ser
implantados coordenadamente; o job novo falha fechado contra a API antiga, que
ainda não fornece `prospeccao_permitida`. Preservar o cron piloto suspenso e não usar
o autoteste de e-mail como teste de deploy.

## Interruptor central

`EMAIL_ENVIOS_PAUSADOS=true` bloqueia todos os envios pelos dois adaptadores.
Ausente preserva os envios existentes. Valores `false`, `0`, `no` liberam apenas
essa trava; qualquer outro valor bloqueia. Nenhuma variável foi configurada aqui.

Há também pausa persistente, compartilhada entre workers:

`POST /api/admin/email/seguranca`, com `X-Admin-Key` e JSON:

```json
{"pausado": true, "motivo": "Investigação de falhas de entrega"}
```

Para retomar, enviar `pausado: false` com motivo. A retomada não remove supressões
nem sobrepõe a pausa por ambiente. Pausas/retomadas deixam eventos de auditoria.
A pausa impede novas chamadas de envio; não revoga mensagens já submetidas ao Gmail.
Payload que não seja objeto JSON, booleano inválido ou motivo ausente retorna 400.

## Supressão

O envio institucional da Fase 5.6 e o adaptador legado de briefing consultam a
mesma supressão antes de obter credenciais e novamente antes de enviar. Isso cobre
primeiros contatos, testes, respostas/follow-ups, alertas e os lotes 5.7/5.8A/5.8B.
Todos os endereços em To/Cc são verificados; um suprimido bloqueia a mensagem inteira.
Banco indisponível ou erro na consulta bloqueia o envio. Não há cache permissivo.

Na sincronização, todos os DSNs do lote são analisados antes de respostas comerciais.
A supressão automática exige:

- `multipart/report` de entrega, remetente técnico e DSN estruturado;
- `Action: failed` e código `5.1.1`, `5.1.2` ou `5.1.3`;
- destinatário RFC822 e Message-ID original anexado;
- confirmação desse Message-ID e destinatário numa mensagem Gmail marcada SENT.

Texto/assunto, 4.x, 5.2.x, 5.7.x e ausência de bounce nunca confirmam hard bounce
de endereço nem entrega. Casos ambíguos permanecem sem supressão automática.
Relatórios técnicos ficam no histórico de interações e não geram resposta comercial.
Eventos repetidos são idempotentes e novas evidências são preservadas.

Falha individual de leitura, DSN ou registro não impede a importação das outras
mensagens. Uma falha torna o resultado parcial (HTTP 502, success=false), impede a
prospecção pelo job e tenta persistir pausa global. O processamento CRM existente
das mensagens importadas continua, mas as saídas ficam bloqueadas no contexto da
requisição mesmo se a gravação da pausa falhar. As mensagens técnicas não passam
pelos classificadores comerciais. A pausa não é removida automaticamente após um
lote posterior bem-sucedido: requer revisão e retomada administrativa.

## Schema e compatibilidade

Quatro tabelas adicionais, criadas no primeiro uso das novas operações:
`email_controle_p0`, `email_eventos_seguranca_p0`, `email_supressoes_p0`,
`gmail_oauth_estados_p0`. Não há DROP, DELETE ou mudança no schema/histórico antigo.
O verifier temporário é limpo ao consumir o estado OAuth, conservando o registro.
O usuário do banco precisa de permissão de criação dessas tabelas. Nenhum DDL foi
executado contra um banco real durante a implementação ou os testes.

Os prospectos suprimidos permanecem nos cadastros com seus estados comerciais
anteriores. Mesmo que sejam selecionados novamente, o adaptador impede a saída.
Remover esses candidatos da seleção e melhorar as métricas são trabalho posterior.

## Testes offline

```sh
python3 -B -m unittest discover -s tests -p 'test*.py' -v
node --test tests/test_gmail_oauth_ui.cjs
git diff --check
```

Os testes extraem funções por AST, sem importar `main.py` e suas inicializações.
Banco, Gmail e OAuth são simulados; conexões de socket são proibidas nos testes.
Sintaxe de todos os arquivos Python locais é compilada em memória, sem executá-los.

## Limites restantes

- A importação existente ainda consulta somente vinte mensagens da caixa de entrada.
  Não houve importação retroativa de bounces, consulta à caixa real ou backfill.
- DSNs sem original, com outro formato ou de destinatário encaminhado podem precisar
  de análise posterior. Correlação não é prova criptográfica de autenticidade do DSN.
- A consulta antes do envio não é uma transação distribuída com Gmail: uma pausa ou
  supressão pode chegar após a última verificação, quando a chamada já está começando.
- Idempotência de submissão/resultado incerto, reserva atômica de quota, limites de
  volume, classificação completa de respostas automáticas, paginação e métricas
  continuam fora desta alteração incremental.
- Os testes não validam permissões/schema real, concorrência PostgreSQL ou configuração
  do agendador de produção. A proteção nova só terá efeito após deploy autorizado.
- A janela OAuth foi testada com DOM/fetch simulados, não com a conta Google real;
  políticas de popup/COOP e cookies do navegador precisam de homologação posterior.
- O CRM mantém o comportamento anterior de deduplicação: respostas automáticas
  bloqueadas durante uma pausa não são reenviadas automaticamente ao retomar.
- Se a persistência da pausa falhar mas outros workers ainda conseguirem ler o banco,
  o bloqueio de contexto cobre apenas a requisição atual. A pausa por ambiente continua
  sendo a trava operacional para todos os processos. Não há transação distribuída.

## Reversão

Para reverter somente o código deste P0, após revisar alterações posteriores:

```sh
git restore --source reversao-p0-20260908 -- main.py fase56_fabrica_piloto.py maranhao-backend/admin.html
```

Os novos arquivos podem permanecer sem uso. Não remover as novas tabelas nem seus
registros. A reversão do código também remove as proteções de envio e autenticação;
se já implantado, avaliar a pausa operacional antes de reverter. Nenhum desses
comandos de reversão foi executado.
Se o novo job já tiver sido ativado, interrompê-lo antes de reverter a API. A versão
anterior ignora `EMAIL_ENVIOS_PAUSADOS` e as novas supressões; a flag não protege um
rollback. Controlar todos os disparadores, inclusive briefing no serviço web.
