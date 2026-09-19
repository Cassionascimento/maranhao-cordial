-- Central Empresarial -- Operações Vivas (ver docs/CENTRAL_EMPRESARIAL_
-- OPERACOES_VIVAS.md). Transforma um item do Calendário Empresarial em
-- uma operação viva, editável e versionada, sobre o mesmo contexto
-- P0-P5 + P5X. Aditiva: não altera nenhuma tabela existente, não toca
-- nas migrations 019-021. Reaproveita mi_artefatos/mi_artefatos_blobs
-- para arquivos/imagens (nenhum storage paralelo) e mi_fila_operacional
-- como origem opcional (item de calendário que deu origem à operação).

CREATE TABLE IF NOT EXISTS mi_operacoes (
    id UUID PRIMARY KEY,
    titulo TEXT NOT NULL,
    descricao TEXT,
    data_inicio DATE NOT NULL,
    data_fim DATE NOT NULL,
    local TEXT,
    estado TEXT NOT NULL DEFAULT 'planejamento' CHECK (estado IN (
        'planejamento','confirmada','em_andamento','concluida','cancelada'
    )),
    prioridade TEXT NOT NULL DEFAULT 'normal' CHECK (prioridade IN (
        'baixa','normal','alta','critica'
    )),
    responsavel TEXT,
    origem_fila_id BIGINT,
    criado_por TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (data_fim >= data_inicio)
);
CREATE INDEX IF NOT EXISTS mi_operacoes_periodo_idx ON mi_operacoes(data_inicio, data_fim);
CREATE INDEX IF NOT EXISTS mi_operacoes_estado_idx ON mi_operacoes(estado);

CREATE TABLE IF NOT EXISTS mi_operacao_pessoas (
    id UUID PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    funcao TEXT NOT NULL,
    nome TEXT,
    telefone TEXT,
    email TEXT,
    estado TEXT NOT NULL DEFAULT 'sugerido' CHECK (estado IN (
        'sugerido','convidado','confirmado','cancelado'
    )),
    origem TEXT NOT NULL DEFAULT 'humano' CHECK (origem IN ('humano','agente')),
    disponibilidade TEXT,
    observacoes TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_operacao_pessoas_operacao_idx ON mi_operacao_pessoas(operacao_id);

CREATE TABLE IF NOT EXISTS mi_operacao_itens (
    id UUID PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL DEFAULT 'tarefa' CHECK (tipo IN ('tarefa','marco','checklist')),
    titulo TEXT NOT NULL,
    descricao TEXT,
    data_prevista DATE,
    horario TEXT,
    responsavel TEXT,
    prioridade TEXT NOT NULL DEFAULT 'normal' CHECK (prioridade IN (
        'baixa','normal','alta','critica'
    )),
    status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN (
        'pendente','em_andamento','concluido','bloqueado','cancelado'
    )),
    depende_de_item_id UUID REFERENCES mi_operacao_itens(id) ON DELETE SET NULL,
    plano_b TEXT,
    observacoes TEXT,
    ordem INTEGER NOT NULL DEFAULT 0,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_operacao_itens_operacao_idx ON mi_operacao_itens(operacao_id);
CREATE INDEX IF NOT EXISTS mi_operacao_itens_status_idx ON mi_operacao_itens(status);

CREATE TABLE IF NOT EXISTS mi_operacao_brainstorm (
    id UUID PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    pergunta TEXT NOT NULL,
    autor_tipo TEXT NOT NULL CHECK (autor_tipo IN ('humano','agente','conselho')),
    autor_nome TEXT,
    resposta JSONB CHECK (resposta IS NULL OR jsonb_typeof(resposta) = 'object'),
    status TEXT NOT NULL DEFAULT 'aguardando' CHECK (status IN (
        'aguardando','respondido','aceito_como_proposta','descartado',
        'transformado_em_tarefa','transformado_em_artefato'
    )),
    item_id UUID REFERENCES mi_operacao_itens(id) ON DELETE SET NULL,
    artefato_id UUID REFERENCES mi_artefatos(id) ON DELETE SET NULL,
    versao INTEGER NOT NULL DEFAULT 1,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_operacao_brainstorm_operacao_idx ON mi_operacao_brainstorm(operacao_id);

CREATE TABLE IF NOT EXISTS mi_operacao_metricas (
    id UUID PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    nome TEXT NOT NULL,
    valor NUMERIC(18,4),
    unidade TEXT,
    periodo TEXT,
    formula TEXT,
    fonte TEXT,
    explicacao TEXT,
    estado_dado TEXT NOT NULL DEFAULT 'aguardando_dados' CHECK (estado_dado IN (
        'aguardando_dados','estimativa','confirmado','nao_aplicavel'
    )),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_operacao_metricas_operacao_idx ON mi_operacao_metricas(operacao_id);

CREATE TABLE IF NOT EXISTS mi_operacao_financeiro (
    id UUID PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    categoria TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN (
        'orcamento','realizado','comprometido','receita_atribuida','taxa','tributo'
    )),
    valor_centavos BIGINT NOT NULL,
    base_calculo TEXT,
    formula TEXT,
    premissas TEXT,
    fonte TEXT,
    periodo TEXT,
    estado_dado TEXT NOT NULL DEFAULT 'estimativa' CHECK (estado_dado IN (
        'estimativa','confirmado','aguardando_dados'
    )),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_operacao_financeiro_operacao_idx ON mi_operacao_financeiro(operacao_id);

CREATE TABLE IF NOT EXISTS mi_operacao_arquivos (
    id UUID PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    artefato_id UUID NOT NULL REFERENCES mi_artefatos(id) ON DELETE CASCADE,
    categoria TEXT NOT NULL DEFAULT 'documento' CHECK (categoria IN (
        'documento','visual','briefing','planilha','outro'
    )),
    adicionado_por TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (operacao_id, artefato_id)
);
CREATE INDEX IF NOT EXISTS mi_operacao_arquivos_operacao_idx ON mi_operacao_arquivos(operacao_id);

CREATE TABLE IF NOT EXISTS mi_operacao_auditoria (
    id BIGSERIAL PRIMARY KEY,
    operacao_id UUID NOT NULL REFERENCES mi_operacoes(id) ON DELETE CASCADE,
    entidade TEXT NOT NULL,
    entidade_id UUID,
    acao TEXT NOT NULL,
    campo TEXT,
    valor_anterior TEXT,
    valor_novo TEXT,
    ator_tipo TEXT NOT NULL DEFAULT 'humano' CHECK (ator_tipo IN ('humano','agente')),
    ator_nome TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_operacao_auditoria_operacao_idx ON mi_operacao_auditoria(operacao_id, criado_em DESC);

-- Esta migration é somente um arquivo versionado, mesma convenção de
-- 019_mi_artefatos.sql/020_mi_brand_context.sql/021_mi_regulatorio_
-- produto.sql: não foi executada contra nenhum banco (nem produção,
-- nem homologação) nesta etapa.
