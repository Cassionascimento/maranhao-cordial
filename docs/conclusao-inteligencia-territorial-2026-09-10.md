# Conclusão territorial — relatório antes de deploy

Implementação local concluída; publicação e homologação HTTP em produção pendentes. Nenhum deploy territorial realizado. O objetivo WhatsApp não foi iniciado nesta conclusão, respeitando a parada entre objetivos.

## Diff desta conclusão

- `inteligencia_territorial.py`: exclui registros operacionais sintéticos dos agregados; separa potencial para eventos de eventos identificados; preserva estabelecimento e UF explícita nas evidências.
- `tests/test_inteligencia_territorial.py`: regressões para esses casos e para ausência de quantidade, custo e receita mesmo quando há amostra/compra registrada.
- `maranhao-backend/admin.html`: aba territorial, quatro decisões executivas, aprofundamento por bairro/cidade/UF/região e formulário aditivo de fatos observados.
- `maranhao-backend/inteligencia-territorial.js`: consulta autenticada, interpretação somente por clique, evidências em texto seguro, registro com chave preservada em retries. Sem endpoint comercial ou executor.
- `maranhao-backend/inteligencia-territorial.css`: estilos limitados à seção territorial.
- `tests/test_territorio_ui.cjs`: autenticação, leitura sem IA automática, conteúdo seguro, aprofundamento e retry idempotente.
- Este relatório.

A conclusão preserva os commits locais anteriores de dados/motor (`0b9a8cb`) e API/IA (`73da3a9`). A integração da API em `main.py`, `territorio_api.py` e `tests/test_territorio_api.py` já estava concluída e foi revalidada pelos testes específicos. Não houve reescrita desses commits.

## Testes e resultados

- `python3 -m unittest tests.test_inteligencia_territorial tests.test_territorio_api -v`: 27 testes aprovados (18 motor + 9 API).
- `node --test tests/test_territorio_ui.cjs`: 4 testes aprovados.
- `node --check maranhao-backend/inteligencia-territorial.js`: aprovado.
- `git diff --check`: aprovado.
- Prévia local no navegador, com snapshot de dados existentes e gravação/IA desativadas: quatro cartões, lacunas, aprofundamento e formulário conferidos; sem transbordamento horizontal na largura inspecionada (1280 px).
- Não foi executada a suíte completa nem repetida a homologação Gmail.

Fatos são contagens/atributos efetivamente registrados. Sinais são padrões e classificações identificados como tais. Recomendações usam candidatos sustentados pelos registros e não podem elevar a confiança calculada. Lacunas continuam explícitas. Compra não implica circulação física; amostra sem quantidade não gera volume; CAC não vira investimento em mídia; snapshot global não vira audiência territorial.

## Banco e publicação

A migration `005_inteligencia_territorial.sql` já havia sido aplicada antes da instrução mais recente de parada para relatório. Criou somente `territorio_registros`, `territorio_leituras` e seus índices/constraints; não contém DELETE. A repetição foi verificada em savepoint, com rollback do savepoint. Nenhum fato sintético foi persistido nessas tabelas.

O código territorial não foi publicado. O teste de registro da API usou banco simulado; a chamada real à IA e a homologação HTTP da nova API em produção permanecem para a etapa de publicação autorizada. Não tratar a prévia local como homologação de produção.

## Riscos e dependências

- Qualidade/cobertura da base: no snapshot lido, 49 de 96 relações não possuem cidade/UF completas; 52 interações não têm vínculo consolidado. Não há evidência para preencher essas lacunas automaticamente.
- Localização e perfis declarados podem estar desatualizados. A base cadastrada não representa tamanho de mercado nem elegibilidade para contato.
- Custos e conversões precisam pertencer ao mesmo território/ação/período. O registro manual depende da direção evitar relatórios sobrepostos.
- Limite de 5.000 linhas por fonte é declarado quando alcançado e reduz a confiança. A v1 não é um sistema analítico de grande escala.
- Interpretação depende da disponibilidade do provedor/modelo de IA já configurado. Não foram alteradas credenciais ou quotas. Em falha, fatos e sinais continuam acessíveis.
- Publicação manual e validação de produção ainda pendentes. Auto Deploy não foi alterado.

Nenhuma ação comercial automática foi criada. Nenhum envio comercial, WhatsApp, cobrança ou movimentação de estoque foi realizado. Gmail, seu cron homologado, prospecção e jobs suspensos não foram alterados nesta conclusão.
