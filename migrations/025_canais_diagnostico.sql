-- Histórico de diagnóstico dos canais externos.
-- Aditiva e idempotente. Não cria job, não dispara transporte.
--
-- Guarda só o que o painel precisa para mostrar "último erro" e "histórico
-- de falhas" sem reconsultar a plataforma: estado, códigos e carimbos.
-- NUNCA token, client secret, corpo de resposta ou URL com credencial --
-- por isso não existe coluna de payload livre aqui.
CREATE TABLE IF NOT EXISTS canais_diagnostico_historico (
    id BIGSERIAL PRIMARY KEY,
    canal TEXT NOT NULL,
    estado TEXT NOT NULL,
    leitura_disponivel BOOLEAN,
    escrita_disponivel BOOLEAN,
    webhook_ativo BOOLEAN,
    conta TEXT,
    tipo_conta TEXT,
    permissoes_ausentes TEXT[],
    token_expira_em TIMESTAMPTZ,
    ultimo_erro TEXT,
    codigo_erro TEXT,
    exige_acao_admin BOOLEAN NOT NULL DEFAULT FALSE,
    aguardando_plataforma BOOLEAN NOT NULL DEFAULT FALSE,
    verificacao_remota BOOLEAN NOT NULL DEFAULT FALSE,
    verificado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS canais_diagnostico_historico_canal_idx
    ON canais_diagnostico_historico(canal, verificado_em DESC);

-- Só o que mudou interessa como histórico: a mesma leitura repetida a cada
-- abertura do painel não vira linha nova (ver registrar_diagnostico em
-- canais_status.py, que compara com a última antes de gravar).
CREATE INDEX IF NOT EXISTS canais_diagnostico_historico_falhas_idx
    ON canais_diagnostico_historico(canal, verificado_em DESC)
    WHERE codigo_erro IS NOT NULL;
