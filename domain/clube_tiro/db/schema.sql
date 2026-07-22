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
