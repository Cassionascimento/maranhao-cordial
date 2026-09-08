# Migração do agendamento da prospecção

O motor comercial homologado não foi modificado. A nova entrada
`python prospeccao_render_job.py` executa na nuvem o trabalho que a tarefa Codex
fazia: verificar dependências, sincronizar Gmail isoladamente, pesquisar, validar
fonte institucional, chamar o primeiro contato com reserva e conferir Gmail/CRM.

Agenda Render: `0 13 * * 1-5` (UTC), equivalente a dias úteis às 10h de São Paulo.
O executor também exige dia útil, hora local 10 e data inicial configurada.

Configuração inicial segura:

- `PROSPECCAO_RENDER_MODO=seguro` (padrão; nunca pesquisa, reserva ou envia).
- `PROSPECCAO_RENDER_INICIO=2026-09-09` (nenhum primeiro contato em 08/09).
- `EMAIL_ENVIOS_PAUSADOS=true` e `EMAIL_APENAS_PROSPECCAO_CONTROLADA=true`.
- Mesmos `DATABASE_URL`, `ADMIN_API_KEY` e `OPENAI_API_KEY` da API, copiados
  diretamente no Render sem expor valores. Credenciais Gmail continuam no banco.
- `PROSPECCAO_CONTROLADA_HABILITADA=false` impede uso acidental da entrada antiga.
- Autodeploy desligado. API e cron Gmail não precisam de novo deploy.

Somente após smoke seguro com perfil Gmail institucional, banco e modelo
confirmados, armar o cron com `PROSPECCAO_RENDER_MODO=ativo`. A pausa persistente
permanece verdadeira entre envios. O cron só pode retirá-la se o último evento
P0 for exatamente `prospeccao_render: intervalo seguro entre rodadas`. Qualquer
pausa de emergência ou reserva incompleta impede a rodada, inclusive após crash.
O lock global de rodada evita sobreposição; o lock/reserva comercial existente
continua limitando todos os primeiros contatos a 2/dia. Erros não rearmam reservas.

Verificação de fonte: HTTPS público, certificado/SNI verificados, IP público fixado
por conexão, sem cookies/segredos/retries e com limite de tamanho e redirecionamentos.
O endereço deve estar publicado na fonte e usar seu domínio institucional.
Fontes indisponíveis, endereços de exemplo e associações não confirmadas são
exclusões normais da rodada, sem apagar registros ou consumir cota.

Desativar a automação local `maranh-o-cordial-prospec-o-verificada-2-dia` somente
após validar e confirmar o cron Render. Não reativar piloto, briefing, autoteste,
GA4 ou jobs 5.8. Gmail sync permanece ativo e separado.

Checkpoint de código: 95 testes Python aprovados antes da configuração cloud.
Antes de ativar, registrar neste documento o ID do cron e o resultado do smoke.
