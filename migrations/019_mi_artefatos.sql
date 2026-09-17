-- Contrato canônico de artefatos executivos/criativos (P5.X, Milestone 1).
-- Modelado no padrão de versionamento já comprovado em produção em
-- documentos_empresariais (status + ponteiro para a versão anterior) --
-- ver P5X_AUDIT.md item 5. Nunca sobrescreve uma versão: uma nova versão
-- sempre encadeia via parent_artifact_id. Aditiva: não altera nenhuma
-- tabela P0-P5 existente.
CREATE TABLE IF NOT EXISTS mi_artefatos (
    id UUID PRIMARY KEY,
    artifact_type TEXT NOT NULL CHECK (artifact_type IN (
        'PRESENTATION','CHART','IMAGE','LABEL_CONCEPT','SOCIAL_CREATIVE',
        'PACKAGING_CONCEPT','INFOGRAPHIC','REPORT'
    )),
    source_type TEXT,
    source_id TEXT,
    meeting_id TEXT,
    agent_id TEXT,
    decision_id TEXT,
    parent_artifact_id UUID REFERENCES mi_artefatos(id),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    status TEXT NOT NULL DEFAULT 'gerado' CHECK (status IN ('gerado','aprovado','rejeitado','historico')),
    storage_uri TEXT NOT NULL,
    thumbnail_uri TEXT,
    mime_type TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    CHECK ((status = 'aprovado') = (approved_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS mi_artefatos_meeting_idx ON mi_artefatos(meeting_id);
CREATE INDEX IF NOT EXISTS mi_artefatos_agent_idx ON mi_artefatos(agent_id);
CREATE INDEX IF NOT EXISTS mi_artefatos_type_idx ON mi_artefatos(artifact_type);
CREATE INDEX IF NOT EXISTS mi_artefatos_parent_idx ON mi_artefatos(parent_artifact_id);
CREATE INDEX IF NOT EXISTS mi_artefatos_status_idx ON mi_artefatos(status);

CREATE TABLE IF NOT EXISTS mi_artefatos_auditoria (
    id BIGSERIAL PRIMARY KEY,
    artefato_id UUID NOT NULL REFERENCES mi_artefatos(id),
    estado_anterior TEXT,
    estado_novo TEXT NOT NULL,
    ator TEXT NOT NULL,
    motivo TEXT,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Storage padrão (provider Postgres-BYTEA -- ver P5X_AUDIT.md item 6/15:
-- é o único mecanismo de persistência de arquivo já comprovado em
-- produção neste projeto, mesmo padrão de documentos_empresariais.
-- conteudo). Fica em tabela separada da metadata acima para nunca puxar
-- bytes grandes ao listar/consultar artefatos (mesma disciplina de N+1
-- do contrato P5 em mi_intelligence_api.py).
CREATE TABLE IF NOT EXISTS mi_artefatos_blobs (
    id UUID PRIMARY KEY,
    conteudo BYTEA NOT NULL,
    mime_type TEXT NOT NULL,
    tamanho_bytes BIGINT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Esta migration é somente um arquivo versionado, na mesma convenção de
-- 014_mi_fila_operacional.sql: não foi executada contra nenhum banco
-- (nem produção, nem homologação) nesta etapa.
