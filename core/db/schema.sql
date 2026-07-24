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
    responsavel_id          TEXT REFERENCES usuario(usuario_id),
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
    responsavel_id    TEXT REFERENCES usuario(usuario_id),
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
    revisado_por_id   TEXT REFERENCES usuario(usuario_id),
    observacoes       TEXT,
    mensagem_id       TEXT REFERENCES mensagem(mensagem_id), -- qual mensagem trouxe este anexo (nullable -- doc migrado/antigo não tem)
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
    responsavel_id             TEXT REFERENCES usuario(usuario_id),
    conversa_id_origem         TEXT REFERENCES conversa(conversa_id),
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

-- Fonte: docs/schema_historico_log_usuario.md.
-- Diferente das tabelas anteriores, não existe aba própria na planilha
-- para usuario/historico/log_ia — desenhadas a partir de 91_Padrao_IDs,
-- 92_Matriz_Dependencias e 95_Regras_Casos. Minima de propósito: login e
-- permissões de verdade ficam para a Fase 6 (Produto) do PROJETO_1.md.
CREATE TABLE usuario (
    usuario_id    TEXT PRIMARY KEY,                  -- USR-000001
    nome          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    papel         TEXT NOT NULL,                       -- texto livre (ex.: Despachante, Atendimento, Gestor)
    equipe        TEXT,
    ativo         TEXT NOT NULL DEFAULT 'Sim',
    criado_em     TEXT NOT NULL,                        -- ISO 8601
    senha_hash    TEXT                                  -- hash (werkzeug), nunca a senha em texto puro; NULL = login ainda não configurado, ver webapp/definir_senha.py
);

-- Log de eventos de negócio do caso — append-only (só INSERT, nunca
-- UPDATE/DELETE). RCA-007: toda troca de responsável gera registro aqui.
-- 96_Relacionamentos_Casos: "todo evento do caso deve apontar para o
-- caso"; "nunca excluir".
CREATE TABLE historico (
    historico_id     TEXT PRIMARY KEY,                 -- HIS-000001
    caso_id          TEXT NOT NULL REFERENCES caso(caso_id),
    tipo_evento      TEXT NOT NULL CHECK (tipo_evento IN ('criacao', 'mudanca_status', 'troca_responsavel', 'encerramento', 'outro')),
    descricao        TEXT,
    valor_anterior   TEXT,
    valor_novo       TEXT,
    criado_em        TEXT NOT NULL,                      -- ISO 8601
    criado_por       TEXT NOT NULL
);

CREATE INDEX idx_historico_caso_id ON historico(caso_id);

-- Log técnico de execução da IA (uma linha por chamada relevante ao
-- modelo). Fonte: 92_Matriz_Dependencias, linha "Auditoria IA".
-- Diferente de historico: aqui é auditoria técnica, não evento de negócio.
CREATE TABLE log_ia (
    log_id                    TEXT PRIMARY KEY,          -- LOG-000001
    caso_id                   TEXT REFERENCES caso(caso_id),
    sessao_id                 TEXT REFERENCES sessao(sessao_id),
    prompt_key                TEXT NOT NULL,               -- ex.: CLASSIFICADOR (ver 21_Prompts.prompt_key)
    modelo                    TEXT NOT NULL,                -- ex.: gpt-5-mini
    tokens_entrada             INTEGER,
    tokens_saida                INTEGER,
    tempo_processamento_ms      INTEGER,
    resultado                    TEXT NOT NULL CHECK (resultado IN ('Sucesso', 'Erro')),
    erro                          TEXT,
    criado_em                     TEXT NOT NULL              -- ISO 8601
);

CREATE INDEX idx_log_ia_caso_id ON log_ia(caso_id);
CREATE INDEX idx_log_ia_sessao_id ON log_ia(sessao_id);

-- Fonte: docs/schema_conversa_template.md (07_Conversas, 96_Relacionamentos_Casos).
-- "Envelope" de um atendimento; as mensagens individuais (06_Mensagens)
-- ficam para uma tabela mensagem numa próxima rodada.
CREATE TABLE conversa (
    conversa_id           TEXT PRIMARY KEY,             -- CON-000001
    cliente_id             TEXT NOT NULL REFERENCES cliente(cliente_id),
    caso_id                 TEXT REFERENCES caso(caso_id),
    sessao_id               TEXT REFERENCES sessao(sessao_id),
    canal                    TEXT NOT NULL,
    origem                   TEXT NOT NULL,
    status                   TEXT NOT NULL,
    assunto_principal        TEXT,
    iniciada_em              TEXT NOT NULL,               -- ISO 8601
    ultima_mensagem_em       TEXT NOT NULL,                -- ISO 8601
    encerrada_em             TEXT,                          -- ISO 8601
    responsavel_id           TEXT REFERENCES usuario(usuario_id),
    precisa_humano           TEXT,                          -- Sim/Não, texto livre
    total_mensagens          INTEGER NOT NULL DEFAULT 0,
    criado_por                TEXT NOT NULL,
    atualizado_por             TEXT NOT NULL,
    versao                     INTEGER NOT NULL DEFAULT 1,
    ativo                       TEXT NOT NULL DEFAULT 'Sim',
    observacoes                 TEXT
);

