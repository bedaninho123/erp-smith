-- Views do Core — a única porta de entrada que o Motor IA (Fase 2) pode
-- usar para ler dados. Nenhum módulo de IA deve fazer "SELECT * FROM
-- cliente" direto; sempre through uma destas views.
--
-- VW_ATENDIMENTO_COMPLETO (a view "mestre" do PROJETO_1.md) fica pendente:
-- depende de conhecimento (Domínio, banco separado) e ainda vai ser
-- responsabilidade do futuro Montador de Contexto combinar Core + Domínio,
-- não uma única SQL view cruzando bancos diferentes.
-- VW_FINANCEIRO fica pendente: não existe tabela financeiro ainda.

-- Cliente + a memória vigente dele (ativo='Sim'), sem o Motor IA precisar
-- saber que memoria_ia existe como tabela separada.
CREATE VIEW VW_CLIENTE AS
SELECT
    c.cliente_id,
    c.nome,
    c.cpf,
    c.email,
    c.telefone,
    c.cidade,
    c.status,
    c.atendimento_ia,
    c.data_cadastro,
    c.ultima_interacao,
    m.memoria_id,
    m.resumo_cliente,
    m.preferencia_canal,
    m.tom_recomendado,
    m.restricoes_atendimento,
    m.informacoes_importantes
FROM cliente c
LEFT JOIN memoria_ia m ON m.cliente_id = c.cliente_id AND m.ativo = 'Sim';

-- Serviço + o texto de prazo/valor já montado a partir dos templates
-- (mostra na prática o padrão template + dado real que o Redator vai usar).
CREATE VIEW VW_SERVICO AS
SELECT
    s.service_id,
    s.service_key,
    s.nome_servico,
    s.descricao,
    s.categoria,
    s.prazo_estimado_dias,
    s.valor_referencia,
    s.documentos_obrigatorios,
    s.ativo,
    REPLACE(tp.conteudo, '{prazo_estimado_dias}', CAST(s.prazo_estimado_dias AS TEXT)) AS prazo_texto,
    REPLACE(tv.conteudo, '{valor_referencia}', printf('%.2f', s.valor_referencia)) AS valor_texto
FROM servico s
LEFT JOIN template tp ON tp.template_key = 'prazo_texto_servico'
LEFT JOIN template tv ON tv.template_key = 'valor_texto_servico';

-- Processo com tudo que a rota "Consulta Documentos/Processo" do Make
-- já usava espalhado em 3 abas diferentes, aqui numa query só.
CREATE VIEW VW_PROCESSO AS
SELECT
    p.processo_id,
    p.protocolo,
    p.status,
    p.data_abertura,
    p.prazo_estimado,
    p.proxima_acao,
    p.ultima_atualizacao,
    p.observacoes,
    c.cliente_id,
    c.nome AS cliente_nome,
    ca.caso_id,
    ca.titulo AS caso_titulo,
    ca.status AS caso_status,
    s.service_id,
    s.nome_servico,
    s.prazo_estimado_dias,
    s.valor_referencia,
    s.documentos_obrigatorios,
    u.usuario_id AS responsavel_id,
    u.nome AS responsavel_nome
FROM processo p
JOIN cliente c ON c.cliente_id = p.cliente_id
JOIN caso ca ON ca.caso_id = p.caso_id
JOIN servico s ON s.service_id = p.servico_id
LEFT JOIN usuario u ON u.usuario_id = p.responsavel_id;
