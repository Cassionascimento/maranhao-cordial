-- Banco de fatos confirmados do Conselho de Agentes -- a peça que faltava
-- para Iris "manter fatos confirmados reutilizáveis" e para dar validade
-- temporal a preço/estoque/prazo/disponibilidade/integração (sem isso, um
-- dado antigo era lido como se fosse atual para sempre).
--
-- Não duplica mi_sinais (fatos/eventos de negócio já observados) nem
-- mi_conselho_registros (atas/relatórios): este é especificamente um
-- pequeno registro de VALORES confirmados e sua proveniência, consultável
-- por tópico (ex.: "preco_extrato_gengibre", "moq_fornecedor_x"), com
-- expiração explícita -- histórico nunca é apagado (append-only, mesma
-- disciplina do resto do projeto); "o valor atual" é sempre a leitura mais
-- recente, calculada em código (mi_conselho_fatos.py), nunca um UPDATE
-- aqui.
--
-- Aditiva: não altera nenhuma tabela/migration anterior. Arquivo
-- versionado -- não executado automaticamente contra nenhum banco.

CREATE TABLE IF NOT EXISTS mi_conselho_fatos (
    id UUID PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    topico TEXT NOT NULL CHECK (topico ~ '^[a-z][a-z0-9_]{0,127}$'),
    valor TEXT NOT NULL,
    unidade TEXT,
    origem_tipo TEXT NOT NULL CHECK (origem_tipo IN (
        'FONTE_INTERNA', 'FORNECEDOR', 'POLITICA', 'CALCULO', 'ESTIMATIVA'
    )),
    fonte_detalhe TEXT,
    confianca TEXT CHECK (confianca IS NULL OR confianca IN ('alta', 'media', 'baixa')),
    agente_registrante TEXT CHECK (agente_registrante IS NULL OR agente_registrante ~ '^[a-z][a-z0-9_]{0,63}$'),
    registro_id UUID REFERENCES mi_conselho_registros(id),
    obtido_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valido_ate TIMESTAMPTZ,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- "Estado atual" de um tópico = a linha de maior obtido_em -- este índice
-- é o que torna essa consulta barata sem precisar de view/coluna derivada.
CREATE INDEX IF NOT EXISTS mi_conselho_fatos_topico_obtido_idx
    ON mi_conselho_fatos(topico, obtido_em DESC);
CREATE INDEX IF NOT EXISTS mi_conselho_fatos_registro_idx ON mi_conselho_fatos(registro_id);

-- Append-only por desenho da aplicação (mi_conselho_fatos.py nunca expõe
-- UPDATE/DELETE); mesma garantia de código, sem trigger, já usada em
-- mi_conselho_mensagens/mi_conselho_registros.
