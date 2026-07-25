-- Schema de Domínio — Clube de Tiro. Banco separado do Core de propósito
-- (ver docs/schema_conhecimento_dominio.md): o Core precisa funcionar sem
-- nenhuma referência hardcoded a este domínio (PROJETO_1.md, seção 8).
--
-- Para consultar Core + Domínio juntos, anexar na mesma conexão:
--   ATTACH DATABASE 'core/db/erp_smith.db' AS core;
-- Sem FK cruzando os dois bancos — SQLite não aplica FOREIGN KEY entre
-- bancos anexados. conhecimento é material de referência institucional
-- (perguntas/respostas gerais), não dado de cliente/caso específico.

PRAGMA foreign_keys = ON;

-- Fonte: 92_Matriz_Dependencias (linha "Motor de Conhecimento"),
-- 91_Padrao_IDs (prefixo KNW). Não existe aba própria na planilha; nasce
-- vazia, populada manualmente ou pelo Motor de Conhecimento (Fase 2+).
CREATE TABLE conhecimento (
    conhecimento_id  TEXT PRIMARY KEY,                -- KNW-000001
    categoria        TEXT NOT NULL,                    -- CR, CRAF, Transferência, Habitualidade, Aquisição, Guias, Legislação
    pergunta         TEXT NOT NULL,
    resposta         TEXT NOT NULL,
    aprovado         TEXT NOT NULL DEFAULT 'Não',        -- conhecimento aprovado tem prioridade
    ativo            TEXT NOT NULL DEFAULT 'Sim',
    criado_em        TEXT NOT NULL                        -- ISO 8601
);

CREATE INDEX idx_conhecimento_categoria ON conhecimento(categoria);

-- Calendário de campeonatos/provas do clube. Nasce populado à mão a
-- partir do calendário público (https://www.smithclube.com.br/calendario/),
-- porque o Shooting House (integracoes/shooting_house.py) já modela
-- "campeonatos" do atirador mas ainda não tem credencial liberada --
-- mesmo raciocínio do dado "simulado" de lá: origem='manual' identifica
-- o que foi digitado aqui até um dia dar pra reconciliar com a API de
-- verdade (origem='shooting_house'), em vez de essa tabela virar uma
-- segunda fonte de verdade permanente.
CREATE TABLE campeonato (
    campeonato_id    TEXT PRIMARY KEY,                  -- CAM-000001
    nome             TEXT NOT NULL,
    data_inicio      TEXT NOT NULL,                       -- ISO 8601 (YYYY-MM-DD)
    data_fim         TEXT NOT NULL,                       -- igual a data_inicio quando é um único dia
    local            TEXT,                                -- nullable -- nem toda prova é na sede
    observacoes      TEXT,
    origem           TEXT NOT NULL DEFAULT 'manual',       -- 'manual' | 'shooting_house'
    ativo            TEXT NOT NULL DEFAULT 'Sim',
    criado_em        TEXT NOT NULL,                        -- ISO 8601
    atualizado_em    TEXT NOT NULL                          -- ISO 8601
);

CREATE INDEX idx_campeonato_data ON campeonato(data_inicio);

-- Classificação de uma prova/campeonato -- só existe pra campeonatos já
-- ocorridos. Mesmo raciocínio de origem='manual' do campeonato acima:
-- Shooting House já modela resultado de atirador mas ainda não tem
-- credencial liberada, então por enquanto é digitado à mão (decisão do
-- usuário 2026-07-25: quando a integração existir, esses 4 campos
-- (colocação, modalidade, pontuação, observações) são exatamente o que
-- o Shooting House deve mandar automaticamente).
--
-- Mostra a CLASSIFICAÇÃO COMPLETA da prova no Portal, não só o resultado
-- do cliente que está logado (decisão do usuário) -- por isso
-- nome_atirador é sempre preenchido (mesmo pra quem não é cliente do
-- despachante) e cliente_id é opcional, preenchido só quando o atirador
-- também é cliente (permite destacar "você" na lista sem exigir que
-- todo participante da prova esteja cadastrado como cliente). Cross-db
-- pra core.cliente, sem FK de verdade -- mesma regra de core/conexao.py
-- (integridade é responsabilidade do código, não do banco).
CREATE TABLE resultado_campeonato (
    resultado_id     TEXT PRIMARY KEY,                  -- RES-000001
    campeonato_id    TEXT NOT NULL REFERENCES campeonato(campeonato_id),
    cliente_id       TEXT,                               -- nullable -- ver comentário acima
    nome_atirador    TEXT NOT NULL,
    modalidade       TEXT,                                -- nullable = prova sem quebra por modalidade/categoria ("Geral")
    colocacao        INTEGER,                              -- posição final (1, 2, 3...), nullable
    pontuacao        TEXT,                                 -- texto livre -- formato de pontuação varia por modalidade
    observacoes      TEXT,
    origem           TEXT NOT NULL DEFAULT 'manual',       -- 'manual' | 'shooting_house'
    criado_em        TEXT NOT NULL,                        -- ISO 8601
    atualizado_em    TEXT NOT NULL                          -- ISO 8601
);

CREATE INDEX idx_resultado_campeonato ON resultado_campeonato(campeonato_id);
CREATE INDEX idx_resultado_cliente ON resultado_campeonato(cliente_id);
