-- Schema Core do ERP Smith — SQLite
-- Gerado a partir de docs/schema_core_cliente_caso.md, com base na planilha
-- "Banco de Dados - Clube de Tiro.xlsx" (abas 02_Clientes, 90_Dicionario_Dados,
-- 91_Padrao_IDs, 94_Contrato_Casos, 95_Regras_Casos, 96_Relacionamentos_Casos).
--
-- Convenções do projeto:
--   * IDs: TEXT, formato PREFIXO-000000 (6 dígitos), gerados pelo sistema, imutáveis.
--   * Datas/horas: TEXT em ISO 8601 (ex.: 2026-07-17T22:15:29Z).
--   * "Sim"/"Não" em vez de booleano, para ficar igual à planilha original.

PRAGMA foreign_keys = ON;

CREATE TABLE cliente (
    cliente_id      TEXT PRIMARY KEY,              -- CLI-000001
    nome            TEXT NOT NULL,
    cpf             TEXT NOT NULL UNIQUE,           -- só dígitos, sem pontuação
    email           TEXT,
    telefone        TEXT,
    cidade          TEXT,
    status          TEXT NOT NULL,                  -- texto livre por enquanto (ex.: Ativo, Inativo)
    atendimento_ia  TEXT NOT NULL,                   -- texto livre por enquanto (Sim/Não)
    data_cadastro   TEXT NOT NULL,                   -- ISO 8601, imutável
    ultima_interacao TEXT,                           -- ISO 8601
    observacoes     TEXT
);

-- RCA-001: todo caso deve ter um cliente_id válido existente em cliente.
-- RCA-002: caso_id nunca é alterado depois de criado.
-- RCA-009: a IA nunca encerra, cancela ou muda prioridade diretamente — isso é
--          responsabilidade do Core, não é imposto pelo banco.
CREATE TABLE caso (
    caso_id                TEXT PRIMARY KEY,        -- CAS-000001
    cliente_id             TEXT NOT NULL REFERENCES cliente(cliente_id),
    titulo                 TEXT NOT NULL,
    descricao              TEXT,
    categoria              TEXT NOT NULL,            -- ver Listas_Casos em docs/schema_core_cliente_caso.md
    tipo_caso               TEXT NOT NULL,
    origem                  TEXT NOT NULL,
    canal_origem            TEXT NOT NULL,
    status                  TEXT NOT NULL,
    fase                    TEXT,
    prioridade              TEXT NOT NULL,
    responsavel_id          TEXT,                    -- sem FK ainda; tabela usuario pendente
    equipe_responsavel      TEXT,
    sessao_principal_id     TEXT,                    -- sem FK ainda; tabela sessao pendente
    memoria_id              TEXT,                    -- sem FK ainda; tabela memoria_ia pendente
    criado_em               TEXT NOT NULL,            -- ISO 8601, imutável
    atualizado_em           TEXT NOT NULL,            -- ISO 8601
    prazo_previsto          TEXT,
    encerrado_em            TEXT,
    criado_por              TEXT NOT NULL,
    alterado_por            TEXT NOT NULL,
    versao                  INTEGER NOT NULL DEFAULT 1,
    ativo                   TEXT NOT NULL DEFAULT 'Sim',
    motivo_encerramento     TEXT,
    observacoes             TEXT
);

CREATE INDEX idx_caso_cliente_id ON caso(cliente_id);
CREATE INDEX idx_caso_status ON caso(status);
