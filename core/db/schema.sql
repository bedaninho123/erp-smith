-- Schema Core do ERP Smith — SQLite
-- Gerado a partir de docs/schema_core_cliente_caso.md, com base na planilha
-- "Banco de Dados - Clube de Tiro.xlsx" (abas 02_Clientes, 90_Dicionario_Dados,
-- 91_Padrao_IDs, 94_Contrato_Casos, 95_Regras_Casos, 96_Relacionamentos_Casos).
--
-- Convenções do projeto:
--   * IDs: TEXT, formato PREFIXO-000000 (6 dígitos), gerados pelo sistema, imutáveis.
--   * Datas/horas: TEXT em ISO 8601 (ex.: 2026-07-17T22:15:29Z).
--   * "Sim"/"Não" em vez de booleano, para ficar igual à planilha original.
--
-- MULTI-TENANT (docs/schema_multi_tenant.md, decisões de 2026-07-28):
--   * Toda tabela carrega empresa_id -- inclusive as três que poderiam
--     herdar do pai (historico, documento_checklist, portal_token). A
--     redundância é proposital: query que filtra direto, sem JOIN, é
--     query com menos chance de esquecer o filtro.
--   * As UNIQUE que envolvem dado de negócio são compostas com
--     empresa_id. O mesmo CPF PODE ser cliente de dois despachantes
--     diferentes; a única exceção é portal_token.token, que é segredo
--     de autenticação e continua único globalmente.

PRAGMA foreign_keys = ON;

-- Raiz do multi-tenant. Cada linha é uma empresa que usa o sistema; toda
-- outra tabela do Core aponta para cá.
CREATE TABLE empresa (
    empresa_id    TEXT PRIMARY KEY,               -- EMP-000001
    nome          TEXT NOT NULL,
    dominio       TEXT NOT NULL,                    -- qual pacote de Domínio usa (ex.: clube_tiro)
    ativo         TEXT NOT NULL DEFAULT 'Sim',      -- empresa suspensa vira 'Não', nunca é apagada
    criado_em     TEXT NOT NULL                     -- ISO 8601, imutável
);

CREATE TABLE cliente (
    cliente_id      TEXT PRIMARY KEY,              -- CLI-000001
    empresa_id      TEXT NOT NULL REFERENCES empresa(empresa_id),
    nome            TEXT NOT NULL,
    cpf             TEXT,                           -- só dígitos, sem pontuação
    -- NULL = contato que chegou por e-mail e ainda não informou o CPF
    -- (core/motor_clientes.py::obter_ou_criar_contato_por_email). Banco em
    -- uso com NOT NULL: core.db.migrar_cliente_sem_cpf.
    email           TEXT,
    telefone        TEXT,
    cidade          TEXT,
    status          TEXT NOT NULL,                  -- texto livre por enquanto (ex.: Ativo, Inativo)
    atendimento_ia  TEXT NOT NULL,                   -- texto livre por enquanto (Sim/Não)
    data_cadastro   TEXT NOT NULL,                   -- ISO 8601, imutável
    ultima_interacao TEXT,                           -- ISO 8601
    observacoes     TEXT,
    -- Composta, não global: a mesma pessoa pode ser cliente de mais de
    -- um despachante. Com UNIQUE(cpf) simples, a segunda empresa a
    -- cadastrar esse CPF receberia um erro sem sentido nenhum.
    UNIQUE (empresa_id, cpf)
);

CREATE INDEX idx_cliente_empresa_id ON cliente(empresa_id);

