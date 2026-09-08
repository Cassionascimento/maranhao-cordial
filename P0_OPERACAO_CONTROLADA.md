# Operação controlada P0

O cron usa `python gmail_sync_only_job.py`. Essa entrada nova falha por arquivo
ausente em imagens antigas, impedindo o fluxo antigo sync + Fase 5.8 na retomada.
`gmail_sync_job.py` faz somente sync. `prospeccao_job.py` preserva o fluxo separado,
exigindo `PROSPECCAO_JOB_HABILITADO=true`; não habilitar nem agendar nesta janela.

As rotas abaixo herdam a autenticação administrativa P0 (`X-Admin-Key`):

- POST `/api/admin/email/supervisionado/autorizar`: JSON com exatamente
  `destinatario`, `assunto`, `texto`, `motivo`. Apenas um endereço simples.
- POST `/api/admin/email/supervisionado/<autorizacao_id>/enviar`: JSON `{}`.
  Não aceita alteração de destinatário ou conteúdo.

A autorização armazena MIME imutável e SHA-256, expira em dez minutos e é consumida
em transação com bloqueio de linha antes do Gmail. Exige as duas pausas ativas e
respeita supressões. Nenhum adaptador normal usa esta exceção. MIME contém assinatura
institucional e Message-ID próprio; cria uma nova thread (não responde a terceiros).

Não há retry da submissão. Timeout, crash ou falha posterior ao consumo mantém a
autorização indisponível. Reconciliar Gmail/CRM por Message-ID; nunca tentar reenviar
com outra autorização para compensar uma resposta incerta. O estado `incerto` não
significa que Gmail rejeitou a mensagem. Credenciais e pausas não são alteradas.

Nova tabela aditiva `email_autorizacoes_unicas_p0`; eventos na tabela de segurança
P0 e saída no CRM com Gmail ID, thread ID e vínculo à autorização. Não apagar dados.

Testes offline: `python3 -B -m unittest discover -s tests -p 'test*.py'` e
`node --test tests/test_gmail_oauth_ui.cjs`. Testes concorrentes usam um banco
transacional simulado; não substituem garantias de locks do PostgreSQL real.
