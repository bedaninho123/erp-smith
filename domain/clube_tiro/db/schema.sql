-- Schema de Domínio — Clube de Tiro. Banco separado do Core de propósito
-- (ver docs/schema_conhecimento_dominio.md): o Core precisa funcionar sem
-- nenhuma referência hardcoded a este domínio (PROJETO_1.md, seção 8).
--
-- Para consultar Core + Domínio juntos, anexar na mesma conexão:
--   ATTACH DATABASE 'core/db/erp_smith.db' AS core;
-- Sem FK cruzando os dois bancos — SQLite não aplica FOREIGN KEY entre
-- bancos anexados. conhecimento é material de referência institucional
-- (perguntas/respostas gerais), não dado de cliente/caso específico.
--
-- ================================================================
-- DUAS NATUREZAS (docs/schema_multi_tenant.md, decisão 7.1 de 2026-07-28)
-- ================================================================
-- Este banco guarda duas coisas de natureza diferente, e a distinção
-- decide quem leva empresa_id:
--
--   1. CONHECIMENTO COMPARTILHADO -- sem empresa_id.
--      O Decreto nº 11.615/2023 é a mesma lei para todo despachante de
--      clube de tiro. Duplicar isso por empresa seria manter N cópias da
--      mesma legislação, que divergiriam com o tempo.
--      Tabelas: conhecimento
--
--   2. DADO OPERACIONAL DA EMPRESA -- com empresa_id.
--      O calendário de provas é de UMA empresa; outro despachante tem o
--      dele. É dado de negócio, não conhecimento de domínio.
--      Tabelas: campeonato, resultado_campeonato
--
-- Por que essas duas não foram para o Core: um escritório de advocacia
-- nunca terá um campeonato. Levar vocabulário de clube de tiro para o
-- Core faria a validação da Fase 5 do PROJETO_1.md ("o Core funciona sem
-- nenhuma referência hardcoded ao domínio") falhar por construção -- e é
-- essa pureza que sustenta a tese de produto multi-domínio.
--
-- Todo pacote de Domínio futuro pode ter as duas áreas: advocacia teria
-- prazos processuais como conhecimento e audiências como dado operacional.

PRAGMA foreign_keys = ON;

-- ---------- NATUREZA 1: conhecimento compartilhado (sem empresa_id) ----------
-- Fonte: 92_Matriz_Dependencias (linha "Motor de Conhecimento"),
-- 91_Padrao_IDs (prefixo KNW). Não existe aba própria na planilha; nasce
-- vazia, populada manualmente ou pelo Motor de Conhecimento (Fase 2+).
--
-- SEM empresa_id de propósito: é legislação federal, igual para toda
-- empresa que opera neste domínio.
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
-- ---------- NATUREZA 2: dado operacional da empresa (com empresa_id) ----------
-- empresa_id aponta para core.empresa, sem FK de verdade: SQLite não
-- aplica FOREIGN KEY entre bancos anexados (mesma regra já usada em
-- resultado_campeonato.cliente_id). Integridade é responsabilidade do
-- código, não do banco.
CREATE TABLE campeonato (
    campeonato_id    TEXT PRIMARY KEY,                  -- CAM-000001
    empresa_id       TEXT NOT NULL,                       -- cross-db → core.empresa
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

CREATE INDEX idx_campeonato_empresa_id ON campeonato(empresa_id);
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
    empresa_id       TEXT NOT NULL,                       -- cross-db → core.empresa
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

CREATE INDEX idx_resultado_empresa_id ON resultado_campeonato(empresa_id);
CREATE INDEX idx_resultado_campeonato ON resultado_campeonato(campeonato_id);
CREATE INDEX idx_resultado_cliente ON resultado_campeonato(cliente_id);

-- Catálogo de modalidades do clube -- ESPELHO de
-- GET /championship/modalities/groups (2026-08-27).
--
-- Por que existe: é o ÚNICO endpoint de campeonato que responde com dado
-- para a credencial do clube. `/championship/stage` devolve lista vazia,
-- e sem id de etapa não há como puxar resultado por prova. Então o que dá
-- para trazer hoje é o vocabulário: 13 grupos, ~204 modalidades.
--
-- Serve para `resultado_campeonato.modalidade` deixar de ser texto
-- digitado à mão. Note que aquele campo continua TEXTO, não vira FK: os
-- resultados já cadastrados têm modalidade escrita por pessoa, e uma FK
-- os quebraria. A tabela alimenta a lista de sugestões da tela; quem
-- quiser digitar algo fora do catálogo continua podendo.
--
-- COM empresa_id: o catálogo vem da conta do clube no Shooting House, e
-- o grupo 1000 (modalidades criadas pelo próprio clube) prova que ele
-- não é igual para todo mundo. Mesmo critério de campeonato.
CREATE TABLE modalidade (
    modalidade_id     TEXT PRIMARY KEY,            -- MOD-000001
    empresa_id        TEXT NOT NULL,                 -- cross-db → core.empresa
    grupo_id_sh       INTEGER,                       -- id do grupo no Shooting House
    grupo             TEXT NOT NULL,                 -- 'Sem grupo' quando vem vazio
    modalidade_id_sh  INTEGER NOT NULL,
    nome              TEXT NOT NULL,
    -- Modalidade que sai do catálogo do clube vira 'Não' em vez de ser
    -- apagada: pode haver resultado antigo que a menciona, e apagar
    -- deixaria a tela sem como explicar de onde veio aquele texto.
    ativo             TEXT NOT NULL DEFAULT 'Sim',
    sincronizado_em   TEXT NOT NULL,                 -- ISO 8601
    UNIQUE (empresa_id, grupo_id_sh, modalidade_id_sh)
);

CREATE INDEX idx_modalidade_empresa_id ON modalidade(empresa_id);

-- Filiado do clube -- ESPELHO da lista do Shooting House, não cadastro
-- próprio (2026-08-25). Diferente de core.cliente em natureza, e a
-- distinção é deliberada:
--
--   core.cliente  = quem o DESPACHANTE atende. Registro nosso, criado à
--                   mão quando o primeiro caso da pessoa aparece.
--   filiado       = quem passou pelo CLUBE. Vem de
--                   GET /registers/shooters/paginate, sincronizado.
--
-- A mesma pessoa costuma ser as duas coisas, e a ligação é pelo CPF --
-- sem FK, porque são bancos diferentes (mesma regra de
-- resultado_campeonato.cliente_id). Juntar tudo numa tabela só
-- destruiria o sentido de `cliente`: o clube tem ~1450 filiados e o
-- despachante atende um subconjunto, e importar todo mundo para
-- `cliente` seria guardar dado pessoal de gente que ninguém atende.
--
-- Por que fica no Domínio e não no Core: "filiado de clube de tiro" é
-- vocabulário deste domínio. Um escritório de advocacia nunca terá um.
-- Mesmo critério que manteve campeonato aqui.
--
-- ATENÇÃO ao ler esta tabela: como é banco anexado, ela NÃO passa pelas
-- views do Core que se filtram sozinhas. Todo WHERE precisa de
-- empresa_id escrito à mão.
CREATE TABLE filiado (
    filiado_id           TEXT PRIMARY KEY,             -- FIL-000001
    empresa_id           TEXT NOT NULL,                  -- cross-db → core.empresa
    idatirador           INTEGER,                        -- id interno do Shooting House
    matricula            TEXT,                           -- registratitionCode ("F101")
    nome                 TEXT NOT NULL,
    cpf                  TEXT NOT NULL,                  -- só dígitos -- é a chave de ligação com core.cliente
    email                TEXT,
    status_filiacao      TEXT,                           -- 'Ativo' | 'Inativo' (status A/I da API)

    -- ---- retrato da habitualidade, NÃO a verdade sobre ela ----
    -- O Shooting House é o sistema de registro que reporta à PF e ao
    -- Exército; estes números são uma cópia guardada só para conseguir
    -- desenhar um panorama do clube inteiro sem fazer centenas de
    -- consultas a cada tela aberta.
    --
    -- Toda tela que os exibir precisa mostrar `sincronizado_em` junto, e
    -- NENHUMA afirmação a cliente pode sair daqui -- pergunta de cliente
    -- é respondida com consulta ao vivo, como já é hoje no Portal.
    --
    -- Só a CONTAGEM e a última data são guardadas, de propósito: separar
    -- treino de competição depende de confirmar o significado do campo
    -- `competicao` da API contra uma resposta real (ele vem com o texto
    -- "TREINO" num treino comum), e guardar uma classificação não
    -- conferida convidaria alguém a confiar nela.
    participacoes_12m    INTEGER,                        -- NULL = nunca sincronizado
    ultima_participacao  TEXT,                           -- ISO 8601 (YYYY-MM-DD)
    -- As DATAS das participações dentro da janela, como lista JSON
    -- (["2026-08-22", ...]). NULL = nunca sincronizado, [] = consultado
    -- e não teve.
    --
    -- Por que a lista, e não uma tabela `habitualidade_dia` com o total
    -- do clube por dia (2026-08-27): a sincronização é um RODÍZIO -- cada
    -- rodada lê ~150 dos ~978 ativos. Um total por dia gravado a cada
    -- rodada seria a soma de um pedaço do clube, e não haveria como
    -- corrigir depois sem saber de quem era cada participação. Guardando
    -- as datas na linha da pessoa, cada sincronização REESCREVE o que
    -- aquela pessoa tem, o total do dia é recalculado por cima de todo
    -- mundo, e o número se conserta sozinho conforme o rodízio avança.
    --
    -- Continua sendo retrato, não cópia do registro: só a data. Sem
    -- modalidade, sem arma, sem hora, sem local -- nada que permita
    -- remontar o que foi lançado no Shooting House, que é quem reporta à
    -- PF e ao Exército.
    participacoes_datas  TEXT,
    sincronizado_em      TEXT,                           -- ISO 8601, NULL = nunca
    sincronizacao_erro   TEXT,                           -- último motivo de falha, NULL = ok

    -- ---- vínculo e situação financeira (2026-08-27) ----
    -- Vêm todos da MESMA resposta de GET /registers/shooters/paginate,
    -- ou seja: o clube inteiro em ~40 chamadas paginadas, não numa
    -- consulta por CPF como a habitualidade. É essa diferença que faz o
    -- Financeiro poder ser sincronizado várias vezes ao dia sem peso.
    --
    -- Mesma natureza de retrato dos campos de habitualidade acima: são
    -- cópia com data, e `sincronizado_em` vale para eles também. NENHUMA
    -- afirmação a filiado sobre a anuidade dele sai daqui.
    --
    -- 'Sim'/'Não'/NULL, e o NULL importa: é "o campo não veio", não
    -- "está devendo". Acusar de inadimplente quem tem cadastro
    -- incompleto seria o pior erro possível desta tela.
    data_filiacao        TEXT,          -- ISO 8601, a data REAL de filiação
    tipo_filiado         TEXT,          -- 'F', 'C'... como a API devolve
    anuidade_em_dia      TEXT,          -- monthly.status
    anuidade_validade    TEXT,          -- monthly.expirationDate (ISO)
    financeiro_em_dia    TEXT,          -- financial.status
    cr_numero            TEXT,
    cr_validade          TEXT,          -- documents.cr.expirationDate (ISO)
    cr_em_dia            TEXT,          -- documents.cr.status
    tem_pedido_aberto    TEXT,          -- orders.status (comanda aberta)

    criado_em            TEXT NOT NULL,
    atualizado_em        TEXT NOT NULL,

    -- Mesma razão da UNIQUE composta de core.cliente: o mesmo CPF pode
    -- ser filiado de dois clubes diferentes atendidos pelo sistema.
    UNIQUE (empresa_id, cpf)
);

CREATE INDEX idx_filiado_empresa_id ON filiado(empresa_id);
CREATE INDEX idx_filiado_cpf ON filiado(cpf);
-- A sincronização varre por "quem foi sincronizado há mais tempo",
-- então este índice é o que faz uma rodada limitada ser barata.
CREATE INDEX idx_filiado_sincronizado ON filiado(empresa_id, sincronizado_em);

-- ---------------------------------------------------------------------
-- O que o despachante sabe do filiado e o Shooting House não diz
-- (2026-09-24): datas do CR, e SIGMA/acervo de cada arma. Tabelas à
-- parte de `filiado` porque aquela é espelho reescrito pela
-- sincronização -- dado digitado por gente não mora ali. O motor
-- (domain/clube_tiro/motor_anotacoes_filiado.py) também as cria sob
-- demanda, então banco em uso não precisa de migração.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS filiado_cr (
    empresa_id       TEXT NOT NULL,
    cpf              TEXT NOT NULL,
    data_expedicao   TEXT,
    data_vencimento  TEXT,
    atualizado_em    TEXT NOT NULL,
    atualizado_por   TEXT,
    PRIMARY KEY (empresa_id, cpf)
);
CREATE TABLE IF NOT EXISTS arma_anotacao (
    empresa_id       TEXT NOT NULL,
    cpf              TEXT NOT NULL,
    arma_id          TEXT NOT NULL,         -- `id` da arma no Shooting House, nunca a série
    sigma            TEXT,
    acervo           TEXT,                  -- 'Tiro' | 'Caça' | 'Coleção'
    atualizado_em    TEXT NOT NULL,
    atualizado_por   TEXT,
    PRIMARY KEY (empresa_id, cpf, arma_id)
);
