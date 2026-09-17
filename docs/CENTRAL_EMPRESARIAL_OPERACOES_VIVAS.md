# Central Empresarial — Operações Vivas

## Objetivo
Transformar cada item do Calendário Empresarial em uma **operação viva**, editável e versionada, usando o mesmo contexto P0–P5 + P5X. Não iniciar P6.

Exemplo canônico: **Softdrinks Tech — 15 e 16 de outubro**.

## Estrutura de uma operação
Cada operação deve possuir:

1. **Identidade e calendário** — título, início/fim, local, estado, prioridade, responsável, dependências, marcos e agenda dos dois dias.
2. **Equipe / staff** — funções (direção, bartender, staff, apoio etc.), vagas, nomes confirmados, candidatos/sugestões da IA, disponibilidade e observações. Sugestões nunca viram confirmação sem ação humana.
3. **Plano operacional** — tarefas, checklist, horários, responsáveis, dependências, status, plano B e pós-evento.
4. **Brainstorm com Conselho** — conversa vinculada à operação, ideias humanas e dos agentes, propostas, contrapontos, decisão, pendências e opção de converter uma proposta em tarefa/marco após aprovação humana.
5. **Visual / roupas / materiais** — referências e anexos de fotos/imagens, conceitos de uniforme/roupa, balcão, display, garrafas, peças e simulações. Toda imagem gerada/sugerida fica como artefato versionado e editável; geração paga continua sujeita às travas existentes.
6. **Documentos e anexos** — fotos, imagens, PDFs, apresentações, planilhas, briefings e procedimentos, ligados aos artefatos P5X e à operação.
7. **Indicadores** — cards com nome, valor, unidade, período, origem, fórmula, explicação simples, confiança/estado do dado e data de atualização. Nunca inventar valor: sem fonte real => `AGUARDANDO DADOS`.
8. **Financeiro/fiscal** — orçamento, realizado, comprometido, receita atribuída, impostos, taxas e tributos. Cálculos devem exibir base, fórmula, premissas e fonte; classificação tributária não pode ser inferida silenciosamente.
9. **Memória e versões** — histórico de alterações, autor (humano/agente), data, antes/depois, possibilidade de revisar planejamento sem apagar versões anteriores.
10. **Visão Investidor** — somente leitura, consolidada e explicada, sem chave administrativa, dados pessoais, segredos, prompts internos ou controles de execução. A publicação/compartilhamento deve ser explicitamente aprovado e revogável.

## Indicadores por operação
O sistema pode apresentar quando fizer sentido e houver dados: receita atribuída, leads, leads qualificados, conversão, CAC, custo por lead, ticket médio, margem de contribuição, ROI/ROAS quando aplicável, churn apenas para base recorrente/coorte definida, orçamento vs. realizado, impostos/taxas, contatos/follow-ups, entregas no prazo e riscos.

`LTV`, `churn`, `CAC` e outros termos devem trazer tooltip/explicação e fórmula. Indicadores não aplicáveis a uma operação devem aparecer como **Não aplicável**, não como zero.

## UX
- Calendário: mês/semana/lista, clique no evento abre o workspace da operação.
- Operação: abas `Visão geral`, `Equipe`, `Plano`, `Brainstorm`, `Visual`, `Indicadores`, `Financeiro`, `Arquivos`, `Histórico`.
- Edição humana inline e sugestões da IA claramente identificadas.
- Botões de IA: `Pedir sugestões ao Conselho`, `Replanejar`, `Identificar riscos`, `Sugerir KPIs`, `Gerar briefing`, sempre produzindo proposta/artefato; não executar ação externa automaticamente.
- Nenhuma tela deve terminar em silêncio: carregando, sucesso, vazio, bloqueado ou erro compreensível.

## Modelo de dados proposto (aditivo)
- `mi_operacoes`: operação principal e ligação opcional ao item de calendário/origem.
- `mi_operacao_pessoas`: função, pessoa/placeholder, estado (sugerido/convidado/confirmado/cancelado), origem e observação.
- `mi_operacao_itens`: tarefas, marcos, atividades, checklist e dependências.
- `mi_operacao_brainstorm`: sessões/contribuições do Conselho e humano, com vínculo a artefatos/decisões.
- `mi_operacao_metricas`: definição e snapshots de KPI com fórmula, fonte e período.
- `mi_operacao_financeiro`: orçamento/realizado/comprometido/tributos/taxas com premissas e fonte.
- `mi_operacao_arquivos`: vínculo entre operação e `mi_artefatos`/blobs existentes; evitar armazenamento paralelo.
- `mi_operacao_auditoria`: trilha imutável de alterações relevantes.

Implementar via migration nova, aditiva e idempotente, depois de testes em PostgreSQL real. Não alterar migrations 019–021.

## Softdrinks Tech — semente planejada
Criar a operação apenas quando a migration/CRUD estiverem homologados. Datas: **15/10/2026 a 16/10/2026**. Staff, bartender, roupas, atividades, custos e KPIs começam vazios/`AGUARDANDO DADOS`, exceto fatos já presentes em fonte operacional confiável. Não transformar memória de conversa em dado canônico sem revisão/fonte adequada.

## Governança
Human-in-the-loop permanece obrigatório para convite/contato externo, publicação, gasto, contratação, alteração fiscal/regulatória ou qualquer ação consequencial. O Conselho pode sugerir e editar rascunhos; o sistema deve preservar autoria, versão e justificativa.
