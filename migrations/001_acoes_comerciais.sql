BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
CREATE TABLE IF NOT EXISTS acoes_comerciais_propostas (
 id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
 chave TEXT NOT NULL UNIQUE,
 -- Referência tipada: nenhum ID de uma tabela é submetido à FK de outra.
 -- A aplicação valida a existência na origem e conserva a referência no digest.
 origem_tipo TEXT NOT NULL CHECK(origem_tipo ~ '^[a-z][a-z0-9_]{0,63}$'),
 origem_id TEXT NOT NULL CHECK(length(trim(origem_id)) BETWEEN 1 AND 200),
 dados JSONB NOT NULL,
 digest TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'aguardando_aprovacao'
 CHECK(status IN ('aguardando_aprovacao','aprovada','rejeitada','executando','enviada','incerta','bloqueada')),
 criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 decidido_em TIMESTAMPTZ, decidido_por TEXT, digest_aprovado TEXT,
 executor TEXT, resultado JSONB, atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Este rascunho nunca foi aplicado em produção. Não adivinha como converter
-- instalações divergentes: aborta integralmente, sem apagar dados ou aprovações.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public'
   AND table_name='acoes_comerciais_propostas' AND column_name='prospecto_id') THEN
   RAISE EXCEPTION 'Schema preliminar detectado: requer migração de origem explícita';
 END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_acoes_comerciais_origem
 ON acoes_comerciais_propostas(origem_tipo,origem_id);
CREATE TABLE IF NOT EXISTS auditoria_acoes_comerciais (
 id BIGSERIAL PRIMARY KEY, acao_id UUID NOT NULL REFERENCES acoes_comerciais_propostas(id),
 evento TEXT NOT NULL, ator TEXT NOT NULL, criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS gmail_processamentos_seguros (
 interacao_id UUID PRIMARY KEY REFERENCES interacoes_omnichannel(id),
 estado TEXT NOT NULL CHECK(estado IN ('pendente','concluido','falhou')),
 tentativas INTEGER NOT NULL DEFAULT 0, erro_tipo TEXT, atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Registra somente a pendência; não interpreta nem envia no deploy.
INSERT INTO gmail_processamentos_seguros(interacao_id,estado)
 SELECT id,'pendente' FROM interacoes_omnichannel
 WHERE canal='gmail' AND tipo_interacao='email' AND NOT COALESCE(processado_ia,FALSE)
 ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS pesquisas_abandonadas_auditoria (
 pesquisa_id UUID PRIMARY KEY REFERENCES pesquisas_fase57(id),
 estado_anterior TEXT NOT NULL, iniciado_em TIMESTAMPTZ, registrado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO pesquisas_abandonadas_auditoria(pesquisa_id,estado_anterior,iniciado_em)
 SELECT id,status,iniciado_em FROM pesquisas_fase57
 WHERE status='executando' AND iniciado_em < NOW()-INTERVAL '24 hours'
 ON CONFLICT DO NOTHING;
UPDATE pesquisas_fase57 SET status='erro',concluido_em=NOW(),erro='execucao_abandonada_requer_nova_pesquisa'
 WHERE status='executando' AND iniciado_em < NOW()-INTERVAL '24 hours'
 AND EXISTS (SELECT 1 FROM pesquisas_abandonadas_auditoria a WHERE a.pesquisa_id=pesquisas_fase57.id AND a.iniciado_em=pesquisas_fase57.iniciado_em);
COMMIT;
