# WhatsApp Omnichannel — conclusão interna antes de push/deploy

Estado: implementação interna concluída e testada com payloads simulados. Conector permanece `aguardando_meta` ou `disconnected`; nenhum envio liberado. Commit de base preservado: `760d8502df65b90c7746d3292377294a44c76a99`.

## Arquivos e diff funcional

- `main.py`: encaminha somente eventos `whatsapp_business_account` ao receptor com checkpoints; registra o painel autenticado; limita o tamanho do webhook. Verificação HMAC e demais canais preservados.
- `whatsapp_meta.py`: normalização preservada, validação de tamanho/tipo e rejeição de IDs conflitantes dentro do mesmo lote; não baixa anexos.
- `whatsapp_omnichannel.py`: persistência da entrada antes da IA; interação omnichannel; associação ao CRM por telefone completo normalizado; classificação e sugestão sem ferramentas; fila manual; checkpoints, recuperação por reentrega e auditoria; status interno sem consultar a Meta.
- `whatsapp_aprovacoes.py`: bloqueio adicional enquanto a Meta não estiver validada. Regras de conteúdo aprovado, uso único, pausas e janela existentes preservadas.
- `migrations/006_whatsapp_omnichannel.sql`: tabelas aditivas `whatsapp_processamentos` e `whatsapp_entrada_auditoria`, FKs e índices. Sem DELETE/DROP/UPDATE de dados existentes; depende da migration 002. **006 não aplicada em produção.**
- `maranhao-backend/admin.html`: painel WhatsApp na seção IA; botão WhatsApp passa a aprovar sem executar envio; fluxo dos outros canais preservado.
- `maranhao-backend/whatsapp-omnichannel.js`: monitor autenticado de entradas, classificação, contato, fila, erros, auditoria e dependências Meta. Apenas GET.
- `tests/test_whatsapp_omnichannel.py`: fluxo interno completo, falhas, retomada, identidade, assinatura, auditoria, status, adapter IA e bloqueio de envio.
- `tests/whatsapp_sqlite.py`: banco temporário isolado, com adaptação explícita de dialeto para executar as consultas do repositório real. Nenhum acesso ao banco de produção.
- `tests/test_whatsapp_routes.py`: regressões das rotas afetadas usando o novo receptor.
- `tests/test_whatsapp_aprovacoes.py`: cenário futuro conectado apenas em mock; chamadas de transporte continuam simuladas.
- `tests/test_whatsapp_ui.cjs`: aprovação/rejeição WhatsApp sem envio, preservação do outro canal, status autenticado e conteúdo como texto.
- Este relatório.

## Testes executados e resultados

38 testes Python específicos aprovados ao longo das execuções: 18 de integração interna, 4 de rotas, 9 de normalização/receptor anterior e 7 de aprovação/transporte simulado. 5 testes JavaScript específicos aprovados.

Comandos utilizados:

```text
PYTHONPATH=tests:. python3 -m unittest test_whatsapp_omnichannel test_whatsapp_routes test_whatsapp_meta test_whatsapp_aprovacoes -v
PYTHONPATH=tests:. python3 -m unittest test_whatsapp_omnichannel test_whatsapp_meta test_whatsapp_routes -v
PYTHONPATH=tests:. python3 -m unittest test_whatsapp_omnichannel.Integracao.test_adaptador_ia_sem_ferramentas_ou_transporte -v
PYTHONPATH=tests:. python3 -m unittest test_whatsapp_omnichannel.Integracao.test_aguardando_meta_bloqueia_aprovada_mesmo_sem_pausas -v
node --test tests/test_whatsapp_ui.cjs
```

Os testes adicionais e reruns ocorreram somente após alterações específicas. Não foi rodada a suíte completa, nem testes de Gmail/território. Compilação Python, sintaxe do JavaScript novo e scripts inline do Admin, e `git diff --check` aprovados.

Verificação visual em prévia localhost com payload simulado: `disconnected`, classificação, contato CRM, proposta aguardando aprovação, etapas de auditoria e dependências Meta exibidos. Nenhuma gravação ou requisição à produção nesse teste.

Resultados comprovados internamente:

- Entrada assinada cria um contato, uma interação classificada e uma proposta manual com IDs rastreáveis.
- Reentrega concluída não duplica contato, interação, proposta ou auditoria e não repete IA.
- Falha da IA preserva entrada/interação. Falha posterior à classificação reutiliza o checkpoint da IA.
- Conteúdo conflitante para a mesma identidade é rejeitado. Metadados originais são preservados na retomada.
- Telefone formatado corresponde ao mesmo telefone completo; país/DDD não são inferidos. Múltiplos contatos ou contatos internos/arquivados/de teste exigem revisão, sem associação arbitrária.
- Status de entrega/leitura não cria contato nem chama IA. Áudio/mídia não é baixado ou transcrito.
- Aprovação grava conteúdo e auditoria, sem transporte. `aguardando_meta` bloqueia execução até em cenário com pausas desativadas e credenciais fictícias presentes.
- IA recebe apenas a mensagem e o tipo, sem acesso a ferramentas ou executor. Saída inválida/falha não é marcada como classificação concluída.

## Limites, riscos e dependências externas

- A migration 006 e as transações/locks reais devem ser validados no PostgreSQL antes de uma publicação autorizada. O banco SQL temporário valida persistência/consultas adaptadas e rollback, mas não substitui a validação do catálogo e da concorrência PostgreSQL. Lock ocupado foi testado por simulação separada.
- O receptor processa IA de forma síncrona. Lentidão/timeout pode provocar reentrega; a entrada durável e os checkpoints permitem retomada. Se a Meta encerrar suas reentregas, uma entrada pendente precisará de intervenção operacional; não foi criado novo job.
- Respostas reais do provedor IA não foram solicitadas. O adaptador e o contrato foram testados com respostas simuladas. Toda sugestão exige revisão humana; não é promessa comercial nem fato confirmado.
- Não há download/transcrição de mídia nem templates/prospecção WhatsApp nesta entrega.
- A prontidão do conector não é inferida pela presença de variáveis. O bloqueio de transporte permanece fechado no código; eventual liberação exige validar os ativos Meta e uma nova autorização de operação.

Dependência Meta conhecida: número offline/não verificado, conforme estado informado pelo usuário. Não foi feita nova consulta à Meta nem tentativa de contorno. Antes de liberar operação, confirmar:

1. Número online/verificado e seu Phone Number ID.
2. WABA correta, vínculo do app e assinatura do campo `messages`.
3. Token válido com acesso ao ativo e `whatsapp_business_messaging`; permissões de gestão/validação `whatsapp_business_management` quando utilizadas.
4. App secret e verify token correspondentes ao webhook publicado.

A disponibilidade atual de token, WABA e permissões não foi revalidada externamente; não se afirma que estejam ausentes. O painel mostra apenas presença/ausência de configuração, sem expor valores secretos.

## Preservação e próxima etapa

Nenhum push ou deploy. Nenhuma migration aplicada nesta etapa. Nenhuma mudança de credencial, quota, pausa, cron, Gmail, prospecção ou job suspenso. Arquivos do motor/API territorial permanecem iguais ao SHA de base; os acréscimos ao Admin/main são exclusivamente WhatsApp.

Nenhuma mensagem real de WhatsApp, e-mail comercial, cobrança ou outra ação externa foi realizada. Aprovação continua obrigatória e não libera automaticamente transporte. Próxima etapa depende de avaliação deste relatório e autorização de publicação; manter o conector sem envio.
