# P5X — fechamento técnico local

## Fonte de verdade e continuidade

Branch feature/p5x-executive-creative-layer. Base recebida 44458f7;
main/remoto e62c172; PR #19 confirmado aberto em Draft. Não houve push,
merge, deploy ou alteração de configuração externa.

Preservados os três arquivos modificados recebidos e os oito não rastreados.
Label/Social/Regulatório e migration 021 foram concluídos; os quatro
arquivos estratégicos em docs continuam fora dos commits por não fazerem
parte de P5X. Nenhuma migration foi executada.

## O que existe

| Etapa | Entrega |
|---|---|
| M1 | Contrato, versões, estados humanos, auditoria e BYTEA de artefatos |
| M2 | Parecer compacto e requested_visual no Conselho existente |
| M3 | Secretário transforma registro persistido em ata |
| M4 | PPTX real, curto, com gráficos nativos editáveis |
| M5 | Gráficos programáticos SVG/PPTX com lacunas explícitas |
| M6 | Pirret, brief e provider injetável de imagem |
| M7 | Brand Context versionado e referências aprovadas; teste de composição real |
| M8 | Label e Social Studio; feed/story/key visual/vertical/banner/produto/mockup; origem e versões preservadas |
| M9 | Uma seção Executivo & Criativo dentro do Command Center atual |
| M10 | E2E, autenticação, auditoria visível, SVG escapado, download restrito, limites e proveniência sintética explícita |

## Classificação honesta

- **LIVE E FUNCIONAL:** esta rodada não consultou nem alterou LIVE. Nenhum recurso novo é declarado publicado. O estado operacional de produção não foi revalidado.
- **IMPLEMENTADO MAS NÃO CONFIGURADO/HOMOLOGADO:** pipeline e UI locais; operação requer migrations 019–021 e credenciais/provider no ambiente de destino. O estado desses recursos em produção é desconhecido nesta rodada.
- **MOCK/TEST ONLY:** persistência SQL em memória, resposta do LLM e imagem de 1 pixel do MockImageProvider. Rede bloqueada no teste E2E. Isso não demonstra qualidade visual premium do provider real nem transações PostgreSQL reais.
- **AGUARDANDO DADOS:** gráfico comercial da MI sem dados reais consultados. A UI busca segmentos do overview; sem contagens válidas, não grava gráfico. Não foram criados contatos, pedidos, vendas, métricas comerciais ou reuniões reais.
- **PENDENTE:** homologação controlada com PostgreSQL e provider reais; aprovação visual dos materiais reais e demonstração de gráfico comercial com dados reais. São pendências de homologação, não resultados presumidos a partir de mocks.

## Segurança

Todos os registradores P5X foram montados em Flask e suas rotas testadas
sem autorização: 401 antes de banco/provider. Aprovar/rejeitar exige ator,
as transições usam lock e auditoria existentes. Aprovação de artefato não
publica. Referências visuais não aprovadas não são usadas como positivas.
Revisão regulatória exige tipo, SKU correspondente e aprovação criativa;
registra revisão humana sem autorização automática de produção. Nova
versão de rótulo volta a NAO_VALIDADO.

Metadata é função interna, não PATCH público arbitrário: atualizações
são auditadas, com antes/depois. Geração de conceitos limitada a 1–3;
formatos sociais validados/deduplicados. Falta de imagem é erro explícito.
SVG escapa títulos/rótulos/fonte; valores não finitos, negativos e séries
não suportadas são rejeitados em vez de produzir visual enganoso.
Download usa attachment, nosniff, CSP sandbox e no-store. HTML/SVG não é
inserido no DOM como preview; previews são restritos a PNG/JPEG/WebP.
A identificação de ator herda a autenticação administrativa compartilhada
existente; não é identidade individual criptograficamente comprovada.

Não há envio, publicação, pagamento, campanha automática ou alteração de
travas dos canais. Credenciais, quotas e jobs não foram alterados.

## Provas e limites de teste

