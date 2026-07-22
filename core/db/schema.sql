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
    sessao_principal_id     TEXT REFERENCES sessao(sessao_id),
    memoria_id              TEXT REFERENCES memoria_ia(memoria_id),
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

-- Fonte: docs/schema_processo_servico.md (01_Servicos, 04_Processos).
-- Campos de texto-padrão/resposta pronta (mensagem_padrao, prazo_texto,
-- valor_texto, resposta_*) ficaram FORA de propósito — são template
-- genérico repetido, não dado do serviço. Ficam para uma futura tabela
-- de Templates.
CREATE TABLE servico (
    service_id              TEXT PRIMARY KEY,         -- SER-000001
    service_key             TEXT NOT NULL UNIQUE,      -- ex.: renovacao_cr
    nome_servico             TEXT NOT NULL,
    descricao                TEXT,
    categoria                TEXT NOT NULL,             -- mesma lista de caso.categoria
    prazo_estimado_dias      INTEGER,
    valor_referencia         REAL,                       -- número puro, ex. 850.00
    documentos_obrigatorios  TEXT NOT NULL,
    ativo                    TEXT NOT NULL DEFAULT 'Sim',
    observacoes              TEXT
);

-- RCA/matriz: a IA nunca altera processo.status; só informa proxima_acao cadastrada.
-- processo.caso_id é campo novo (não existia na planilha) — exigido por
-- 96_Relacionamentos_Casos: "todo processo operacional deve pertencer a um caso".
CREATE TABLE processo (
    processo_id       TEXT PRIMARY KEY,                 -- PRO-000001
    caso_id           TEXT NOT NULL REFERENCES caso(caso_id),
    cliente_id        TEXT NOT NULL REFERENCES cliente(cliente_id),
    servico_id        TEXT NOT NULL REFERENCES servico(service_id),
    protocolo         TEXT,
    status            TEXT NOT NULL,
    data_abertura     TEXT NOT NULL,                     -- ISO 8601
    prazo_estimado    TEXT,                               -- ISO 8601
    proxima_acao      TEXT,
    responsavel       TEXT,                               -- texto livre por enquanto
    ultima_atualizacao TEXT NOT NULL,                     -- ISO 8601
    observacoes       TEXT
);

CREATE INDEX idx_processo_caso_id ON processo(caso_id);
CREATE INDEX idx_processo_cliente_id ON processo(cliente_id);
CREATE INDEX idx_processo_servico_id ON processo(servico_id);
CREATE INDEX idx_processo_status ON processo(status);

-- Fonte: docs/schema_documento_sessao.md (05_Documentos, 96_Relacionamentos_Casos).
-- documento.caso_id é campo novo (não existia na planilha).
-- CHECK abaixo garante que todo documento tem contexto: pertence a um
-- caso e/ou a um processo, nunca solto sem nenhum dos dois.
CREATE TABLE documento (
    documento_id      TEXT PRIMARY KEY,                 -- DOC-000001
    cliente_id        TEXT NOT NULL REFERENCES cliente(cliente_id),
    caso_id           TEXT REFERENCES caso(caso_id),
    processo_id       TEXT REFERENCES processo(processo_id),
    tipo_documento    TEXT NOT NULL,
    nome_arquivo      TEXT,
    link_arquivo      TEXT,
    status            TEXT NOT NULL,
    data_envio        TEXT,                              -- ISO 8601
    data_validade     TEXT,                              -- ISO 8601
    revisado_por      TEXT,                               -- texto livre por enquanto
    observacoes       TEXT,
    CHECK (caso_id IS NOT NULL OR processo_id IS NOT NULL)
);

CREATE INDEX idx_documento_cliente_id ON documento(cliente_id);
CREATE INDEX idx_documento_caso_id ON documento(caso_id);
CREATE INDEX idx_documento_processo_id ON documento(processo_id);

-- Fonte: docs/schema_documento_sessao.md (08_Sessoes, 40_Listas_Auxiliares).
-- sessao.caso_id é campo novo e opcional: "uma sessão pode iniciar sem
-- caso e ser vinculada após classificação" (96_Relacionamentos_Casos).
-- sessao_id não constava em 91_Padrao_IDs, mas os dados de exemplo já
-- seguem o padrão de 6 dígitos (SES-000001) — vale completar a planilha depois.
CREATE TABLE sessao (
    sessao_id                TEXT PRIMARY KEY,           -- SES-000001
    cliente_id                TEXT NOT NULL REFERENCES cliente(cliente_id),
    caso_id                    TEXT REFERENCES caso(caso_id),
    canal                      TEXT NOT NULL,
    identificador_canal        TEXT,
    assunto_atual              TEXT,
    ultima_intencao            TEXT,
    ultimo_servico_id          TEXT REFERENCES servico(service_id),
    ultimo_processo_id         TEXT REFERENCES processo(processo_id),
    ultima_mensagem_cliente    TEXT,
    ultima_resposta_ia         TEXT,
    resumo_sessao              TEXT,
    status_sessao              TEXT NOT NULL,
    iniciada_em                TEXT NOT NULL,             -- ISO 8601
    ultima_interacao_em        TEXT NOT NULL,              -- ISO 8601
    expira_em                  TEXT,                        -- ISO 8601
    encaminhada_humano         TEXT,                        -- Sim/Não, texto livre
    responsavel                TEXT,                        -- texto livre por enquanto
    conversa_id_origem         TEXT,                        -- sem FK ainda; tabela conversa pendente
    ativo                      TEXT NOT NULL DEFAULT 'Sim',
    observacoes                TEXT
);

CREATE INDEX idx_sessao_cliente_id ON sessao(cliente_id);
CREATE INDEX idx_sessao_caso_id ON sessao(caso_id);
CREATE INDEX idx_sessao_status_sessao ON sessao(status_sessao);

-- Fonte: docs/schema_memoria_ia.md (09_Memoria_IA).
-- servicos_recentes/processos_recentes/assuntos_recentes ficam texto
-- livre de propósito: são resumo em linguagem natural reescrito pelo
-- Motor de Memória, não registro transacional normalizado.
-- memoria_id não constava em 91_Padrao_IDs, mesma observação de sessao_id.
CREATE TABLE memoria_ia (
    memoria_id                TEXT PRIMARY KEY,          -- MEM-000001
    cliente_id                 TEXT NOT NULL REFERENCES cliente(cliente_id),
    resumo_cliente              TEXT,
    assuntos_recentes           TEXT,
    servicos_recentes           TEXT,
    processos_recentes          TEXT,
    ultima_intencao              TEXT,
    preferencia_canal            TEXT,
    tom_recomendado              TEXT,
    informacoes_importantes      TEXT,
    restricoes_atendimento       TEXT,
    ultima_sessao_id             TEXT REFERENCES sessao(sessao_id),
    atualizada_em                TEXT NOT NULL,            -- ISO 8601
    atualizada_por               TEXT NOT NULL,
    versao                       INTEGER NOT NULL DEFAULT 1,
    ativo                        TEXT NOT NULL DEFAULT 'Sim',
    observacoes                  TEXT
);

CREATE INDEX idx_memoria_ia_cliente_id ON memoria_ia(cliente_id);

-- Garante uma única memória "vigente" por cliente: trocar a memória
-- significa inativar a antiga (ativo='Não') e criar uma linha nova,
-- preservando histórico.
CREATE UNIQUE INDEX idx_memoria_ia_cliente_ativo ON memoria_ia(cliente_id) WHERE ativo = 'Sim';