CREATE INDEX idx_conversa_cliente_id ON conversa(cliente_id);
CREATE INDEX idx_conversa_caso_id ON conversa(caso_id);
CREATE INDEX idx_conversa_sessao_id ON conversa(sessao_id);

-- Fonte: docs/schema_conversa_template.md. Recupera os 7 campos tirados
-- de servico na 2ª rodada. Diferente de 21_Prompts (que fica para a Fase
-- 2 do PROJETO_1.md): template é texto pronto de resposta, prompt é
-- instrução para o modelo pensar.
CREATE TABLE template (
    template_id     TEXT PRIMARY KEY,                    -- TPL-000001
    template_key    TEXT NOT NULL UNIQUE,
    nome            TEXT NOT NULL,
    categoria       TEXT,
    conteudo        TEXT NOT NULL,                         -- pode ter marcadores {campo}
    canal           TEXT,                                    -- Email, WhatsApp, ou vazio = qualquer canal
    ativo           TEXT NOT NULL DEFAULT 'Sim',
    observacoes     TEXT
);

-- Fonte: docs/schema_mensagem.md (06_Mensagens). Última tabela do Core
-- mínimo. protocolo foi removido (redundante com processo.protocolo).
-- mensagem (corpo do texto) é opcional: um dos registros reais migrados
-- tinha esse campo corrompido na origem (bug de serialização XML no Make).
CREATE TABLE mensagem (
    mensagem_id             TEXT PRIMARY KEY,             -- MSG-000001
    cliente_id                TEXT NOT NULL REFERENCES cliente(cliente_id),
    caso_id                    TEXT REFERENCES caso(caso_id),
    conversa_id                TEXT REFERENCES conversa(conversa_id),
    processo_id                 TEXT REFERENCES processo(processo_id),
    canal                        TEXT NOT NULL,
    data_hora                     TEXT NOT NULL,             -- ISO 8601
    origem                         TEXT NOT NULL,
    email_remetente                 TEXT,
    assunto                          TEXT,
    mensagem                          TEXT,
    intent                             TEXT,
    resumo_ia                          TEXT,
    precisa_humano                      TEXT,                -- Sim/Não, texto livre
    status_processamento                 TEXT NOT NULL,
    id_externo                            TEXT,
    resposta_ia                            TEXT,
    responsavel_id                          TEXT REFERENCES usuario(usuario_id),
    tempo_processamento_ms                   INTEGER,
    modelo_ia                                 TEXT,
    observacoes_ia                             TEXT
);

CREATE INDEX idx_mensagem_cliente_id ON mensagem(cliente_id);
CREATE INDEX idx_mensagem_caso_id ON mensagem(caso_id);
CREATE INDEX idx_mensagem_conversa_id ON mensagem(conversa_id);
CREATE INDEX idx_mensagem_processo_id ON mensagem(processo_id);

-- Fonte: docs/schema_configuracoes_tarefas.md (20_Configuracoes). Aba mais
-- limpa até agora; só 2 chaves duplicadas (mesmo valor, config_id diferente)
-- descartadas na migração.
CREATE TABLE configuracoes (
    config_id     TEXT PRIMARY KEY,                  -- CFG-000001
    chave         TEXT NOT NULL UNIQUE,
    valor         TEXT NOT NULL,                       -- sempre texto, mesmo quando é número
    categoria     TEXT NOT NULL,
    descricao     TEXT,
    ativo         TEXT NOT NULL DEFAULT 'Sim'
);

-- Fonte: docs/schema_configuracoes_tarefas.md (07_Tarefas,
-- 96_Relacionamentos_Casos). tarefa.caso_id é campo novo (mesma situação
-- de processo.caso_id): não existia na planilha, mas toda tarefa de
-- atendimento deve pertencer a um caso.
CREATE TABLE tarefas (
    tarefa_id        TEXT PRIMARY KEY,                -- TAR-000001
    caso_id          TEXT NOT NULL REFERENCES caso(caso_id),
    cliente_id       TEXT NOT NULL REFERENCES cliente(cliente_id),
    processo_id      TEXT REFERENCES processo(processo_id),
    tipo             TEXT NOT NULL,
    descricao        TEXT,
    responsavel_id   TEXT REFERENCES usuario(usuario_id),
    prazo            TEXT,                             -- ISO 8601
    prioridade       TEXT NOT NULL,
    status           TEXT NOT NULL,
    data_conclusao   TEXT,                              -- ISO 8601
    observacoes      TEXT
);

CREATE INDEX idx_tarefas_caso_id ON tarefas(caso_id);
CREATE INDEX idx_tarefas_cliente_id ON tarefas(cliente_id);
CREATE INDEX idx_tarefas_processo_id ON tarefas(processo_id);