Suíte: 1336 testes Python e 223 JavaScript aprovados. Auditoria estrutural
existente: quatro testes aprovados. Novos E2E/governança: cinco testes.
Sintaxe Python/JS e git diff --check aprovados. Sem testes Python fora de
tests/ encontrados. Removidos imports sem uso Emu/re nos módulos afetados.

E2E chama registrar_registro real e reentrega a mesma chave; busca esse
registro, monta ata, gera e persiste PPTX/gráfico/conceito, lista pelo HTTP,
baixa PPTX, valida ZIP/XML e reabre pela biblioteca PowerPoint, aprova,
rejeita, refina e consulta linhagem/auditoria. O PPTX tem no máximo sete
slides com dois gráficos/estados incluídos. Nenhuma chamada de rede é
permitida nesse teste. Não foi aberto no aplicativo Microsoft PowerPoint.

Navegador: página local isolada, CSP sem conexão externa, fetch simulado,
banner SYNTHETIC_TEST. Conferidos controles/estados e NOT_ENOUGH_DATA.
Isso valida a composição da seção, não uma sessão real do Admin autenticado.

Reprodução da demonstração: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:. python3 tests/demo_p5x_local.py`.
Saída em /tmp/p5x-demo-local. O PPTX é real; reunião é demonstrativa.
O gráfico usa contagem real do Git e identifica que é dado técnico, não
métrica comercial. Não substitui a demonstração comercial ainda pendente.

## Migrations

019 mi_artefatos, mi_artefatos_auditoria, mi_artefatos_blobs;
020 mi_brand_context; 021 mi_regulatorio_produto.
Numeração única, CREATE TABLE/INDEX IF NOT EXISTS, sem DELETE/DROP/TRUNCATE.
Não executadas. IF NOT EXISTS não comprova compatibilidade de uma tabela
preexistente divergente; isso deve ser verificado no ambiente de homologação.

## Git e recomendação

568c0cb: fecha auditoria/cobertura M7 e corrige assertions CSS legadas.
4f630e9: M8 studios e bloqueios.
2895848: M9 Command Center.
f4f0bc2: teste M9 distingue leitura automática de escrita humana.
O commit M10 acompanha este relatório.

PR #19 permanece Draft. A revisão de código pode começar, mas recomendo
manter Draft até a homologação de PostgreSQL/provider/dados comerciais e
a aprovação visual real. Sem merge ou deploy nesta rodada.

## Inventário das rotas P5X

| Métodos | Rota |
|---|---|
| GET | `/api/admin/mi/artefatos` |
| GET | `/api/admin/mi/artefatos/<artefato_id>` |
| POST | `/api/admin/mi/artefatos/<artefato_id>/aprovar` |
| GET | `/api/admin/mi/artefatos/<artefato_id>/auditoria` |
| GET | `/api/admin/mi/artefatos/<artefato_id>/download` |
| GET | `/api/admin/mi/artefatos/<artefato_id>/linhagem` |
| POST | `/api/admin/mi/artefatos/<artefato_id>/rejeitar` |
| GET | `/api/admin/mi/brand-context` |
| POST | `/api/admin/mi/brand-context` |
| POST | `/api/admin/mi/conselho/<registro_id>/apresentacao` |
| GET | `/api/admin/mi/conselho/<registro_id>/ata` |
| POST | `/api/admin/mi/graficos` |
| POST | `/api/admin/mi/label-studio/<artefato_id>/validar-regulatorio` |
| POST | `/api/admin/mi/label-studio/conceitos` |
| POST | `/api/admin/mi/pirret/conceitos` |
| GET | `/api/admin/mi/pirret/provider-status` |
| POST | `/api/admin/mi/pirret/refinar/<artefato_id>` |
| GET | `/api/admin/mi/regulatorio/<sku>` |
| POST | `/api/admin/mi/regulatorio/<sku>` |
| POST | `/api/admin/mi/social-studio/campanha/<artefato_base_id>` |
| GET | `/api/admin/mi/visual-memory` |
