-- Conselho de Agentes (INTEGRAÇÃO): a menor estrutura necessária para
-- representar mensagem/reunião/ata/relatório entre os 8 agentes
-- especialistas, sem duplicar mi_sinais (fatos), mi_fila_operacional
-- (fila/aprovações) ou mi_calendario (agenda) -- todos continuam sendo a
-- fonte de verdade para o que já resolviam antes desta etapa.
--
-- O que NÃO ganhou tabela nova, de propósito:
-- - "recomendação" do Conselho -> vira um item de mi_fila_operacional
--   (origem='conselho'), reaproveitando o motor de decisão/aprovação já
--   existente (mi_decisao.registrar_item_fila / avancar_estado_fila).
-- - "relatório curto"/"atividade do agente" -> vira um fato em mi_sinais
--   (origem='conselho'), reaproveitando o mesmo barramento da ETAPA 4.9.
-- O que precisou de tabela nova: mensagens entre agentes (thread livre,
-- não é um "sinal" nem uma "decisão") e registros estruturados (reunião/
-- conclave/relatório longo, com seções fixas que não cabem no payload
-- solto de mi_sinais sem forçar a modelagem).
--
-- Aditiva: não altera nenhuma tabela/migration anterior. Esta migration é
-- somente um arquivo versionado -- não foi executada contra nenhum banco.

CREATE TABLE IF NOT EXISTS mi_conselho_mensagens (
    id UUID PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    de_agente TEXT NOT NULL CHECK (de_agente ~ '^[a-z][a-z0-9_]{0,63}$'),
    para_agente TEXT CHECK (para_agente IS NULL OR para_agente ~ '^[a-z][a-z0-9_]{0,63}$'),
    demanda_referencia TEXT,
    texto TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_conselho_mensagens_agentes_idx ON mi_conselho_mensagens(de_agente, para_agente);
CREATE INDEX IF NOT EXISTS mi_conselho_mensagens_criado_idx ON mi_conselho_mensagens(criado_em);

-- Mensagens são append-only por desenho da aplicação (mi_conselho.py nunca
-- expõe UPDATE/DELETE para esta tabela); não há trigger de banco impedindo
-- porque o projeto não usa triggers em nenhuma outra migration -- a
-- garantia é de código, como em todo o restante do Maranhão Intelligence.

CREATE TABLE IF NOT EXISTS mi_conselho_registros (
    id UUID PRIMARY KEY,
    chave TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL CHECK (tipo IN ('reuniao', 'conclave', 'relatorio')),
    demanda TEXT,
    participantes JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(participantes) = 'array'),
    contexto TEXT,
    dados_apresentados JSONB,
    posicoes JSONB,
    conflitos JSONB,
    conclusao TEXT,
    recomendacoes JSONB,
    vetos JSONB,
    pendencias JSONB,
    precisa_diretor BOOLEAN NOT NULL DEFAULT FALSE,
    status TEXT NOT NULL DEFAULT 'registrado',
    versao INTEGER NOT NULL DEFAULT 1,
    registro_anterior_id UUID REFERENCES mi_conselho_registros(id),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS mi_conselho_registros_tipo_idx ON mi_conselho_registros(tipo);
CREATE INDEX IF NOT EXISTS mi_conselho_registros_criado_idx ON mi_conselho_registros(criado_em);
CREATE INDEX IF NOT EXISTS mi_conselho_registros_precisa_diretor_idx ON mi_conselho_registros(precisa_diretor) WHERE precisa_diretor;

-- Correções nunca sobrescrevem um registro existente: uma nova versão é
-- SEMPRE uma linha nova apontando para registro_anterior_id (aplicação,
-- mi_conselho.nova_versao_registro -- nunca um UPDATE de conteúdo).
