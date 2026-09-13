-- Campos de agendamento para o Calendário Inteligente (ETAPA 5.1).
-- Aditiva: não altera 014 nem nenhuma coluna existente de mi_fila_operacional.
-- "motivo" pedido pela 5.1 é o mesmo conceito da coluna já existente
-- `inferencia` (014) -- não duplicamos a coluna, só a expomos com esse nome
-- na leitura do calendário (mi_calendario.py).
ALTER TABLE mi_fila_operacional ADD COLUMN IF NOT EXISTS executar_em TIMESTAMPTZ;
ALTER TABLE mi_fila_operacional ADD COLUMN IF NOT EXISTS lead_id UUID REFERENCES leads_crm(id);
ALTER TABLE mi_fila_operacional ADD COLUMN IF NOT EXISTS estabelecimento_id UUID REFERENCES mi_estabelecimentos(id);
CREATE INDEX IF NOT EXISTS mi_fila_executar_em_idx ON mi_fila_operacional(executar_em);
CREATE INDEX IF NOT EXISTS mi_fila_lead_idx ON mi_fila_operacional(lead_id);
CREATE INDEX IF NOT EXISTS mi_fila_estabelecimento_idx ON mi_fila_operacional(estabelecimento_id);

-- Esta migration é somente um arquivo versionado: não foi executada contra
-- nenhum banco nesta etapa, assim como 013 e 014 continuam pendentes.
