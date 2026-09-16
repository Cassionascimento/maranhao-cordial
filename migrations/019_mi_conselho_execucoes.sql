-- Observabilidade do Conselho de Agentes -- "Saúde dos Agentes": um registro
-- por chamada real a um especialista (sucesso ou falha), para o painel poder
-- mostrar status/última execução/duração/erro categorizado/modelo/tokens
-- sem depender de log de aplicação.
--
-- NUNCA guarda prompt, resposta bruta, segredo ou stack trace -- só
-- categoria de erro (nome da exceção) e um detalhe truncado e seguro
-- (ver mi_conselho_saude.py / mi_conselho_executor._categorizar_erro).
--
-- Aditiva: não altera nenhuma tabela/migration anterior. Arquivo
-- versionado -- não executado automaticamente contra nenhum banco.
--
-- Reversível: DROP TABLE IF EXISTS mi_conselho_execucoes; (nenhuma outra
-- tabela referencia esta -- é puramente telemetria de leitura, sem FK
-- apontando para ela).

CREATE TABLE IF NOT EXISTS mi_conselho_execucoes (
    id UUID PRIMARY KEY,
    agente TEXT NOT NULL,
    origem TEXT NOT NULL CHECK (origem IN ('automatico', 'interativo')),
    status TEXT NOT NULL CHECK (status IN ('sucesso', 'falha')),
    erro_categoria TEXT,
    erro_detalhe TEXT,
    duracao_ms INTEGER CHECK (duracao_ms IS NULL OR duracao_ms >= 0),
    modelo TEXT,
    tentativas SMALLINT,
    tokens_entrada INTEGER,
    tokens_saida INTEGER,
    tokens_raciocinio INTEGER,
    executado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Leitura do painel é sempre "últimas N horas de UM agente" -- este índice
-- é o que torna essa consulta barata sem view/coluna derivada.
CREATE INDEX IF NOT EXISTS mi_conselho_execucoes_agente_executado_idx
    ON mi_conselho_execucoes(agente, executado_em DESC);
CREATE INDEX IF NOT EXISTS mi_conselho_execucoes_executado_idx
    ON mi_conselho_execucoes(executado_em DESC);

-- Append-only por desenho da aplicação (mi_conselho_saude.py nunca expõe
-- UPDATE/DELETE); mesma garantia de código, sem trigger, já usada em
-- mi_conselho_mensagens/mi_conselho_registros/mi_conselho_fatos.