-- RCA-001: todo caso deve ter um cliente_id válido existente em cliente.
-- RCA-002: caso_id nunca é alterado depois de criado.
-- RCA-009: a IA nunca encerra, cancela ou muda prioridade diretamente — isso é
--          responsabilidade do Core, não é imposto pelo banco.
CREATE TABLE caso (
    caso_id                TEXT PRIMARY KEY,        -- CAS-000001
    empresa_id             TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_caso_empresa_id ON caso(empresa_id);
CREATE INDEX idx_caso_cliente_id ON caso(cliente_id);
CREATE INDEX idx_caso_status ON caso(status);

-- Fonte: docs/schema_processo_servico.md (01_Servicos, 04_Processos).
-- Campos de texto-padrão/resposta pronta (mensagem_padrao, prazo_texto,
-- valor_texto, resposta_*) ficaram FORA de propósito — são template
-- genérico repetido, não dado do serviço. Ficam para uma futura tabela
-- de Templates.
--
-- Multi-tenant: prazo_estimado_dias e valor_referencia são por empresa --
-- outro despachante cobra outro preço e promete outro prazo.
CREATE TABLE servico (
    service_id              TEXT PRIMARY KEY,         -- SER-000001
    empresa_id              TEXT NOT NULL REFERENCES empresa(empresa_id),
    service_key             TEXT NOT NULL,             -- ex.: renovacao_cr
    nome_servico             TEXT NOT NULL,
    descricao                TEXT,
    categoria                TEXT NOT NULL,             -- mesma lista de caso.categoria
    prazo_estimado_dias      INTEGER,
    valor_referencia         REAL,                       -- número puro, ex. 850.00
    documentos_obrigatorios  TEXT NOT NULL,
    ativo                    TEXT NOT NULL DEFAULT 'Sim',
    observacoes              TEXT,
    -- Toda empresa vai querer ter um serviço com a chave renovacao_cr.
    UNIQUE (empresa_id, service_key)
);

CREATE INDEX idx_servico_empresa_id ON servico(empresa_id);

-- Checklist detalhado de documentos por serviço (2026-07-24, usuário
-- passou as listas reais de CR/CRAF/Aquisição/Transferência/Guia de
-- Tráfego). documentos_obrigatorios (acima) continua existindo como
-- resumo curto usado no catálogo geral; esta tabela é a lista completa,
-- organizada em grupos, usada quando o cliente pergunta sobre UM serviço
-- específico. Não tem FK pra caso/processo -- é conhecimento de
-- catálogo, igual servico, não dado de atendimento de cliente.
CREATE TABLE documento_exigido (
    documento_exigido_id  TEXT PRIMARY KEY,             -- DEX-000001
    empresa_id             TEXT NOT NULL REFERENCES empresa(empresa_id),
    servico_id             TEXT NOT NULL REFERENCES servico(service_id),
    grupo                  TEXT,                          -- ex.: "Documentos Pessoais e Residenciais" (pode ser NULL)
    item                    TEXT NOT NULL,
    ordem                   INTEGER NOT NULL,
    ativo                   TEXT NOT NULL DEFAULT 'Sim',
    -- NULL = item do SERVIÇO (vale para todo processo). Preenchido = item
    -- extra de UM processo só -- a segunda capacidade técnica de quem tem
    -- pistola e carabina (2026-09-24, core/db/migrar_itens_por_processo.py).
    processo_id             TEXT
);

CREATE INDEX idx_documento_exigido_empresa_id ON documento_exigido(empresa_id);
CREATE INDEX idx_documento_exigido_servico ON documento_exigido(servico_id);

-- RCA/matriz: a IA nunca altera processo.status; só informa proxima_acao cadastrada.
-- processo.caso_id é campo novo (não existia na planilha) — exigido por
-- 96_Relacionamentos_Casos: "todo processo operacional deve pertencer a um caso".
CREATE TABLE processo (
    processo_id       TEXT PRIMARY KEY,                 -- PRO-000001
    empresa_id        TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_processo_empresa_id ON processo(empresa_id);
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
    empresa_id        TEXT NOT NULL REFERENCES empresa(empresa_id),
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
    -- 'Caso' | 'Dossiê' (2026-08-27). Um documento de atendimento
    -- pertence a um caso; o CR, o CRAF e o comprovante de residência
    -- pertencem à PESSOA -- valem por anos, atravessam vários casos e
    -- continuam valendo quando todos fecharem. Lista controlada em
    -- código (core/motor_documentos.py), não CHECK de valor, mesmo
    -- padrão do status do Caso.
    categoria         TEXT NOT NULL DEFAULT 'Caso',
    -- Finalidade de uso da arma a que este documento se refere -- 'Tiro'
    -- / 'Caça' / 'Coleção' (2026-09-01). Vocabulário de CAC, então o Core
    -- só guarda o texto e não valida contra essa lista (mesmo motivo de
    -- tipo_documento): quem sabe o que são essas três palavras é
    -- domain/clube_tiro/documentos_cac.py, oferecida como SELECT na
    -- tela. Sempre NULL em documento de Caso e em documento de dossiê
    -- que não é de arma nenhuma (CPF, comprovante de residência).
    finalidade        TEXT,
    -- O CHECK cobre os dois e não deixa zona cinzenta: dossiê com caso
    -- preenchido é recusado, e documento de caso sem caso também.
    CHECK (
        (categoria = 'Dossiê' AND caso_id IS NULL AND processo_id IS NULL)
        OR
        (categoria = 'Caso' AND (caso_id IS NOT NULL OR processo_id IS NOT NULL))
    )
);

CREATE INDEX idx_documento_empresa_id ON documento(empresa_id);
CREATE INDEX idx_documento_cliente_id ON documento(cliente_id);
CREATE INDEX idx_documento_caso_id ON documento(caso_id);
CREATE INDEX idx_documento_processo_id ON documento(processo_id);
-- A tela do dossiê lê sempre por (empresa, cliente, categoria).
CREATE INDEX idx_documento_categoria ON documento(empresa_id, cliente_id, categoria);

-- Rastreamento de documento recebido vs. exigido, por processo (2026-07-24).
-- Marcação sempre manual -- um funcionário confirma visualmente que um
-- arquivo recebido é de fato aquele documento do checklist; a IA nunca
-- infere/decide essa correspondência sozinha (seria a IA decidindo regra
-- de negócio, o que o projeto proíbe). Um documento pode atender mais de
-- um item (ex.: um PDF só com RG+CPF juntos), e um item pode ter mais de
-- um documento marcado (raro, mas não impedido).
CREATE TABLE documento_checklist (
    documento_checklist_id  TEXT PRIMARY KEY,             -- DCK-000001
    empresa_id                TEXT NOT NULL REFERENCES empresa(empresa_id),
    processo_id               TEXT NOT NULL REFERENCES processo(processo_id),
    documento_exigido_id      TEXT NOT NULL REFERENCES documento_exigido(documento_exigido_id),
    documento_id                TEXT NOT NULL REFERENCES documento(documento_id),
    marcado_em                   TEXT NOT NULL,             -- ISO 8601
    marcado_por                   TEXT NOT NULL,
    -- O padrão é 'Aprovado' de propósito: quando um funcionário marca o
    -- documento pelo painel, a marcação JÁ É a aprovação -- ele olhou o
    -- arquivo pra decidir que atende o item. Só o que chega pelo Portal
    -- (o cliente dizendo "mandei este documento pra este item") nasce
    -- 'Aguardando aprovação', porque aí ninguém da equipe conferiu ainda.
    status                        TEXT NOT NULL DEFAULT 'Aprovado'
        CHECK (status IN ('Aguardando aprovação', 'Aprovado', 'Recusado')),
    revisado_em                   TEXT,                      -- ISO 8601
    revisado_por                  TEXT,
    -- Só preenchido quando status='Recusado'. É mostrado ao cliente no
    -- Portal: sem o motivo, ele reenvia o mesmo arquivo errado sem saber
    -- o porquê.
    motivo_recusa                 TEXT
);

CREATE INDEX idx_documento_checklist_empresa_id ON documento_checklist(empresa_id);
CREATE INDEX idx_documento_checklist_processo ON documento_checklist(processo_id);
CREATE UNIQUE INDEX idx_documento_checklist_par ON documento_checklist(processo_id, documento_exigido_id, documento_id);

-- Fonte: docs/schema_documento_sessao.md (08_Sessoes, 40_Listas_Auxiliares).
-- sessao.caso_id é campo novo e opcional: "uma sessão pode iniciar sem
-- caso e ser vinculada após classificação" (96_Relacionamentos_Casos).
-- sessao_id não constava em 91_Padrao_IDs, mas os dados de exemplo já
-- seguem o padrão de 6 dígitos (SES-000001) — vale completar a planilha depois.
CREATE TABLE sessao (
    sessao_id                TEXT PRIMARY KEY,           -- SES-000001
    empresa_id                TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_sessao_empresa_id ON sessao(empresa_id);
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
    empresa_id                 TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_memoria_ia_empresa_id ON memoria_ia(empresa_id);
CREATE INDEX idx_memoria_ia_cliente_id ON memoria_ia(cliente_id);

-- Garante uma única memória "vigente" por cliente: trocar a memória
-- significa inativar a antiga (ativo='Não') e criar uma linha nova,
-- preservando histórico. Não precisa de empresa_id: cliente_id já
-- pertence a uma empresa só.
CREATE UNIQUE INDEX idx_memoria_ia_cliente_ativo ON memoria_ia(cliente_id) WHERE ativo = 'Sim';

-- Fonte: docs/schema_historico_log_usuario.md.
-- Diferente das tabelas anteriores, não existe aba própria na planilha
-- para usuario/historico/log_ia — desenhadas a partir de 91_Padrao_IDs,
-- 92_Matriz_Dependencias e 95_Regras_Casos.
CREATE TABLE usuario (
    usuario_id    TEXT PRIMARY KEY,                  -- USR-000001
    empresa_id    TEXT NOT NULL REFERENCES empresa(empresa_id),
    nome          TEXT NOT NULL,
    email         TEXT NOT NULL,
    -- Sem CHECK de propósito: os valores válidos ('Gestor', 'Atendente')
    -- são validados em core/motor_usuarios.PAPEIS_VALIDOS, mesmo padrão
    -- do status do Caso (validado em core/motor_casos.py, não no schema).
    papel         TEXT NOT NULL,
    equipe        TEXT,
    ativo         TEXT NOT NULL DEFAULT 'Sim',
    criado_em     TEXT NOT NULL,                        -- ISO 8601
    senha_hash    TEXT,                                 -- hash (werkzeug), nunca a senha em texto puro; NULL = login ainda não configurado, ver webapp/definir_senha.py
    UNIQUE (empresa_id, email)
);

CREATE INDEX idx_usuario_empresa_id ON usuario(empresa_id);

-- Permissão granular por função, só para usuario.papel = 'Atendente'
-- (Gestor tem acesso total e intocável, nunca consulta esta tabela).
-- Sem linha para uma função = permitido -- ver core/motor_usuarios.py
-- (FUNCOES_VALIDAS, tem_permissao). Só ganha linha quando o Gestor mexe
-- explicitamente naquela função pela tela de Usuários.
CREATE TABLE usuario_permissao (
    usuario_id  TEXT NOT NULL REFERENCES usuario(usuario_id),
    empresa_id  TEXT NOT NULL REFERENCES empresa(empresa_id),
    funcao      TEXT NOT NULL,
    ativo       TEXT NOT NULL DEFAULT 'Sim',
    PRIMARY KEY (usuario_id, funcao)
);

CREATE INDEX idx_usuario_permissao_empresa_id ON usuario_permissao(empresa_id);

-- Log administrativo -- append-only, mesmo espírito de historico, mas
-- pra ação de gestão (papel/ativo/permissão de usuário, configuração da
-- empresa), não evento de Caso. Achado na auditoria de riscos de
-- 2026-07-30: sem isso, "quem desligou a revisão humana" não tinha
-- resposta. Ver core/motor_log_administrativo.py.
CREATE TABLE log_administrativo (
    log_administrativo_id TEXT PRIMARY KEY,   -- ADM-000001
    empresa_id             TEXT NOT NULL REFERENCES empresa(empresa_id),
    tipo_evento             TEXT NOT NULL,     -- papel_alterado | ativo_alterado | permissao_alterada | configuracao_alterada
    alvo                    TEXT NOT NULL,     -- usuario_id ou config_id afetado
    descricao                TEXT,
    valor_anterior          TEXT,
    valor_novo               TEXT,
    criado_em                TEXT NOT NULL,     -- ISO 8601
    criado_por                TEXT NOT NULL
);

CREATE INDEX idx_log_administrativo_empresa_id ON log_administrativo(empresa_id);

-- Log de eventos de negócio do caso — append-only (só INSERT, nunca
-- UPDATE/DELETE). RCA-007: toda troca de responsável gera registro aqui.
-- 96_Relacionamentos_Casos: "todo evento do caso deve apontar para o
-- caso"; "nunca excluir".
CREATE TABLE historico (
    historico_id     TEXT PRIMARY KEY,                 -- HIS-000001
    empresa_id       TEXT NOT NULL REFERENCES empresa(empresa_id),
    caso_id          TEXT NOT NULL REFERENCES caso(caso_id),
    tipo_evento      TEXT NOT NULL CHECK (tipo_evento IN ('criacao', 'mudanca_status', 'troca_responsavel', 'encerramento', 'outro')),
    descricao        TEXT,
    valor_anterior   TEXT,
    valor_novo       TEXT,
    criado_em        TEXT NOT NULL,                      -- ISO 8601
    criado_por       TEXT NOT NULL
);

CREATE INDEX idx_historico_empresa_id ON historico(empresa_id);
CREATE INDEX idx_historico_caso_id ON historico(caso_id);

-- Log técnico de execução da IA (uma linha por chamada relevante ao
-- modelo). Fonte: 92_Matriz_Dependencias, linha "Auditoria IA".
-- Diferente de historico: aqui é auditoria técnica, não evento de negócio.
--
-- empresa_id aqui não é burocracia: é o que responde "quanto de IA cada
-- empresa consumiu", base do billing por assinatura (docs/schema_multi_tenant.md §3).
CREATE TABLE log_ia (
    log_id                    TEXT PRIMARY KEY,          -- LOG-000001
    empresa_id                TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_log_ia_empresa_id ON log_ia(empresa_id);
CREATE INDEX idx_log_ia_caso_id ON log_ia(caso_id);
CREATE INDEX idx_log_ia_sessao_id ON log_ia(sessao_id);

-- Fonte: docs/schema_conversa_template.md (07_Conversas, 96_Relacionamentos_Casos).
-- "Envelope" de um atendimento; as mensagens individuais (06_Mensagens)
-- ficam para uma tabela mensagem numa próxima rodada.
CREATE TABLE conversa (
    conversa_id           TEXT PRIMARY KEY,             -- CON-000001
    empresa_id             TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_conversa_empresa_id ON conversa(empresa_id);
CREATE INDEX idx_conversa_cliente_id ON conversa(cliente_id);
CREATE INDEX idx_conversa_caso_id ON conversa(caso_id);
CREATE INDEX idx_conversa_sessao_id ON conversa(sessao_id);

-- Fonte: docs/schema_conversa_template.md. Recupera os 7 campos tirados
-- de servico na 2ª rodada. Diferente de 21_Prompts (que fica para a Fase
-- 2 do PROJETO_1.md): template é texto pronto de resposta, prompt é
-- instrução para o modelo pensar.
--
-- Multi-tenant: cada empresa tem a assinatura de e-mail dela.
CREATE TABLE template (
    template_id     TEXT PRIMARY KEY,                    -- TPL-000001
    empresa_id      TEXT NOT NULL REFERENCES empresa(empresa_id),
    template_key    TEXT NOT NULL,
    nome            TEXT NOT NULL,
    categoria       TEXT,
    conteudo        TEXT NOT NULL,                         -- pode ter marcadores {campo}
    canal           TEXT,                                    -- Email, WhatsApp, ou vazio = qualquer canal
    ativo           TEXT NOT NULL DEFAULT 'Sim',
    observacoes     TEXT,
    UNIQUE (empresa_id, template_key)
);

CREATE INDEX idx_template_empresa_id ON template(empresa_id);

-- Fonte: docs/schema_mensagem.md (06_Mensagens). Última tabela do Core
-- mínimo. protocolo foi removido (redundante com processo.protocolo).
-- mensagem (corpo do texto) é opcional: um dos registros reais migrados
-- tinha esse campo corrompido na origem (bug de serialização XML no Make).
CREATE TABLE mensagem (
    mensagem_id             TEXT PRIMARY KEY,             -- MSG-000001
    empresa_id                TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_mensagem_empresa_id ON mensagem(empresa_id);
CREATE INDEX idx_mensagem_cliente_id ON mensagem(cliente_id);
CREATE INDEX idx_mensagem_caso_id ON mensagem(caso_id);
CREATE INDEX idx_mensagem_conversa_id ON mensagem(conversa_id);
CREATE INDEX idx_mensagem_processo_id ON mensagem(processo_id);

-- Fonte: docs/schema_configuracoes_tarefas.md (20_Configuracoes). Aba mais
-- limpa até agora; só 2 chaves duplicadas (mesmo valor, config_id diferente)
-- descartadas na migração.
--
-- Multi-tenant: nome_empresa, telefone, horario_*, assinatura_email e
-- revisao_humana_ativa são todos por empresa. Uma empresa pode querer o
-- freio de revisão humana ligado e outra não.
CREATE TABLE configuracoes (
    config_id     TEXT PRIMARY KEY,                  -- CFG-000001
    empresa_id    TEXT NOT NULL REFERENCES empresa(empresa_id),
    chave         TEXT NOT NULL,
    valor         TEXT NOT NULL,                       -- sempre texto, mesmo quando é número
    categoria     TEXT NOT NULL,
    descricao     TEXT,
    ativo         TEXT NOT NULL DEFAULT 'Sim',
    -- Sem isso, só poderia existir UMA linha com chave='telefone' no
    -- banco inteiro -- ou seja, uma empresa só.
    UNIQUE (empresa_id, chave)
);

CREATE INDEX idx_configuracoes_empresa_id ON configuracoes(empresa_id);

-- Fonte: docs/schema_configuracoes_tarefas.md (07_Tarefas,
-- 96_Relacionamentos_Casos). tarefa.caso_id é campo novo (mesma situação
-- de processo.caso_id): não existia na planilha, mas toda tarefa de
-- atendimento deve pertencer a um caso.
CREATE TABLE tarefas (
    tarefa_id        TEXT PRIMARY KEY,                -- TAR-000001
    empresa_id       TEXT NOT NULL REFERENCES empresa(empresa_id),
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

CREATE INDEX idx_tarefas_empresa_id ON tarefas(empresa_id);
CREATE INDEX idx_tarefas_caso_id ON tarefas(caso_id);
CREATE INDEX idx_tarefas_cliente_id ON tarefas(cliente_id);
CREATE INDEX idx_tarefas_processo_id ON tarefas(processo_id);

-- Token de login sem senha do Portal do Cliente (docs/portal_cliente_arquitetura.md,
-- decisão 2: link mágico por e-mail). Uso único -- usado_em marcado na hora
-- em que o token vira uma sessão, nunca reutilizável depois disso. Sem FK
-- pra caso/processo -- é infraestrutura de autenticação, não dado de negócio.
CREATE TABLE portal_token (
    portal_token_id  TEXT PRIMARY KEY,               -- PTK-000001
    empresa_id        TEXT NOT NULL REFERENCES empresa(empresa_id),
    -- ÚNICA UNIQUE que continua global de propósito: token é segredo de
    -- autenticação, não dado de negócio. Dois tokens iguais em empresas
    -- diferentes seria falha de segurança, não conveniência.
    token             TEXT NOT NULL UNIQUE,            -- valor aleatório, vai na URL do link
    cliente_id        TEXT NOT NULL REFERENCES cliente(cliente_id),
    criado_em         TEXT NOT NULL,                    -- ISO 8601
    expira_em         TEXT NOT NULL,                     -- ISO 8601 (criado_em + 15 min)
    usado_em          TEXT,                               -- ISO 8601, NULL até ser consumido
    -- Código de 6 dígitos (2026-10-14): a segunda porta da MESMA linha,
    -- para o app instalado no iPhone, que não recebe o link do e-mail
    -- (ver core/motor_portal_auth.py). Guardado só como hash; `desafio`
    -- prende o código ao aparelho que o pediu; esgotadas as tentativas,
    -- o código morre (o link continua valendo).
    codigo_hash       TEXT,
    desafio           TEXT,
    tentativas_codigo INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_portal_token_empresa_id ON portal_token(empresa_id);
CREATE INDEX idx_portal_token_cliente_id ON portal_token(cliente_id);
CREATE INDEX idx_portal_token_desafio ON portal_token(desafio);

-- Marketplace de classificados (2026-09-02) -- mural entre os próprios
-- clientes/afiliados de uma empresa (quem conta como "pode ver e
-- publicar" é decisão de CADA domínio, não deste schema -- no Domínio
-- de clube de tiro é "filiado ativo", ver portal/app.py e
-- domain/clube_tiro/motor_filiados.py). Fica no Core porque
-- "visibilidade por comunidade/afiliação dentro de uma empresa" não é
-- exclusivo de clube de tiro -- um domínio futuro pode ter o mesmo
-- conceito com outro critério de quem participa.
--
-- `categoria` é texto livre com sugestão de tela (mesmo padrão de
-- documento.tipo_documento / domain/clube_tiro/documentos_cac.py) --
-- o Core não sabe o que é "Luneta/Mira".
--
-- SEM tabela de pedido/pagamento: é mural de classificados, combinação
-- de preço e entrega acontece fora do sistema (decisão do usuário,
-- 2026-09-02) -- por isso não existe "comprador" aqui, só quem anuncia.
CREATE TABLE anuncio (
    anuncio_id       TEXT PRIMARY KEY,                  -- ANC-000001
    empresa_id       TEXT NOT NULL REFERENCES empresa(empresa_id),
    cliente_id       TEXT NOT NULL REFERENCES cliente(cliente_id),
    categoria        TEXT NOT NULL,
    titulo           TEXT NOT NULL,
    descricao        TEXT,
    valor            REAL,                              -- número puro, ex. 3500.00; NULL = "a combinar"
    contato_telefone TEXT,
    contato_email    TEXT,
    -- Caminhos de arquivo, um por linha -- mesmo formato de lista simples
    -- já usado no projeto (documento_exigido.itens), não JSON: não há
    -- necessidade de estrutura por item, só uma lista de fotos.
    fotos            TEXT,
    -- Fila de moderação: nasce Pendente, só fica visível a outros depois
    -- que um Gestor/Atendente aprova (mesmo cuidado do documento enviado
    -- pelo Portal no checklist -- ninguém da equipe olhou ainda).
    -- Lista controlada em código (core/motor_marketplace.py), mesmo
    -- padrão do status do Caso.
    status           TEXT NOT NULL DEFAULT 'Pendente',
    motivo_recusa    TEXT,
    revisado_por     TEXT,
    revisado_em      TEXT,                               -- ISO 8601
    criado_em        TEXT NOT NULL,                       -- ISO 8601
    atualizado_em    TEXT NOT NULL                        -- ISO 8601
);

CREATE INDEX idx_anuncio_empresa_id ON anuncio(empresa_id);
CREATE INDEX idx_anuncio_cliente_id ON anuncio(cliente_id);
-- A vitrine sempre filtra por (empresa, status='Aprovado'); "meus
-- anúncios" sempre filtra por (empresa, cliente_id) -- os dois juntos
-- são as duas únicas formas de ler esta tabela.
CREATE INDEX idx_anuncio_status ON anuncio(empresa_id, status);

-- Senha do gov.br do cliente (2026-09-24). CIFRADA -- o valor puro nunca
-- toca o banco; a chave vive em ERP_CHAVE_SENHAS, fora dele. Nenhuma view
-- lê esta tabela: não chega à IA nem ao Portal. Ver
-- core/motor_credenciais.py, que também a cria sob demanda.
CREATE TABLE IF NOT EXISTS credencial_cliente (
    empresa_id       TEXT NOT NULL,
    cliente_id       TEXT NOT NULL,
    tipo             TEXT NOT NULL,          -- 'gov.br'
    segredo_cifrado  TEXT NOT NULL,
    atualizado_em    TEXT NOT NULL,
    atualizado_por   TEXT NOT NULL,
    PRIMARY KEY (empresa_id, cliente_id, tipo)
);
