-- Credenciais de canal cifradas e estados OAuth genéricos.
-- Aditiva e idempotente. Não toca gmail_oauth_credentials nem
-- tiktok_oauth_credentials: as integrações existentes seguem como estão.
--
-- Por que existe: a aplicação não consegue escrever variáveis de ambiente no
-- Render. Sem um lugar durável, uma reautorização feita pelo painel se
-- perderia no próximo deploy. O token NUNCA entra aqui em texto puro --
-- `segredo_cifrado` guarda o envelope Fernet (AES-128-CBC + HMAC), e a
-- chave vive fora do banco (CANAIS_CRYPTO_KEY).
CREATE TABLE IF NOT EXISTS credenciais_canal (
    canal TEXT NOT NULL,
    nome TEXT NOT NULL,
    segredo_cifrado BYTEA NOT NULL,
    -- Metadado legível serve ao painel sem nunca decifrar o segredo:
    -- conta conectada, escopos e validade.
    metadados JSONB NOT NULL DEFAULT '{}'::jsonb,
    expira_em TIMESTAMPTZ,
    atualizado_por VARCHAR(220),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (canal, nome)
);

CREATE INDEX IF NOT EXISTS credenciais_canal_expira_idx
    ON credenciais_canal(expira_em) WHERE expira_em IS NOT NULL;

-- Estado OAuth genérico, mesmo desenho já usado para o Gmail
-- (gmail_oauth_estados_p0): nada do valor do state é guardado, só o hash.
-- Uso único + janela de 10 minutos = proteção CSRF e callback repetido
-- tratado de forma idempotente.
CREATE TABLE IF NOT EXISTS oauth_estados_canal (
    state_hash TEXT PRIMARY KEY,
    canal TEXT NOT NULL,
    navegador_hash TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    consumido_em TIMESTAMPTZ,
    resultado TEXT
);

CREATE INDEX IF NOT EXISTS oauth_estados_canal_limpeza_idx
    ON oauth_estados_canal(criado_em);
