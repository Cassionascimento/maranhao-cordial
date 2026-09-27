# Catálogo de produtos

A Maranhão passa a ser uma marca que reúne produtos com identidade regional. O Maranhão Cordial (a bebida) é o primeiro item do catálogo e continua com seu próprio checkout e suas próprias regras comerciais (`compreaqui.html`, `c6_pix.py`) — **nada aqui cria um checkout novo**.

## Rotas

| Rota | Quem | O quê |
|---|---|---|
| `GET /api/catalogo/produtos` | público | produtos `publicado`/`em_breve`, ordenados por destaque e ordem de exibição |
| `GET /api/catalogo/produtos/<slug>` | público | um produto (404 genérico se não existir ou estiver em rascunho) |
| `GET /api/catalogo/midia/<blob_id>` | público | bytes da mídia enviada por upload (imagens semeadas por `url_externa` não passam por aqui) |
| `GET /produto/<slug>` | público | mesma página (`produto.html`) para qualquer slug |
| `GET/POST /api/admin/catalogo/produtos`, `PATCH …/<id>`, `POST/DELETE …/<id>/midias[/<midia_id>]`, `GET /api/admin/catalogo/categorias` | admin (`X-Admin-Key`) | cadastro, edição, publicação e mídia |

## Regras que não mudam

- **Slug imutável.** Definido só na criação; o PATCH nunca aceita `id`, `slug` nem `criado_em` (`campo_nao_editavel`).
- **`comprar_site` exige `url_compra`.** Só existe quando já há uma compra funcional — nunca um checkout novo. O produto Maranhão Cordial aponta para `/compreaqui.html#checkoutCard`.
- **`orcamento`** reaproveita a solicitação de orçamento já existente (`/cadastro-profissional?origem=orcamento_<slug>`), sem formulário novo.
- **`em_breve`** nunca oferece pagamento — nem no cartão da vitrine, nem na página do produto.
- **Rascunho é invisível ao público**: nunca aparece em `/api/catalogo/produtos`, nunca é encontrado por slug, e a mídia dele não é servida (mesmo sabendo o id do blob).
- **Campos da bebida (volume, peso, composição, cuidados) são opcionais** para qualquer categoria — nada é obrigatório fora do que o produto realmente usa.
- **Upload reaproveita `mi_artefatos_blobs`** (migration 019, BYTEA em Postgres — mesmo mecanismo já usado por Materiais do Conselho). Lista branca de formato (`image/png`, `image/jpeg`, `image/webp`, `video/mp4`); limite de 8 MB para imagem e 40 MB para vídeo. Uma mídia tem `blob_id` **ou** `url_externa`, nunca os dois nem nenhum — é assim que o produto semeado usa a fotografia real já publicada em `img/hero/tres-cordiais.webp` sem duplicar bytes.

## Onde aparece

- **Página inicial**: seção "Produtos da Maranhão" (`catalogo-vitrine.js`), com o layout completo mesmo com um produto só.
- **"Compre aqui"**: entrada do catálogo, com o Maranhão Cordial em destaque (seção própria, regras de caixa/lote preservadas).
- **Painel administrativo**: Comercial → Catálogo (`catalogo-admin.js`), cadastro/edição/mídia/publicação sem mexer em código.

## Decisões de escopo

- Ficha técnica limitada a volume, peso, composição e cuidados (os quatro campos citados no pedido), não um editor de chave/valor livre.
- Categoria é texto livre por produto; `/api/admin/catalogo/categorias` só sugere as já usadas (datalist no formulário), sem lista fixa no código.
- A página `/produto/<slug>` é usada por qualquer produto **exceto** o Maranhão Cordial, que continua na sua página dedicada (`compreaqui.html`) por já ter uma experiência de compra mais rica que a página genérica não reproduz.
