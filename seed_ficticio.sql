-- =====================================================================
--  ERP SMITH -- SEED DE DADO FICTICIO PARA TESTE
--  Gerado para o modelo descrito em ESPECIFICACAO_LOVABLE.md
-- =====================================================================
--
--  TUDO AQUI E INVENTADO. Nenhuma linha veio do banco de producao.
--  Os CPFs seguem o padrao 100.000.000-XX, que NAO e CPF valido -- e de
--  proposito: numero de CPF valido tem dono, mesmo quando voce sortear.
--  Nomes, e-mails (@example.com) e telefones sao ficticios.
--
--  COMO USAR NO SUPABASE
--  ---------------------
--  1. Rode PRIMEIRO o DDL da secao 4 da especificacao (as tabelas).
--  2. Cole este arquivo no SQL Editor do Supabase e rode.
--     O SQL Editor roda como superusuario, entao ele ATRAVESSA o RLS --
--     e por isso o seed funciona antes de existir usuario nenhum.
--  3. Crie os usuarios no Authentication > Users e ligue-os na tabela
--     `perfil` -- o bloco comentado no FIM deste arquivo explica.
--     Sem esse passo o app loga mas nao enxerga nada, porque
--     `empresa_atual()` devolve NULL.
--
--  O QUE ESTE SEED COBRE DE PROPOSITO
--  ----------------------------------
--  * DUAS empresas. A EMP-000002 existe so para voce PROVAR o isolamento:
--    logue como a EMP-000001 e confirme que nada da outra aparece.
--  * Os 8 status de Caso e as 4 prioridades, todos representados.
--  * Tarefa atrasada, para hoje, para esta semana e concluida.
--  * Checklist nos tres estados: Aprovado, Aguardando aprovacao e
--    Recusado (com motivo, que o cliente le no Portal).
--  * Dossie nos QUATRO estados de validade: vencido, vencendo (<=30d),
--    valido e SEM DATA -- este ultimo nao pode aparecer como verde.
--  * Filiado com `participacoes_12m` NULL (nunca sincronizado) ao lado de
--    filiado com 0 (consultado, nao treinou). Se a sua tela mostrar os
--    dois igual, ela esta com o defeito que a regra 7.1 descreve.
--  * Filiado com `anuidade_em_dia` NULL (campo nao veio) -- que NAO pode
--    ser exibido como inadimplente.
--  * Filiado cujo `anuidade_em_dia` DISCORDA de `anuidade_validade`,
--    que e o caso real descrito em 8.9.
--  * Recusas de acesso a dado sensivel no log, para a tela de Auditoria
--    ter o que avisar.
--
--  As datas sao RELATIVAS (now() - interval). O seed nao envelhece:
--  a tarefa atrasada continua atrasada daqui a um ano.
-- =====================================================================

begin;

-- ------------------------------------------------------------------
-- 1. EMPRESAS (a segunda existe para testar isolamento)
-- ------------------------------------------------------------------
insert into empresa
  (empresa_id, nome, dominio, ativo, criado_em)
values
  ('EMP-000001', 'Despachante Aurora (FICTICIO)', 'clube_tiro', true, now() - interval '400 days'),
  ('EMP-000002', 'Despachante Segunda Empresa (FICTICIO)', 'clube_tiro', true, now() - interval '200 days');

-- ------------------------------------------------------------------
-- 2. USUARIOS DO PAINEL
--    Nenhum tem senha aqui: no Supabase quem guarda credencial e o
--    Authentication. Ver o bloco `perfil` no fim do arquivo.
-- ------------------------------------------------------------------
insert into usuario
  (usuario_id, empresa_id, nome, email, papel, equipe, ativo, criado_em)
values
  ('USR-000001', 'EMP-000001', 'Marina Alvarenga', 'marina@example.com', 'Gestor', 'Direcao', true, now() - interval '400 days'),
  ('USR-000002', 'EMP-000001', 'Caio Bentivoglio', 'caio@example.com', 'Atendente', 'Atendimento', true, now() - interval '380 days'),
  ('USR-000003', 'EMP-000001', 'Renata Kobayashi', 'renata@example.com', 'Atendente', 'Atendimento', true, now() - interval '300 days'),
  ('USR-000004', 'EMP-000001', 'Otavio Peixoto', 'otavio@example.com', 'Atendente', 'Documentacao', false, now() - interval '350 days'),
  ('USR-000005', 'EMP-000002', 'Silvana Toledo', 'silvana@example.com', 'Gestor', 'Direcao', true, now() - interval '200 days');

-- Renata e Atendente e teve DUAS funcoes desligadas pela Gestora.
-- Lembre da regra 6.4: ausencia de linha significa PERMITIDO, entao
-- so aparece aqui o que foi explicitamente desligado.
insert into usuario_permissao
  (usuario_id, empresa_id, funcao, ativo)
values
  ('USR-000003', 'EMP-000001', 'aprovacoes_pendentes', false),
  ('USR-000003', 'EMP-000001', 'testar_pipeline', false);

-- ------------------------------------------------------------------
-- 3. CATALOGO DE SERVICOS
--    SER-000005 tem prazo e valor NULL de proposito: a tela precisa
--    escrever 'a confirmar', nunca 0 nem um numero inventado (7.1).
-- ------------------------------------------------------------------
insert into servico
  (service_id, empresa_id, service_key, nome_servico, descricao, categoria, prazo_estimado_dias, valor_referencia, documentos_obrigatorios, ativo)
values
  ('SER-000001', 'EMP-000001', 'renovacao_cr', 'Renovacao do CR', 'Renovacao do Certificado de Registro junto ao Exercito.', 'Regularizacao documental', 45, 850.0, 'RG; CPF; comprovante de residencia; certidoes; laudos; taxa.', true),
  ('SER-000002', 'EMP-000001', 'primeiro_cr', 'Primeiro CR', 'Primeira emissao do Certificado de Registro.', 'Regularizacao documental', 60, 1200.0, 'RG; CPF; comprovante; certidoes; laudos; foto; taxa.', true),
  ('SER-000003', 'EMP-000001', 'apostilamento', 'Apostilamento', 'Inclusao de arma no CR.', 'Regularizacao documental', 30, 500.0, 'Documento da arma; comprovante; documentos pessoais.', true),
  ('SER-000004', 'EMP-000001', 'transferencia_arma', 'Transferencia de arma', 'Transferencia de propriedade entre CACs.', 'Transferencia', 40, 650.0, 'Documentacao das partes e da arma.', true),
  ('SER-000005', 'EMP-000001', 'craf', 'CRAF -- registro de arma', 'Registro de arma de fogo adquirida.', 'CRAF', NULL, NULL, 'CR valido; nota fiscal ou documento de origem; taxa.', true),
  ('SER-000006', 'EMP-000001', 'guia_trafego', 'Guia de Trafego', 'Autorizacao de transporte da arma.', 'Guias', 15, 220.0, 'CR; CRAF de cada arma; requerimento com trajeto.', true),
  ('SER-000007', 'EMP-000002', 'renovacao_cr', 'Renovacao do CR', 'Renovacao do Certificado de Registro.', 'Regularizacao documental', 50, 900.0, 'Documentacao pessoal e laudos.', true),
  ('SER-000008', 'EMP-000002', 'primeiro_cr', 'Primeiro CR', 'Primeira emissao do CR.', 'Regularizacao documental', 65, 1300.0, 'Documentacao pessoal, laudos e taxa.', true);

-- ------------------------------------------------------------------
-- 4. CHECKLIST POR SERVICO (documento_exigido)
--    Note os DOIS grupos: o que se COLETA e o que so se CONFERE.
--    Sao frases de exigencia, nao nomes de arquivo -- nao confundir
--    com o catalogo de tipos do dossie (secao 5.1 da especificacao).
-- ------------------------------------------------------------------
insert into documento_exigido
  (documento_exigido_id, empresa_id, servico_id, grupo, item, ordem, ativo)
values
  ('DEX-000001', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Documento de identidade com foto (RG ou CNH) e CPF.', 1, true),
  ('DEX-000002', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Comprovante de residencia atual.', 2, true),
  ('DEX-000003', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Comprovante de ocupacao licita.', 3, true),
  ('DEX-000004', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Certidao negativa criminal da Justica Federal.', 4, true),
  ('DEX-000005', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Certidao negativa criminal da Justica Estadual.', 5, true),
  ('DEX-000006', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Certidao negativa criminal da Justica Militar.', 6, true),
  ('DEX-000007', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Certidao negativa criminal da Justica Eleitoral.', 7, true),
  ('DEX-000008', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Laudo de aptidao psicologica emitido por psicologo credenciado.', 8, true),
  ('DEX-000009', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Laudo de capacidade tecnica emitido por instrutor credenciado.', 9, true),
  ('DEX-000010', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Declaracao de habitualidade emitida pelo clube.', 10, true),
  ('DEX-000011', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Comprovante de filiacao ao clube de tiro.', 11, true),
  ('DEX-000012', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Declaracao de Seguranca do Acervo (DSA).', 12, true),
  ('DEX-000013', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Comprovante de pagamento da taxa (GRU).', 13, true),
  ('DEX-000014', 'EMP-000001', 'SER-000001', 'Documentos a coletar', 'Requerimento de renovacao preenchido e assinado.', 14, true),
  ('DEX-000015', 'EMP-000001', 'SER-000001', 'Requisitos (conferir, nao coletar)', 'CR ainda dentro da validade -- renovar antes de vencer.', 15, true),
  ('DEX-000016', 'EMP-000001', 'SER-000001', 'Requisitos (conferir, nao coletar)', 'Habitualidade minima do nivel do CR cumprida no periodo.', 16, true),
  ('DEX-000017', 'EMP-000001', 'SER-000001', 'Requisitos (conferir, nao coletar)', 'Acervo dentro do limite do nivel (1, 2 ou 3).', 17, true),
  ('DEX-000018', 'EMP-000001', 'SER-000001', 'Requisitos (conferir, nao coletar)', 'CRAFs do acervo em dia -- arma irregular trava a renovacao.', 18, true),
  ('DEX-000019', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Documento de identidade com foto (RG ou CNH) e CPF.', 1, true),
  ('DEX-000020', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Comprovante de residencia fixa atual.', 2, true),
  ('DEX-000021', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Comprovante de ocupacao licita.', 3, true),
  ('DEX-000022', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Certidao negativa criminal da Justica Federal.', 4, true),
  ('DEX-000023', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Certidao negativa criminal da Justica Estadual.', 5, true),
  ('DEX-000024', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Certidao negativa criminal da Justica Militar.', 6, true),
  ('DEX-000025', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Certidao negativa criminal da Justica Eleitoral.', 7, true),
  ('DEX-000026', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Declaracao de que nao responde a inquerito ou processo criminal.', 8, true),
  ('DEX-000027', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Laudo de aptidao psicologica.', 9, true),
  ('DEX-000028', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Laudo de capacidade tecnica.', 10, true),
  ('DEX-000029', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Comprovante de filiacao ao clube de tiro.', 11, true),
  ('DEX-000030', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Declaracao de Seguranca do Acervo (DSA).', 12, true),
  ('DEX-000031', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Comprovante de pagamento da taxa (GRU).', 13, true),
  ('DEX-000032', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Foto 3x4 recente.', 14, true),
  ('DEX-000033', 'EMP-000001', 'SER-000002', 'Documentos a coletar', 'Requerimento de registro preenchido e assinado.', 15, true),
  ('DEX-000034', 'EMP-000001', 'SER-000002', 'Requisitos (conferir, nao coletar)', 'Idade minima cumprida.', 16, true),
  ('DEX-000035', 'EMP-000001', 'SER-000002', 'Requisitos (conferir, nao coletar)', 'Nivel de CR pretendido definido.', 17, true),
  ('DEX-000036', 'EMP-000001', 'SER-000003', 'Documentos a coletar', 'CR valido do requerente.', 1, true),
  ('DEX-000037', 'EMP-000001', 'SER-000003', 'Documentos a coletar', 'Documento da arma a ser incluida.', 2, true),
  ('DEX-000038', 'EMP-000001', 'SER-000003', 'Documentos a coletar', 'Comprovante de residencia atual.', 3, true),
  ('DEX-000039', 'EMP-000001', 'SER-000003', 'Documentos a coletar', 'Comprovante de pagamento da taxa (GRU).', 4, true),
  ('DEX-000040', 'EMP-000001', 'SER-000003', 'Requisitos (conferir, nao coletar)', 'Acervo dentro do limite do nivel do CR.', 5, true),
  ('DEX-000041', 'EMP-000001', 'SER-000003', 'Requisitos (conferir, nao coletar)', 'Calibre permitido para o nivel do CR.', 6, true),
  ('DEX-000042', 'EMP-000001', 'SER-000004', 'Documentos a coletar', 'CR valido do cedente e do adquirente.', 1, true),
  ('DEX-000043', 'EMP-000001', 'SER-000004', 'Documentos a coletar', 'CRAF da arma a ser transferida.', 2, true),
  ('DEX-000044', 'EMP-000001', 'SER-000004', 'Documentos a coletar', 'Documento de identidade das duas partes.', 3, true),
  ('DEX-000045', 'EMP-000001', 'SER-000004', 'Documentos a coletar', 'Termo de transferencia assinado pelas duas partes.', 4, true),
  ('DEX-000046', 'EMP-000001', 'SER-000004', 'Documentos a coletar', 'Comprovante de pagamento da taxa (GRU).', 5, true),
  ('DEX-000047', 'EMP-000001', 'SER-000004', 'Requisitos (conferir, nao coletar)', 'Acervo do adquirente comporta mais uma arma.', 6, true),
  ('DEX-000048', 'EMP-000001', 'SER-000004', 'Requisitos (conferir, nao coletar)', 'Numero de serie confere entre CRAF e termo.', 7, true),
  ('DEX-000049', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'CR do adquirente, valido.', 1, true),
  ('DEX-000050', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'Documento de identidade com foto (RG ou CNH) e CPF.', 2, true),
  ('DEX-000051', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'Comprovante de residencia atual.', 3, true),
  ('DEX-000052', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'Autorizacao de compra que permitiu adquirir o armamento.', 4, true),
  ('DEX-000053', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'Nota fiscal da arma, com marca, modelo, calibre e numero de serie.', 5, true),
  ('DEX-000054', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'Documento de origem, quando nao houver nota fiscal.', 6, true),
  ('DEX-000055', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'Comprovante de pagamento da taxa (GRU) do registro.', 7, true),
  ('DEX-000056', 'EMP-000001', 'SER-000005', 'Documentos a coletar', 'Termo de responsabilidade assinado.', 8, true),
  ('DEX-000057', 'EMP-000001', 'SER-000005', 'Requisitos (conferir, nao coletar)', 'Acervo dentro do limite do nivel do CR.', 9, true),
  ('DEX-000058', 'EMP-000001', 'SER-000005', 'Requisitos (conferir, nao coletar)', 'Calibre permitido para o nivel do CR do adquirente.', 10, true),
  ('DEX-000059', 'EMP-000001', 'SER-000005', 'Requisitos (conferir, nao coletar)', 'Dados da arma conferem entre nota, autorizacao e requerimento.', 11, true),
  ('DEX-000060', 'EMP-000001', 'SER-000006', 'Documentos a coletar', 'CR valido.', 1, true),
  ('DEX-000061', 'EMP-000001', 'SER-000006', 'Documentos a coletar', 'CRAF valido de cada arma que vai trafegar.', 2, true),
  ('DEX-000062', 'EMP-000001', 'SER-000006', 'Documentos a coletar', 'Documento de identidade com foto (RG ou CNH) e CPF.', 3, true),
  ('DEX-000063', 'EMP-000001', 'SER-000006', 'Documentos a coletar', 'Comprovante de filiacao ao clube de tiro.', 4, true),
  ('DEX-000064', 'EMP-000001', 'SER-000006', 'Documentos a coletar', 'Declaracao de habitualidade do clube, quando for para treino.', 5, true),
  ('DEX-000065', 'EMP-000001', 'SER-000006', 'Documentos a coletar', 'Requerimento com origem, destino e periodo do transito.', 6, true),
  ('DEX-000066', 'EMP-000001', 'SER-000006', 'Documentos a coletar', 'Comprovante de inscricao no campeonato, quando for competicao.', 7, true),
  ('DEX-000067', 'EMP-000001', 'SER-000006', 'Requisitos (conferir, nao coletar)', 'Guia e POR ARMA -- conferir se todas estao no pedido.', 8, true),
  ('DEX-000068', 'EMP-000001', 'SER-000006', 'Requisitos (conferir, nao coletar)', 'Trajeto e periodo cobrem a viagem inteira, ida e volta.', 9, true),
  ('DEX-000069', 'EMP-000001', 'SER-000006', 'Requisitos (conferir, nao coletar)', 'CRAF de cada arma dentro da validade na data do transito.', 10, true),
  ('DEX-000070', 'EMP-000002', 'SER-000007', 'Documentos a coletar', 'Documento de identidade com foto e CPF.', 1, true),
  ('DEX-000071', 'EMP-000002', 'SER-000007', 'Documentos a coletar', 'Comprovante de residencia atual.', 2, true),
  ('DEX-000072', 'EMP-000002', 'SER-000007', 'Documentos a coletar', 'Laudo de aptidao psicologica.', 3, true),
  ('DEX-000073', 'EMP-000002', 'SER-000007', 'Requisitos (conferir, nao coletar)', 'CR ainda dentro da validade.', 4, true),
  ('DEX-000074', 'EMP-000002', 'SER-000008', 'Documentos a coletar', 'Documento de identidade com foto e CPF.', 1, true),
  ('DEX-000075', 'EMP-000002', 'SER-000008', 'Documentos a coletar', 'Laudo de capacidade tecnica.', 2, true),
  ('DEX-000076', 'EMP-000002', 'SER-000008', 'Requisitos (conferir, nao coletar)', 'Idade minima cumprida.', 3, true);

-- ------------------------------------------------------------------
-- 5. CONFIGURACOES
--    `revisao_humana_ativa` esta LIGADA, que e o estado seguro: toda
--    resposta da IA fica na fila de aprovacao em vez de sair sozinha.
-- ------------------------------------------------------------------
insert into configuracoes
  (config_id, empresa_id, chave, valor, categoria, descricao, ativo)
values
  ('CFG-000001', 'EMP-000001', 'nome_empresa', 'Despachante Aurora', 'empresa', 'Nome usado nas mensagens', true),
  ('CFG-000002', 'EMP-000001', 'cidade', 'Marilia', 'empresa', 'Cidade da empresa', true),
  ('CFG-000003', 'EMP-000001', 'estado', 'SP', 'empresa', 'Estado da empresa', true),
  ('CFG-000004', 'EMP-000001', 'telefone', '(14) 4002-8922', 'contato', 'Telefone principal (ficticio)', true),
  ('CFG-000005', 'EMP-000001', 'whatsapp', '(14) 4002-8922', 'contato', 'WhatsApp de atendimento (ficticio)', true),
  ('CFG-000006', 'EMP-000001', 'email_atendimento', 'atendimento@example.com', 'contato', 'E-mail de atendimento', true),
  ('CFG-000007', 'EMP-000001', 'site', 'www.example.com', 'contato', 'Site oficial', true),
  ('CFG-000008', 'EMP-000001', 'horario_semana', 'Segunda a sexta, das 9h as 18h', 'atendimento', 'Horario semanal', true),
  ('CFG-000009', 'EMP-000001', 'horario_sabado', 'Sabado, das 9h as 13h', 'atendimento', 'Horario de sabado', true),
  ('CFG-000010', 'EMP-000001', 'horario_domingo', 'Fechado', 'atendimento', 'Horario de domingo', true),
  ('CFG-000011', 'EMP-000001', 'prazo_resposta_humano', 'Em ate 1 dia util', 'atendimento', 'Prazo de resposta humana', true),
  ('CFG-000012', 'EMP-000001', 'revisao_humana_ativa', 'Sim', 'atendimento', 'Enquanto ''Sim'', toda resposta escrita pela IA fica pendente de aprovacao humana antes de sair. Freio de seguranca da fase de validacao.', true),
  ('CFG-000013', 'EMP-000001', 'saudacao_padrao', 'Ola! Como podemos ajudar?', 'mensagens', 'Saudacao inicial', true),
  ('CFG-000014', 'EMP-000001', 'mensagem_fora_horario', 'Recebemos sua mensagem fora do horario de atendimento. Retornaremos assim que possivel.', 'mensagens', 'Resposta fora do expediente', true),
  ('CFG-000015', 'EMP-000001', 'mensagem_encaminhamento_humano', 'Sua solicitacao sera encaminhada para nossa equipe de atendimento.', 'mensagens', 'Aviso de transferencia', true),
  ('CFG-000016', 'EMP-000001', 'assinatura_email', 'Equipe Despachante Aurora', 'mensagens', 'Assinatura dos e-mails', true),
  ('CFG-000017', 'EMP-000001', 'aviso_valor', 'Os valores informados sao referencias e podem variar conforme o caso.', 'mensagens', 'Aviso usado junto aos valores', true),
  ('CFG-000018', 'EMP-000001', 'aviso_prazo', 'Os prazos informados sao estimativas e podem variar conforme a analise do orgao.', 'mensagens', 'Aviso usado junto aos prazos', true),
  ('CFG-000019', 'EMP-000001', 'mensagem_cliente_nao_encontrado', 'Nao localizamos um cadastro com esses dados. Se voce ja e nosso cliente, poderia informar seu CPF?', 'mensagens', 'Remetente nao identificado', true),
  ('CFG-000020', 'EMP-000001', 'nome_assistente', 'Assistente Virtual Aurora', 'ia', 'Nome do atendente virtual', true),
  ('CFG-000021', 'EMP-000001', 'modelo_openai', 'gpt-5-mini', 'ia', 'Modelo utilizado', true),
  ('CFG-000022', 'EMP-000001', 'temperatura_ia', '0.2', 'ia', 'Criatividade das respostas', true),
  ('CFG-000023', 'EMP-000001', 'max_tokens', '1200', 'ia', 'Maximo de tokens das respostas', true),
  ('CFG-000024', 'EMP-000001', 'idioma_resposta', 'pt-BR', 'ia', 'Idioma padrao das respostas', true),
  ('CFG-000025', 'EMP-000001', 'permitir_valores_referencia', 'Sim', 'ia', 'Permite informar valores cadastrados', true),
  ('CFG-000026', 'EMP-000001', 'permitir_prazos_referencia', 'Sim', 'ia', 'Permite informar prazos cadastrados', true),
  ('CFG-000027', 'EMP-000001', 'moeda', 'BRL', 'sistema', 'Moeda utilizada', true),
  ('CFG-000028', 'EMP-000001', 'idioma', 'pt-BR', 'sistema', 'Idioma do sistema', true),
  ('CFG-000029', 'EMP-000001', 'notificar_cliente_mudanca_status', 'Sim', 'portal', 'Cliente recebe e-mail generico, com link para o Portal, quando o status muda.', true),
  ('CFG-000030', 'EMP-000002', 'nome_empresa', 'Despachante Segunda Empresa', 'empresa', 'Nome usado nas mensagens', true),
  ('CFG-000031', 'EMP-000002', 'revisao_humana_ativa', 'Sim', 'atendimento', 'Freio de seguranca', true);

insert into template
  (template_id, empresa_id, template_key, nome, categoria, conteudo, canal, ativo)
values
  ('TPL-000001', 'EMP-000001', 'prazo_texto_servico', 'Texto de prazo', 'servico', 'Prazo medio estimado: {prazo_estimado_dias} dias.', NULL, true),
  ('TPL-000002', 'EMP-000001', 'valor_texto_servico', 'Texto de valor', 'servico', 'Valor de referencia: R$ {valor_referencia}.', NULL, true),
  ('TPL-000003', 'EMP-000001', 'saudacao_email', 'Saudacao de e-mail', 'mensagens', 'Ola, {nome_cliente}! Tudo bem?', 'Email', true);

-- ------------------------------------------------------------------
-- 6. CLIENTES DO DESPACHANTE
--    CPF ficticio: 100.000.000-XX. Nao e CPF valido, de proposito.
--    Atencao: cliente NAO e a mesma coisa que filiado do clube (secao
--    1 da especificacao). Parte destes tem CPF que tambem aparece em
--    dominio.filiado -- e assim que voce testa o cruzamento -- e parte
--    NAO tem, que e o cliente que nunca foi atirador.
-- ------------------------------------------------------------------
insert into cliente
  (cliente_id, empresa_id, nome, cpf, email, telefone, cidade, status, atendimento_ia, data_cadastro, ultima_interacao, observacoes)
values
  ('CLI-000001', 'EMP-000001', 'Roberto Almeida', '10000000001', 'roberto.1@example.com', '551499900001', 'Marilia', 'Ativo', true, now() - interval '360 days', now() - interval '1 days', NULL),
  ('CLI-000002', 'EMP-000001', 'Carla Mendes', '10000000002', 'carla.2@example.com', '551499900002', 'Bauru', 'Ativo', true, now() - interval '348 days', now() - interval '2 days', NULL),
  ('CLI-000003', 'EMP-000001', 'Eduardo Santos', '10000000003', 'eduardo.3@example.com', '551499900003', 'Assis', 'Ativo', true, now() - interval '336 days', now() - interval '3 days', NULL),
  ('CLI-000004', 'EMP-000001', 'Fernanda Lima', '10000000004', 'fernanda.4@example.com', '551499900004', 'Marilia', 'Ativo', true, now() - interval '324 days', now() - interval '4 days', NULL),
  ('CLI-000005', 'EMP-000001', 'Gustavo Pereira', '10000000005', 'gustavo.5@example.com', '551499900005', 'Ourinhos', 'Ativo', true, now() - interval '312 days', now() - interval '5 days', NULL),
  ('CLI-000006', 'EMP-000001', 'Helena Costa', '10000000006', 'helena.6@example.com', '551499900006', 'Tupa', 'Ativo', true, now() - interval '300 days', now() - interval '6 days', NULL),
  ('CLI-000007', 'EMP-000001', 'Igor Ramos', '10000000007', 'igor.7@example.com', '551499900007', 'Marilia', 'Ativo', true, now() - interval '288 days', now() - interval '7 days', NULL),
  ('CLI-000008', 'EMP-000001', 'Juliana Rocha', '10000000008', 'juliana.8@example.com', '551499900008', 'Garca', 'Ativo', true, now() - interval '276 days', now() - interval '8 days', NULL),
  ('CLI-000009', 'EMP-000001', 'Marcelo Dias', '10000000009', 'marcelo.9@example.com', '551499900009', 'Marilia', 'Inativo', false, now() - interval '264 days', now() - interval '9 days', NULL),
  ('CLI-000010', 'EMP-000001', 'Patricia Souza', '10000000010', 'patricia.10@example.com', '551499900010', 'Bauru', 'Ativo', true, now() - interval '252 days', now() - interval '10 days', NULL),
  ('CLI-000011', 'EMP-000001', 'Rafael Nunes', '10000000011', 'rafael.11@example.com', '551499900011', 'Lins', 'Ativo', true, now() - interval '240 days', now() - interval '11 days', NULL),
  ('CLI-000012', 'EMP-000001', 'Sandra Vieira', '10000000012', 'sandra.12@example.com', '551499900012', 'Assis', 'Ativo', true, now() - interval '228 days', now() - interval '12 days', NULL),
  ('CLI-000013', 'EMP-000001', 'Thiago Moreira', '10000000013', 'thiago.13@example.com', '551499900013', 'Marilia', 'Ativo', true, now() - interval '216 days', now() - interval '13 days', NULL),
  ('CLI-000014', 'EMP-000001', 'Vanessa Teixeira', '10000000014', 'vanessa.14@example.com', '551499900014', 'Ourinhos', 'Ativo', true, now() - interval '204 days', now() - interval '14 days', NULL),
  ('CLI-000015', 'EMP-000001', 'William Cardoso', '10000000015', 'william.15@example.com', '551499900015', 'Tupa', 'Ativo', true, now() - interval '192 days', now() - interval '15 days', NULL),
  ('CLI-000016', 'EMP-000001', 'Ana Beatriz Fonseca', '10000000016', 'ana.16@example.com', '551499900016', 'Garca', 'Ativo', true, now() - interval '180 days', now() - interval '16 days', NULL),
  ('CLI-000017', 'EMP-000001', 'Bruno Carvalho', '10000000017', 'bruno.17@example.com', '551499900017', 'Marilia', 'Ativo', true, now() - interval '168 days', now() - interval '17 days', NULL),
  ('CLI-000018', 'EMP-000001', 'Camila Duarte', '10000000018', 'camila.18@example.com', '551499900018', 'Bauru', 'Ativo', true, now() - interval '156 days', now() - interval '18 days', NULL),
  ('CLI-000019', 'EMP-000001', 'Diego Martins', '10000000019', 'diego.19@example.com', '551499900019', 'Lins', 'Ativo', true, now() - interval '144 days', now() - interval '19 days', NULL),
  ('CLI-000020', 'EMP-000001', 'Larissa Barbosa', '10000000020', 'larissa.20@example.com', '551499900020', 'Assis', 'Ativo', true, now() - interval '132 days', now() - interval '20 days', NULL),
  ('CLI-000021', 'EMP-000002', 'Nilton Escobar', '10000000101', 'nilton@example.com', '551899900001', 'Presidente Prudente', 'Ativo', true, now() - interval '150 days', now() - interval '2 days', 'Cliente da SEGUNDA empresa -- nao pode aparecer para a EMP-000001.'),
  ('CLI-000022', 'EMP-000002', 'Olivia Prestes', '10000000102', 'olivia@example.com', '551899900002', 'Adamantina', 'Ativo', true, now() - interval '130 days', now() - interval '3 days', 'Cliente da SEGUNDA empresa -- nao pode aparecer para a EMP-000001.'),
  ('CLI-000023', 'EMP-000002', 'Paulo Rezende', '10000000103', 'paulo@example.com', '551899900003', 'Dracena', 'Ativo', true, now() - interval '110 days', now() - interval '4 days', 'Cliente da SEGUNDA empresa -- nao pode aparecer para a EMP-000001.');

-- ------------------------------------------------------------------
-- 7. CASOS -- os 8 status e as 4 prioridades, todos representados
--    Repare nos `atualizado_em` bem antigos (CAS-000005, CAS-000011,
--    CAS-000016): sao os 'casos parados' que a tela Inicio precisa
--    pescar. Ordenada por data, a lista de Casos os esconde no fim.
-- ------------------------------------------------------------------
insert into caso
  (caso_id, empresa_id, cliente_id, titulo, descricao, categoria, tipo_caso, origem, canal_origem, status, fase, prioridade, responsavel_id, equipe_responsavel, criado_em, atualizado_em, prazo_previsto, encerrado_em, criado_por, alterado_por, versao, ativo, motivo_encerramento, observacoes)
values
  ('CAS-000001', 'EMP-000001', 'CLI-000001', 'Renovacao do CR', 'Caso ficticio para teste: renovacao do cr.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'Email', 'Em andamento', 'Documentacao', 'Normal', 'USR-000002', NULL, now() - interval '55 days', now() - interval '2 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000002', 'EMP-000001', 'CLI-000002', 'Primeiro CR', 'Caso ficticio para teste: primeiro cr.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'Email', 'Aguardando cliente', 'Documentacao', 'Normal', 'USR-000002', NULL, now() - interval '40 days', now() - interval '6 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000003', 'EMP-000001', 'CLI-000003', 'Apostilamento de arma', 'Caso ficticio para teste: apostilamento de arma.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'WhatsApp', 'Encerrado', 'Conclusao', 'Baixa', 'USR-000003', NULL, now() - interval '120 days', now() - interval '30 days', NULL, now() - interval '30 days', 'Motor IA', 'Motor IA', 1, true, 'Concluido com sucesso.', NULL),
  ('CAS-000004', 'EMP-000001', 'CLI-000004', 'Transferencia de arma', 'Caso ficticio para teste: transferencia de arma.', 'Transferencia', 'Solicitacao', 'Motor IA', 'Email', 'Em andamento', 'Execucao', 'Alta', 'USR-000003', NULL, now() - interval '35 days', now() - interval '1 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000005', 'EMP-000001', 'CLI-000005', 'Duvida sobre CRAF', 'Caso ficticio para teste: duvida sobre craf.', 'CRAF', 'Solicitacao', 'Motor IA', 'Email', 'Aberto', 'Triagem', 'Normal', NULL, NULL, now() - interval '22 days', now() - interval '22 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000006', 'EMP-000001', 'CLI-000006', 'Consulta de habitualidade', 'Caso ficticio para teste: consulta de habitualidade.', 'Habitualidade', 'Solicitacao', 'Motor IA', 'Email', 'Em triagem', 'Triagem', 'Normal', 'USR-000002', NULL, now() - interval '12 days', now() - interval '3 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000007', 'EMP-000001', 'CLI-000007', 'Reclamacao de demora', 'Caso ficticio para teste: reclamacao de demora.', 'Reclamacao', 'Solicitacao', 'Motor IA', 'Email', 'Aberto', 'Triagem', 'Urgente', 'USR-000001', NULL, now() - interval '4 days', now() - interval '1 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000008', 'EMP-000001', 'CLI-000008', 'Aquisicao de arma', 'Caso ficticio para teste: aquisicao de arma.', 'Aquisicao', 'Solicitacao', 'Motor IA', 'Portal', 'Em andamento', 'Documentacao', 'Normal', 'USR-000002', NULL, now() - interval '28 days', now() - interval '5 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000009', 'EMP-000001', 'CLI-000009', 'Renovacao do CR', 'Caso ficticio para teste: renovacao do cr.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'Email', 'Encerrado', 'Conclusao', 'Baixa', 'USR-000003', NULL, now() - interval '200 days', now() - interval '95 days', NULL, now() - interval '95 days', 'Motor IA', 'Motor IA', 1, true, 'Concluido com sucesso.', NULL),
  ('CAS-000010', 'EMP-000001', 'CLI-000010', 'Primeiro CR', 'Caso ficticio para teste: primeiro cr.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'Email', 'Aguardando cliente', 'Documentacao', 'Alta', 'USR-000002', NULL, now() - interval '45 days', now() - interval '8 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000011', 'EMP-000001', 'CLI-000011', 'Apostilamento', 'Caso ficticio para teste: apostilamento.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'Portal', 'Aberto', 'Triagem', 'Normal', NULL, NULL, now() - interval '18 days', now() - interval '18 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000012', 'EMP-000001', 'CLI-000012', 'Transferencia concluida', 'Caso ficticio para teste: transferencia concluida.', 'Transferencia', 'Solicitacao', 'Motor IA', 'Email', 'Encerrado', 'Conclusao', 'Normal', 'USR-000003', NULL, now() - interval '160 days', now() - interval '60 days', NULL, now() - interval '60 days', 'Motor IA', 'Motor IA', 1, true, 'Concluido com sucesso.', NULL),
  ('CAS-000013', 'EMP-000001', 'CLI-000013', 'Duvida sobre registro de arma', 'Caso ficticio para teste: duvida sobre registro de arma.', 'CRAF', 'Solicitacao', 'Motor IA', 'WhatsApp', 'Em triagem', 'Triagem', 'Normal', 'USR-000003', NULL, now() - interval '9 days', now() - interval '2 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000014', 'EMP-000001', 'CLI-000014', 'Consulta de habitualidade', 'Caso ficticio para teste: consulta de habitualidade.', 'Habitualidade', 'Solicitacao', 'Motor IA', 'Email', 'Aberto', 'Triagem', 'Normal', NULL, NULL, now() - interval '6 days', now() - interval '6 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000015', 'EMP-000001', 'CLI-000015', 'Habitualidade em atraso', 'Caso ficticio para teste: habitualidade em atraso.', 'Habitualidade', 'Solicitacao', 'Motor IA', 'Email', 'Aguardando terceiro', 'Acompanhamento', 'Alta', 'USR-000002', NULL, now() - interval '30 days', now() - interval '4 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000016', 'EMP-000001', 'CLI-000016', 'Primeiro CR cancelado', 'Caso ficticio para teste: primeiro cr cancelado.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'Email', 'Cancelado', 'Conclusao', 'Baixa', 'USR-000003', NULL, now() - interval '90 days', now() - interval '75 days', NULL, NULL, 'Motor IA', 'Motor IA', 1, true, 'Cliente desistiu.', NULL),
  ('CAS-000017', 'EMP-000001', 'CLI-000017', 'Renovacao suspensa', 'Caso ficticio para teste: renovacao suspensa.', 'Regularizacao documental', 'Solicitacao', 'Motor IA', 'Email', 'Suspenso', 'Acompanhamento', 'Normal', 'USR-000002', NULL, now() - interval '70 days', now() - interval '25 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000018', 'EMP-000001', 'CLI-000018', 'Aquisicao iniciada', 'Caso ficticio para teste: aquisicao iniciada.', 'Aquisicao', 'Solicitacao', 'Motor IA', 'Email', 'Aberto', 'Triagem', 'Normal', NULL, NULL, now() - interval '3 days', now() - interval '3 days', current_date + 30, NULL, 'Motor IA', 'Motor IA', 1, true, NULL, NULL),
  ('CAS-000019', 'EMP-000001', 'CLI-000019', 'Guia de trafego para campeonato', 'Caso ficticio para teste: guia de trafego para campeonato.', 'Guias', 'Solicitacao', 'Painel', 'Telefone', 'Em andamento', 'Execucao', 'Urgente', 'USR-000003', NULL, now() - interval '10 days', now(), current_date + 30, NULL, 'Marina Alvarenga', 'Marina Alvarenga', 1, true, NULL, NULL),
  ('CAS-000020', 'EMP-000001', 'CLI-000020', 'Transferencia -- aguardando cedente', 'Caso ficticio para teste: transferencia -- aguardando cedente.', 'Transferencia', 'Solicitacao', 'Painel', 'Presencial', 'Aguardando cliente', 'Documentacao', 'Normal', 'USR-000002', NULL, now() - interval '20 days', now() - interval '7 days', current_date + 30, NULL, 'Marina Alvarenga', 'Marina Alvarenga', 1, true, NULL, NULL),
  ('CAS-000021', 'EMP-000002', 'CLI-000021', 'Renovacao do CR', 'Caso da SEGUNDA empresa.', 'Regularizacao documental', 'Solicitacao', 'Painel', 'Email', 'Em andamento', 'Documentacao', 'Normal', 'USR-000005', NULL, now() - interval '30 days', now() - interval '2 days', current_date + 45, NULL, 'Silvana Toledo', 'Silvana Toledo', 1, true, NULL, 'NAO pode aparecer para quem logou na EMP-000001.'),
  ('CAS-000022', 'EMP-000002', 'CLI-000022', 'Renovacao do CR', 'Caso da SEGUNDA empresa.', 'Regularizacao documental', 'Solicitacao', 'Painel', 'Email', 'Em andamento', 'Documentacao', 'Normal', 'USR-000005', NULL, now() - interval '35 days', now() - interval '2 days', current_date + 45, NULL, 'Silvana Toledo', 'Silvana Toledo', 1, true, NULL, 'NAO pode aparecer para quem logou na EMP-000001.'),
  ('CAS-000023', 'EMP-000002', 'CLI-000023', 'Renovacao do CR', 'Caso da SEGUNDA empresa.', 'Regularizacao documental', 'Solicitacao', 'Painel', 'Email', 'Em andamento', 'Documentacao', 'Normal', 'USR-000005', NULL, now() - interval '40 days', now() - interval '2 days', current_date + 45, NULL, 'Silvana Toledo', 'Silvana Toledo', 1, true, NULL, 'NAO pode aparecer para quem logou na EMP-000001.');

-- Processos. `proxima_acao` e o ESTADO perante o orgao, nao uma tarefa
-- (regra 7.5). O mesmo processo abaixo tem tarefas separadas na secao 9.
insert into processo
  (processo_id, empresa_id, caso_id, cliente_id, servico_id, protocolo, status, data_abertura, prazo_estimado, proxima_acao, responsavel_id, ultima_atualizacao, observacoes)
values
  ('PRO-000001', 'EMP-000001', 'CAS-000001', 'CLI-000001', 'SER-000001', '2026000001', 'Em analise', current_date - 55, current_date + 5, 'Em analise no orgao.', 'USR-000002', now() - interval '2 days', NULL),
  ('PRO-000002', 'EMP-000001', 'CAS-000002', 'CLI-000002', 'SER-000002', NULL, 'Aguardando documentos', current_date - 40, current_date + 20, 'Aguardando documento do cliente.', 'USR-000002', now() - interval '6 days', NULL),
  ('PRO-000003', 'EMP-000001', 'CAS-000003', 'CLI-000003', 'SER-000003', '2026000003', 'Concluido', current_date - 120, current_date - 60, 'Processo concluido.', 'USR-000003', now() - interval '30 days', NULL),
  ('PRO-000004', 'EMP-000001', 'CAS-000004', 'CLI-000004', 'SER-000004', '2026000004', 'Em analise', current_date - 35, current_date + 25, 'Em analise no orgao.', 'USR-000003', now() - interval '1 days', NULL),
  ('PRO-000005', 'EMP-000001', 'CAS-000008', 'CLI-000008', 'SER-000005', '2026000005', 'Em analise', current_date - 28, current_date + 32, 'Em analise no orgao.', 'USR-000002', now() - interval '5 days', NULL),
  ('PRO-000006', 'EMP-000001', 'CAS-000009', 'CLI-000009', 'SER-000001', '2026000006', 'Concluido', current_date - 200, current_date - 140, 'Processo concluido.', 'USR-000003', now() - interval '95 days', NULL),
  ('PRO-000007', 'EMP-000001', 'CAS-000010', 'CLI-000010', 'SER-000002', NULL, 'Aguardando documentos', current_date - 45, current_date + 15, 'Aguardando documento do cliente.', 'USR-000002', now() - interval '8 days', NULL),
  ('PRO-000008', 'EMP-000001', 'CAS-000011', 'CLI-000011', 'SER-000003', '2026000008', 'Em analise', current_date - 18, current_date + 42, 'Em analise no orgao.', NULL, now() - interval '18 days', NULL),
  ('PRO-000009', 'EMP-000001', 'CAS-000012', 'CLI-000012', 'SER-000004', '2026000009', 'Concluido', current_date - 160, current_date - 100, 'Processo concluido.', 'USR-000003', now() - interval '60 days', NULL),
  ('PRO-000010', 'EMP-000001', 'CAS-000017', 'CLI-000017', 'SER-000001', '2026000010', 'Suspenso', current_date - 70, current_date - 10, 'Aguardando retorno do orgao.', 'USR-000002', now() - interval '25 days', NULL),
  ('PRO-000011', 'EMP-000001', 'CAS-000019', 'CLI-000019', 'SER-000006', '2026000011', 'Em analise', current_date - 10, current_date + 50, 'Em analise no orgao.', 'USR-000003', now(), NULL),
  ('PRO-000012', 'EMP-000001', 'CAS-000020', 'CLI-000020', 'SER-000004', NULL, 'Aguardando documentos', current_date - 20, current_date + 40, 'Aguardando documento do cliente.', 'USR-000002', now() - interval '7 days', NULL);

-- ------------------------------------------------------------------
-- 8. DOCUMENTOS
--    Duas naturezas na mesma tabela, separadas pelo CHECK:
--    categoria='Caso'   -> preso a um caso/processo
--    categoria='Dossie' -> permanente da PESSOA, caso e processo NULL
-- ------------------------------------------------------------------
-- Dossie -- os quatro estados de validade que a tela precisa distinguir.
-- ATENCAO ao ultimo: data_validade NULL nao e 'valido'. Se a sua tela
-- pintar de verde, ela esta afirmando o que ninguem conferiu (7.1).
insert into documento
  (documento_id, empresa_id, cliente_id, caso_id, processo_id, categoria, tipo_documento, nome_arquivo, storage_path, status, data_envio, data_validade, revisado_por_id, observacoes, mensagem_id)
values
  ('DOC-000001', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_1.pdf', 'EMP-000001/CLI-000001/DOC-000001-documento_1.pdf', 'Recebido', now() - interval '2 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000002', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_2.pdf', 'EMP-000001/CLI-000001/DOC-000002-documento_2.pdf', 'Recebido', now() - interval '3 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000003', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_3.pdf', 'EMP-000001/CLI-000001/DOC-000003-documento_3.pdf', 'Recebido', now() - interval '4 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000004', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_4.pdf', 'EMP-000001/CLI-000001/DOC-000004-documento_4.pdf', 'Recebido', now() - interval '5 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000005', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_5.pdf', 'EMP-000001/CLI-000001/DOC-000005-documento_5.pdf', 'Recebido', now() - interval '6 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000006', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_6.pdf', 'EMP-000001/CLI-000001/DOC-000006-documento_6.pdf', 'Recebido', now() - interval '7 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000007', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_7.pdf', 'EMP-000001/CLI-000001/DOC-000007-documento_7.pdf', 'Recebido', now() - interval '8 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000008', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_8.pdf', 'EMP-000001/CLI-000001/DOC-000008-documento_8.pdf', 'Recebido', now() - interval '9 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000009', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_9.pdf', 'EMP-000001/CLI-000001/DOC-000009-documento_9.pdf', 'Recebido', now() - interval '10 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000010', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_10.pdf', 'EMP-000001/CLI-000001/DOC-000010-documento_10.pdf', 'Recebido', now() - interval '11 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000011', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_11.pdf', 'EMP-000001/CLI-000001/DOC-000011-documento_11.pdf', 'Recebido', now() - interval '12 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000012', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'PRO-000001', 'Caso', 'Documento do checklist', 'documento_12.pdf', 'EMP-000001/CLI-000001/DOC-000012-documento_12.pdf', 'Recebido', now() - interval '13 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000013', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'PRO-000002', 'Caso', 'Documento do checklist', 'documento_13.pdf', 'EMP-000001/CLI-000002/DOC-000013-documento_13.pdf', 'Recebido', now() - interval '14 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000014', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'PRO-000002', 'Caso', 'Documento do checklist', 'documento_14.pdf', 'EMP-000001/CLI-000002/DOC-000014-documento_14.pdf', 'Recebido', now() - interval '15 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000015', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'PRO-000002', 'Caso', 'Documento do checklist', 'documento_15.pdf', 'EMP-000001/CLI-000002/DOC-000015-documento_15.pdf', 'Recebido', now() - interval '16 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000016', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'PRO-000002', 'Caso', 'Documento do checklist', 'documento_16.pdf', 'EMP-000001/CLI-000002/DOC-000016-documento_16.pdf', 'Recebido', now() - interval '17 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000017', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'PRO-000002', 'Caso', 'Documento do checklist', 'documento_17.pdf', 'EMP-000001/CLI-000002/DOC-000017-documento_17.pdf', 'Recebido', now() - interval '18 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000018', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'PRO-000002', 'Caso', 'Documento do checklist', 'documento_18.pdf', 'EMP-000001/CLI-000002/DOC-000018-documento_18.pdf', 'Recebido', now() - interval '19 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000019', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'PRO-000002', 'Caso', 'Documento do checklist', 'documento_19.pdf', 'EMP-000001/CLI-000002/DOC-000019-documento_19.pdf', 'Recebido', now() - interval '20 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000020', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'PRO-000003', 'Caso', 'Documento do checklist', 'documento_20.pdf', 'EMP-000001/CLI-000003/DOC-000020-documento_20.pdf', 'Recebido', now() - interval '21 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000021', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'PRO-000003', 'Caso', 'Documento do checklist', 'documento_21.pdf', 'EMP-000001/CLI-000003/DOC-000021-documento_21.pdf', 'Recebido', now() - interval '22 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000022', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'PRO-000003', 'Caso', 'Documento do checklist', 'documento_22.pdf', 'EMP-000001/CLI-000003/DOC-000022-documento_22.pdf', 'Recebido', now() - interval '23 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000023', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'PRO-000003', 'Caso', 'Documento do checklist', 'documento_23.pdf', 'EMP-000001/CLI-000003/DOC-000023-documento_23.pdf', 'Recebido', now() - interval '24 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000024', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'PRO-000003', 'Caso', 'Documento do checklist', 'documento_24.pdf', 'EMP-000001/CLI-000003/DOC-000024-documento_24.pdf', 'Recebido', now() - interval '25 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000025', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'PRO-000003', 'Caso', 'Documento do checklist', 'documento_25.pdf', 'EMP-000001/CLI-000003/DOC-000025-documento_25.pdf', 'Recebido', now() - interval '26 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000026', 'EMP-000001', 'CLI-000004', 'CAS-000004', 'PRO-000004', 'Caso', 'Documento do checklist', 'documento_26.pdf', 'EMP-000001/CLI-000004/DOC-000026-documento_26.pdf', 'Recebido', now() - interval '27 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000027', 'EMP-000001', 'CLI-000004', 'CAS-000004', 'PRO-000004', 'Caso', 'Documento do checklist', 'documento_27.pdf', 'EMP-000001/CLI-000004/DOC-000027-documento_27.pdf', 'Recebido', now() - interval '28 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000028', 'EMP-000001', 'CLI-000004', 'CAS-000004', 'PRO-000004', 'Caso', 'Documento do checklist', 'documento_28.pdf', 'EMP-000001/CLI-000004/DOC-000028-documento_28.pdf', 'Recebido', now() - interval '29 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000029', 'EMP-000001', 'CLI-000004', 'CAS-000004', 'PRO-000004', 'Caso', 'Documento do checklist', 'documento_29.pdf', 'EMP-000001/CLI-000004/DOC-000029-documento_29.pdf', 'Recebido', now() - interval '30 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000030', 'EMP-000001', 'CLI-000004', 'CAS-000004', 'PRO-000004', 'Caso', 'Documento do checklist', 'documento_30.pdf', 'EMP-000001/CLI-000004/DOC-000030-documento_30.pdf', 'Recebido', now() - interval '31 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000031', 'EMP-000001', 'CLI-000008', 'CAS-000008', 'PRO-000005', 'Caso', 'Documento do checklist', 'documento_31.pdf', 'EMP-000001/CLI-000008/DOC-000031-documento_31.pdf', 'Recebido', now() - interval '32 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000032', 'EMP-000001', 'CLI-000008', 'CAS-000008', 'PRO-000005', 'Caso', 'Documento do checklist', 'documento_32.pdf', 'EMP-000001/CLI-000008/DOC-000032-documento_32.pdf', 'Recebido', now() - interval '33 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000033', 'EMP-000001', 'CLI-000008', 'CAS-000008', 'PRO-000005', 'Caso', 'Documento do checklist', 'documento_33.pdf', 'EMP-000001/CLI-000008/DOC-000033-documento_33.pdf', 'Recebido', now() - interval '34 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000034', 'EMP-000001', 'CLI-000008', 'CAS-000008', 'PRO-000005', 'Caso', 'Documento do checklist', 'documento_34.pdf', 'EMP-000001/CLI-000008/DOC-000034-documento_34.pdf', 'Recebido', now() - interval '35 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000035', 'EMP-000001', 'CLI-000008', 'CAS-000008', 'PRO-000005', 'Caso', 'Documento do checklist', 'documento_35.pdf', 'EMP-000001/CLI-000008/DOC-000035-documento_35.pdf', 'Recebido', now() - interval '36 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000036', 'EMP-000001', 'CLI-000008', 'CAS-000008', 'PRO-000005', 'Caso', 'Documento do checklist', 'documento_36.pdf', 'EMP-000001/CLI-000008/DOC-000036-documento_36.pdf', 'Recebido', now() - interval '37 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000037', 'EMP-000001', 'CLI-000010', 'CAS-000010', 'PRO-000007', 'Caso', 'Documento do checklist', 'documento_37.pdf', 'EMP-000001/CLI-000010/DOC-000037-documento_37.pdf', 'Recebido', now() - interval '38 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000038', 'EMP-000001', 'CLI-000010', 'CAS-000010', 'PRO-000007', 'Caso', 'Documento do checklist', 'documento_38.pdf', 'EMP-000001/CLI-000010/DOC-000038-documento_38.pdf', 'Recebido', now() - interval '39 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000039', 'EMP-000001', 'CLI-000010', 'CAS-000010', 'PRO-000007', 'Caso', 'Documento do checklist', 'documento_39.pdf', 'EMP-000001/CLI-000010/DOC-000039-documento_39.pdf', 'Recebido', now() - interval '40 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000040', 'EMP-000001', 'CLI-000010', 'CAS-000010', 'PRO-000007', 'Caso', 'Documento do checklist', 'documento_40.pdf', 'EMP-000001/CLI-000010/DOC-000040-documento_40.pdf', 'Recebido', now() - interval '1 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000041', 'EMP-000001', 'CLI-000010', 'CAS-000010', 'PRO-000007', 'Caso', 'Documento do checklist', 'documento_41.pdf', 'EMP-000001/CLI-000010/DOC-000041-documento_41.pdf', 'Recebido', now() - interval '2 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000042', 'EMP-000001', 'CLI-000010', 'CAS-000010', 'PRO-000007', 'Caso', 'Documento do checklist', 'documento_42.pdf', 'EMP-000001/CLI-000010/DOC-000042-documento_42.pdf', 'Recebido', now() - interval '3 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000043', 'EMP-000001', 'CLI-000010', 'CAS-000010', 'PRO-000007', 'Caso', 'Documento do checklist', 'documento_43.pdf', 'EMP-000001/CLI-000010/DOC-000043-documento_43.pdf', 'Recebido', now() - interval '4 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000044', 'EMP-000001', 'CLI-000019', 'CAS-000019', 'PRO-000011', 'Caso', 'Documento do checklist', 'documento_44.pdf', 'EMP-000001/CLI-000019/DOC-000044-documento_44.pdf', 'Recebido', now() - interval '5 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000045', 'EMP-000001', 'CLI-000019', 'CAS-000019', 'PRO-000011', 'Caso', 'Documento do checklist', 'documento_45.pdf', 'EMP-000001/CLI-000019/DOC-000045-documento_45.pdf', 'Recebido', now() - interval '6 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000046', 'EMP-000001', 'CLI-000019', 'CAS-000019', 'PRO-000011', 'Caso', 'Documento do checklist', 'documento_46.pdf', 'EMP-000001/CLI-000019/DOC-000046-documento_46.pdf', 'Recebido', now() - interval '7 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000047', 'EMP-000001', 'CLI-000019', 'CAS-000019', 'PRO-000011', 'Caso', 'Documento do checklist', 'documento_47.pdf', 'EMP-000001/CLI-000019/DOC-000047-documento_47.pdf', 'Recebido', now() - interval '8 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000048', 'EMP-000001', 'CLI-000019', 'CAS-000019', 'PRO-000011', 'Caso', 'Documento do checklist', 'documento_48.pdf', 'EMP-000001/CLI-000019/DOC-000048-documento_48.pdf', 'Recebido', now() - interval '9 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000049', 'EMP-000001', 'CLI-000020', 'CAS-000020', 'PRO-000012', 'Caso', 'Documento do checklist', 'documento_49.pdf', 'EMP-000001/CLI-000020/DOC-000049-documento_49.pdf', 'Recebido', now() - interval '10 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000050', 'EMP-000001', 'CLI-000020', 'CAS-000020', 'PRO-000012', 'Caso', 'Documento do checklist', 'documento_50.pdf', 'EMP-000001/CLI-000020/DOC-000050-documento_50.pdf', 'Recebido', now() - interval '11 days', NULL, NULL, 'Conferido e guardado pelo atendente.', NULL),
  ('DOC-000051', 'EMP-000001', 'CLI-000020', 'CAS-000020', 'PRO-000012', 'Caso', 'Documento do checklist', 'documento_51.pdf', 'EMP-000001/CLI-000020/DOC-000051-documento_51.pdf', 'Recebido', now() - interval '12 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000052', 'EMP-000001', 'CLI-000020', 'CAS-000020', 'PRO-000012', 'Caso', 'Documento do checklist', 'documento_52.pdf', 'EMP-000001/CLI-000020/DOC-000052-documento_52.pdf', 'Recebido', now() - interval '13 days', NULL, NULL, 'Enviado pelo cliente via Portal.', NULL),
  ('DOC-000053', 'EMP-000001', 'CLI-000001', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_53.pdf', 'EMP-000001/CLI-000001/DOC-000053-dossie_53.pdf', 'Guardado', now() - interval '63 days', current_date + 700, 'USR-000002', NULL, NULL),
  ('DOC-000054', 'EMP-000001', 'CLI-000001', NULL, NULL, 'Dossiê', 'CRAF -- Certificado de Registro de Arma de Fogo', 'dossie_54.pdf', 'EMP-000001/CLI-000001/DOC-000054-dossie_54.pdf', 'Guardado', now() - interval '64 days', current_date + 500, 'USR-000002', 'Pistola Taurus TH9 -- serie FICTICIA-001', NULL),
  ('DOC-000055', 'EMP-000001', 'CLI-000001', NULL, NULL, 'Dossiê', 'CRAF -- Certificado de Registro de Arma de Fogo', 'dossie_55.pdf', 'EMP-000001/CLI-000001/DOC-000055-dossie_55.pdf', 'Guardado', now() - interval '65 days', current_date + 320, 'USR-000002', 'Revolver Taurus RT85 -- serie FICTICIA-002', NULL),
  ('DOC-000056', 'EMP-000001', 'CLI-000001', NULL, NULL, 'Dossiê', 'Certidao negativa -- Justica Federal', 'dossie_56.pdf', 'EMP-000001/CLI-000001/DOC-000056-dossie_56.pdf', 'Guardado', now() - interval '66 days', current_date - 12, 'USR-000002', NULL, NULL),
  ('DOC-000057', 'EMP-000001', 'CLI-000001', NULL, NULL, 'Dossiê', 'Certidao negativa -- Justica Estadual', 'dossie_57.pdf', 'EMP-000001/CLI-000001/DOC-000057-dossie_57.pdf', 'Guardado', now() - interval '67 days', current_date + 18, 'USR-000002', NULL, NULL),
  ('DOC-000058', 'EMP-000001', 'CLI-000001', NULL, NULL, 'Dossiê', 'Laudo de aptidao psicologica', 'dossie_58.pdf', 'EMP-000001/CLI-000001/DOC-000058-dossie_58.pdf', 'Guardado', now() - interval '68 days', NULL, 'USR-000002', NULL, NULL),
  ('DOC-000059', 'EMP-000001', 'CLI-000002', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_59.pdf', 'EMP-000001/CLI-000002/DOC-000059-dossie_59.pdf', 'Guardado', now() - interval '69 days', current_date + 900, 'USR-000002', NULL, NULL),
  ('DOC-000060', 'EMP-000001', 'CLI-000002', NULL, NULL, 'Dossiê', 'Comprovante de residencia', 'dossie_60.pdf', 'EMP-000001/CLI-000002/DOC-000060-dossie_60.pdf', 'Guardado', now() - interval '70 days', current_date - 40, 'USR-000002', NULL, NULL),
  ('DOC-000061', 'EMP-000001', 'CLI-000002', NULL, NULL, 'Dossiê', 'Laudo de capacidade tecnica', 'dossie_61.pdf', 'EMP-000001/CLI-000002/DOC-000061-dossie_61.pdf', 'Guardado', now() - interval '71 days', current_date + 25, 'USR-000002', NULL, NULL),
  ('DOC-000062', 'EMP-000001', 'CLI-000004', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_62.pdf', 'EMP-000001/CLI-000004/DOC-000062-dossie_62.pdf', 'Guardado', now() - interval '72 days', current_date + 210, 'USR-000002', NULL, NULL),
  ('DOC-000063', 'EMP-000001', 'CLI-000004', NULL, NULL, 'Dossiê', 'CRAF -- Certificado de Registro de Arma de Fogo', 'dossie_63.pdf', 'EMP-000001/CLI-000004/DOC-000063-dossie_63.pdf', 'Guardado', now() - interval '73 days', current_date + 600, 'USR-000002', 'Carabina CBC 7022 -- serie FICTICIA-003', NULL),
  ('DOC-000064', 'EMP-000001', 'CLI-000004', NULL, NULL, 'Dossiê', 'Guia de Trafego', 'dossie_64.pdf', 'EMP-000001/CLI-000004/DOC-000064-dossie_64.pdf', 'Guardado', now() - interval '74 days', current_date + 8, 'USR-000002', 'Pistola Glock G17 -- serie FICTICIA-004', NULL),
  ('DOC-000065', 'EMP-000001', 'CLI-000004', NULL, NULL, 'Dossiê', 'Nota fiscal da arma', 'dossie_65.pdf', 'EMP-000001/CLI-000004/DOC-000065-dossie_65.pdf', 'Guardado', now() - interval '75 days', NULL, 'USR-000002', 'Pistola Glock G17 -- serie FICTICIA-004', NULL),
  ('DOC-000066', 'EMP-000001', 'CLI-000006', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_66.pdf', 'EMP-000001/CLI-000006/DOC-000066-dossie_66.pdf', 'Guardado', now() - interval '76 days', current_date - 95, 'USR-000002', NULL, NULL),
  ('DOC-000067', 'EMP-000001', 'CLI-000006', NULL, NULL, 'Dossiê', 'Comprovante de filiacao a clube de tiro', 'dossie_67.pdf', 'EMP-000001/CLI-000006/DOC-000067-dossie_67.pdf', 'Guardado', now() - interval '77 days', current_date + 150, 'USR-000002', NULL, NULL),
  ('DOC-000068', 'EMP-000001', 'CLI-000010', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_68.pdf', 'EMP-000001/CLI-000010/DOC-000068-dossie_68.pdf', 'Guardado', now() - interval '78 days', current_date + 400, 'USR-000002', NULL, NULL),
  ('DOC-000069', 'EMP-000001', 'CLI-000010', NULL, NULL, 'Dossiê', 'Certidao negativa -- Justica Militar', 'dossie_69.pdf', 'EMP-000001/CLI-000010/DOC-000069-dossie_69.pdf', 'Guardado', now() - interval '79 days', current_date - 5, 'USR-000002', NULL, NULL),
  ('DOC-000070', 'EMP-000001', 'CLI-000010', NULL, NULL, 'Dossiê', 'Certidao negativa -- Justica Eleitoral', 'dossie_70.pdf', 'EMP-000001/CLI-000010/DOC-000070-dossie_70.pdf', 'Guardado', now() - interval '80 days', current_date + 29, 'USR-000002', NULL, NULL),
  ('DOC-000071', 'EMP-000001', 'CLI-000013', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_71.pdf', 'EMP-000001/CLI-000013/DOC-000071-dossie_71.pdf', 'Guardado', now() - interval '81 days', NULL, 'USR-000002', NULL, NULL),
  ('DOC-000072', 'EMP-000001', 'CLI-000017', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_72.pdf', 'EMP-000001/CLI-000017/DOC-000072-dossie_72.pdf', 'Guardado', now() - interval '82 days', current_date + 60, 'USR-000002', NULL, NULL),
  ('DOC-000073', 'EMP-000001', 'CLI-000017', NULL, NULL, 'Dossiê', 'Declaracao de Seguranca do Acervo (DSA)', 'dossie_73.pdf', 'EMP-000001/CLI-000017/DOC-000073-dossie_73.pdf', 'Guardado', now() - interval '83 days', NULL, 'USR-000002', NULL, NULL),
  ('DOC-000074', 'EMP-000001', 'CLI-000019', NULL, NULL, 'Dossiê', 'CR -- Certificado de Registro', 'dossie_74.pdf', 'EMP-000001/CLI-000019/DOC-000074-dossie_74.pdf', 'Guardado', now() - interval '84 days', current_date + 330, 'USR-000002', NULL, NULL),
  ('DOC-000075', 'EMP-000001', 'CLI-000019', NULL, NULL, 'Dossiê', 'CRAF -- Certificado de Registro de Arma de Fogo', 'dossie_75.pdf', 'EMP-000001/CLI-000019/DOC-000075-dossie_75.pdf', 'Guardado', now() - interval '85 days', current_date + 480, 'USR-000002', 'Pistola IMBEL GC MD1 -- serie FICTICIA-005', NULL);

-- Checklist. Repare que 'Aguardando aprovação' NAO conta na barra X/Y
-- nem no anel de progresso (regra 7.8): contar infla o progresso com
-- trabalho que ninguem fez.
insert into documento_checklist
  (documento_checklist_id, empresa_id, processo_id, documento_exigido_id, documento_id, marcado_em, marcado_por, status, revisado_em, revisado_por, motivo_recusa)
values
  ('DCK-000001', 'EMP-000001', 'PRO-000001', 'DEX-000001', 'DOC-000001', now() - interval '2 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '1 days', 'Renata Kobayashi', NULL),
  ('DCK-000002', 'EMP-000001', 'PRO-000001', 'DEX-000002', 'DOC-000002', now() - interval '3 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '2 days', 'Renata Kobayashi', NULL),
  ('DCK-000003', 'EMP-000001', 'PRO-000001', 'DEX-000003', 'DOC-000003', now() - interval '4 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '3 days', 'Renata Kobayashi', NULL),
  ('DCK-000004', 'EMP-000001', 'PRO-000001', 'DEX-000004', 'DOC-000004', now() - interval '5 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '4 days', 'Renata Kobayashi', NULL),
  ('DCK-000005', 'EMP-000001', 'PRO-000001', 'DEX-000005', 'DOC-000005', now() - interval '6 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '5 days', 'Renata Kobayashi', NULL),
  ('DCK-000006', 'EMP-000001', 'PRO-000001', 'DEX-000006', 'DOC-000006', now() - interval '7 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '6 days', 'Renata Kobayashi', NULL),
  ('DCK-000007', 'EMP-000001', 'PRO-000001', 'DEX-000007', 'DOC-000007', now() - interval '8 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '7 days', 'Renata Kobayashi', NULL),
  ('DCK-000008', 'EMP-000001', 'PRO-000001', 'DEX-000008', 'DOC-000008', now() - interval '9 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '8 days', 'Renata Kobayashi', NULL),
  ('DCK-000009', 'EMP-000001', 'PRO-000001', 'DEX-000009', 'DOC-000009', now() - interval '10 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '9 days', 'Renata Kobayashi', NULL),
  ('DCK-000010', 'EMP-000001', 'PRO-000001', 'DEX-000010', 'DOC-000010', now() - interval '11 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000011', 'EMP-000001', 'PRO-000001', 'DEX-000011', 'DOC-000011', now() - interval '12 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000012', 'EMP-000001', 'PRO-000001', 'DEX-000012', 'DOC-000012', now() - interval '13 days', 'Cliente (Portal)', 'Recusado', now() - interval '12 days', 'Renata Kobayashi', 'Documento ilegivel -- a foto cortou o rodape. Envie novamente em PDF.'),
  ('DCK-000013', 'EMP-000001', 'PRO-000002', 'DEX-000019', 'DOC-000013', now() - interval '14 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '13 days', 'Renata Kobayashi', NULL),
  ('DCK-000014', 'EMP-000001', 'PRO-000002', 'DEX-000020', 'DOC-000014', now() - interval '15 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '14 days', 'Renata Kobayashi', NULL),
  ('DCK-000015', 'EMP-000001', 'PRO-000002', 'DEX-000021', 'DOC-000015', now() - interval '16 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '15 days', 'Renata Kobayashi', NULL),
  ('DCK-000016', 'EMP-000001', 'PRO-000002', 'DEX-000022', 'DOC-000016', now() - interval '17 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '16 days', 'Renata Kobayashi', NULL),
  ('DCK-000017', 'EMP-000001', 'PRO-000002', 'DEX-000023', 'DOC-000017', now() - interval '18 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000018', 'EMP-000001', 'PRO-000002', 'DEX-000024', 'DOC-000018', now() - interval '19 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000019', 'EMP-000001', 'PRO-000002', 'DEX-000025', 'DOC-000019', now() - interval '20 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000020', 'EMP-000001', 'PRO-000003', 'DEX-000036', 'DOC-000020', now() - interval '21 days', 'Caio Bentivoglio', 'Aprovado', now(), 'Renata Kobayashi', NULL),
  ('DCK-000021', 'EMP-000001', 'PRO-000003', 'DEX-000037', 'DOC-000021', now() - interval '22 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '1 days', 'Renata Kobayashi', NULL),
  ('DCK-000022', 'EMP-000001', 'PRO-000003', 'DEX-000038', 'DOC-000022', now() - interval '23 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '2 days', 'Renata Kobayashi', NULL),
  ('DCK-000023', 'EMP-000001', 'PRO-000003', 'DEX-000039', 'DOC-000023', now() - interval '24 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '3 days', 'Renata Kobayashi', NULL),
  ('DCK-000024', 'EMP-000001', 'PRO-000003', 'DEX-000040', 'DOC-000024', now() - interval '25 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '4 days', 'Renata Kobayashi', NULL),
  ('DCK-000025', 'EMP-000001', 'PRO-000003', 'DEX-000041', 'DOC-000025', now() - interval '26 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '5 days', 'Renata Kobayashi', NULL),
  ('DCK-000026', 'EMP-000001', 'PRO-000004', 'DEX-000042', 'DOC-000026', now() - interval '27 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '6 days', 'Renata Kobayashi', NULL),
  ('DCK-000027', 'EMP-000001', 'PRO-000004', 'DEX-000043', 'DOC-000027', now() - interval '28 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '7 days', 'Renata Kobayashi', NULL),
  ('DCK-000028', 'EMP-000001', 'PRO-000004', 'DEX-000044', 'DOC-000028', now() - interval '29 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '8 days', 'Renata Kobayashi', NULL),
  ('DCK-000029', 'EMP-000001', 'PRO-000004', 'DEX-000045', 'DOC-000029', now() - interval '30 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000030', 'EMP-000001', 'PRO-000004', 'DEX-000046', 'DOC-000030', now() - interval '31 days', 'Cliente (Portal)', 'Recusado', now() - interval '10 days', 'Renata Kobayashi', 'Certidao vencida: emitida ha mais de 90 dias. Emita uma nova.'),
  ('DCK-000031', 'EMP-000001', 'PRO-000005', 'DEX-000049', 'DOC-000031', now() - interval '32 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '11 days', 'Renata Kobayashi', NULL),
  ('DCK-000032', 'EMP-000001', 'PRO-000005', 'DEX-000050', 'DOC-000032', now() - interval '33 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '12 days', 'Renata Kobayashi', NULL),
  ('DCK-000033', 'EMP-000001', 'PRO-000005', 'DEX-000051', 'DOC-000033', now() - interval '34 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '13 days', 'Renata Kobayashi', NULL),
  ('DCK-000034', 'EMP-000001', 'PRO-000005', 'DEX-000052', 'DOC-000034', now() - interval '35 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '14 days', 'Renata Kobayashi', NULL),
  ('DCK-000035', 'EMP-000001', 'PRO-000005', 'DEX-000053', 'DOC-000035', now() - interval '36 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000036', 'EMP-000001', 'PRO-000005', 'DEX-000054', 'DOC-000036', now() - interval '37 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000037', 'EMP-000001', 'PRO-000007', 'DEX-000019', 'DOC-000037', now() - interval '38 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '17 days', 'Renata Kobayashi', NULL),
  ('DCK-000038', 'EMP-000001', 'PRO-000007', 'DEX-000020', 'DOC-000038', now() - interval '39 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '18 days', 'Renata Kobayashi', NULL),
  ('DCK-000039', 'EMP-000001', 'PRO-000007', 'DEX-000021', 'DOC-000039', now() - interval '40 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '19 days', 'Renata Kobayashi', NULL),
  ('DCK-000040', 'EMP-000001', 'PRO-000007', 'DEX-000022', 'DOC-000040', now() - interval '1 days', 'Caio Bentivoglio', 'Aprovado', now(), 'Renata Kobayashi', NULL),
  ('DCK-000041', 'EMP-000001', 'PRO-000007', 'DEX-000023', 'DOC-000041', now() - interval '2 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '1 days', 'Renata Kobayashi', NULL),
  ('DCK-000042', 'EMP-000001', 'PRO-000007', 'DEX-000024', 'DOC-000042', now() - interval '3 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000043', 'EMP-000001', 'PRO-000007', 'DEX-000025', 'DOC-000043', now() - interval '4 days', 'Cliente (Portal)', 'Recusado', now() - interval '3 days', 'Renata Kobayashi', 'O nome no comprovante nao confere com o do cadastro.'),
  ('DCK-000044', 'EMP-000001', 'PRO-000011', 'DEX-000060', 'DOC-000044', now() - interval '5 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '4 days', 'Renata Kobayashi', NULL),
  ('DCK-000045', 'EMP-000001', 'PRO-000011', 'DEX-000061', 'DOC-000045', now() - interval '6 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '5 days', 'Renata Kobayashi', NULL),
  ('DCK-000046', 'EMP-000001', 'PRO-000011', 'DEX-000062', 'DOC-000046', now() - interval '7 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '6 days', 'Renata Kobayashi', NULL),
  ('DCK-000047', 'EMP-000001', 'PRO-000011', 'DEX-000063', 'DOC-000047', now() - interval '8 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '7 days', 'Renata Kobayashi', NULL),
  ('DCK-000048', 'EMP-000001', 'PRO-000011', 'DEX-000064', 'DOC-000048', now() - interval '9 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000049', 'EMP-000001', 'PRO-000012', 'DEX-000042', 'DOC-000049', now() - interval '10 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '9 days', 'Renata Kobayashi', NULL),
  ('DCK-000050', 'EMP-000001', 'PRO-000012', 'DEX-000043', 'DOC-000050', now() - interval '11 days', 'Caio Bentivoglio', 'Aprovado', now() - interval '10 days', 'Renata Kobayashi', NULL),
  ('DCK-000051', 'EMP-000001', 'PRO-000012', 'DEX-000044', 'DOC-000051', now() - interval '12 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL),
  ('DCK-000052', 'EMP-000001', 'PRO-000012', 'DEX-000045', 'DOC-000052', now() - interval '13 days', 'Cliente (Portal)', 'Aguardando aprovação', NULL, NULL, NULL);

-- ------------------------------------------------------------------
-- 9. TAREFAS -- atrasada, hoje, esta semana, futura e concluida
--    'Atrasada' so vale para tarefa EM ABERTO (7.6): as concluidas
--    abaixo tem prazo no passado de proposito, e nao podem aparecer
--    na contagem de atrasadas.
-- ------------------------------------------------------------------
insert into tarefas
  (tarefa_id, empresa_id, caso_id, cliente_id, processo_id, tipo, descricao, responsavel_id, prazo, prioridade, status, data_conclusao, observacoes)
values
  ('TAR-000001', 'EMP-000001', 'CAS-000001', 'CLI-000001', 'PRO-000001', 'Cobrar documento', 'Cobrar a certidao da Justica Federal, que foi recusada.', 'USR-000002', current_date - 9, 'Alta', 'Pendente', NULL, NULL),
  ('TAR-000002', 'EMP-000001', 'CAS-000002', 'CLI-000002', 'PRO-000002', 'Ligar para o cliente', 'Cliente nao respondeu os dois e-mails.', 'USR-000002', current_date - 5, 'Normal', 'Pendente', NULL, NULL),
  ('TAR-000003', 'EMP-000001', 'CAS-000004', 'CLI-000004', 'PRO-000004', 'Protocolar', 'Protocolar a transferencia no sistema do Exercito.', 'USR-000003', current_date - 2, 'Urgente', 'Em andamento', NULL, NULL),
  ('TAR-000004', 'EMP-000001', 'CAS-000007', 'CLI-000007', NULL, 'Ligar para o cliente', 'Reclamacao de demora -- ligar hoje, sem falta.', 'USR-000001', current_date, 'Urgente', 'Pendente', NULL, NULL),
  ('TAR-000005', 'EMP-000001', 'CAS-000001', 'CLI-000001', 'PRO-000001', 'Conferir documento', 'Conferir os laudos que chegaram ontem.', 'USR-000003', current_date, 'Normal', 'Pendente', NULL, NULL),
  ('TAR-000006', 'EMP-000001', 'CAS-000010', 'CLI-000010', 'PRO-000007', 'Cobrar documento', 'Faltam duas certidoes negativas.', 'USR-000002', current_date + 2, 'Alta', 'Pendente', NULL, NULL),
  ('TAR-000007', 'EMP-000001', 'CAS-000008', 'CLI-000008', 'PRO-000005', 'Consultar andamento', 'Consultar o andamento no orgao.', 'USR-000002', current_date + 4, 'Normal', 'Pendente', NULL, NULL),
  ('TAR-000008', 'EMP-000001', 'CAS-000019', 'CLI-000019', 'PRO-000011', 'Protocolar', 'Guia de trafego precisa sair antes do campeonato.', 'USR-000003', current_date + 3, 'Urgente', 'Em andamento', NULL, NULL),
  ('TAR-000009', 'EMP-000001', 'CAS-000020', 'CLI-000020', 'PRO-000012', 'Ligar para o cliente', 'Confirmar se o cedente vai comparecer.', 'USR-000002', current_date + 6, 'Normal', 'Pendente', NULL, NULL),
  ('TAR-000010', 'EMP-000001', 'CAS-000017', 'CLI-000017', 'PRO-000010', 'Consultar andamento', 'Processo suspenso ha 25 dias -- cobrar o orgao.', 'USR-000002', current_date + 12, 'Normal', 'Pendente', NULL, NULL),
  ('TAR-000011', 'EMP-000001', 'CAS-000011', 'CLI-000011', 'PRO-000008', 'Agendar', 'Agendar a coleta dos documentos.', NULL, current_date + 20, 'Baixa', 'Pendente', NULL, NULL),
  ('TAR-000012', 'EMP-000001', 'CAS-000003', 'CLI-000003', 'PRO-000003', 'Protocolar', 'Apostilamento protocolado.', 'USR-000003', current_date - 35, 'Normal', 'Concluída', now() - interval '34 days', NULL),
  ('TAR-000013', 'EMP-000001', 'CAS-000003', 'CLI-000003', 'PRO-000003', 'Conferir documento', 'Conferencia final antes de encerrar.', 'USR-000003', current_date - 31, 'Normal', 'Concluída', now() - interval '30 days', NULL),
  ('TAR-000014', 'EMP-000001', 'CAS-000012', 'CLI-000012', 'PRO-000009', 'Protocolar', 'Transferencia protocolada.', 'USR-000003', current_date - 70, 'Normal', 'Concluída', now() - interval '69 days', NULL),
  ('TAR-000015', 'EMP-000001', 'CAS-000009', 'CLI-000009', 'PRO-000006', 'Consultar andamento', 'Consulta final de andamento.', 'USR-000003', current_date - 100, 'Baixa', 'Concluída', now() - interval '99 days', NULL),
  ('TAR-000016', 'EMP-000001', 'CAS-000016', 'CLI-000016', NULL, 'Ligar para o cliente', 'Cliente desistiu -- tarefa cancelada junto.', 'USR-000003', current_date - 80, 'Baixa', 'Cancelada', NULL, NULL);

-- ------------------------------------------------------------------
-- 10. ATENDIMENTOS (CRM)
--     Regra de agrupamento: UMA conversa por (cliente, canal).
--     CLI-000001 aparece DUAS vezes -- e-mail e WhatsApp sao fios
--     separados de proposito, nao um bug do seed.
--     Cada linha de `mensagem` vira ATE DUAS bolhas na tela: o que o
--     cliente escreveu e a resposta que saiu.
-- ------------------------------------------------------------------
insert into conversa
  (conversa_id, empresa_id, cliente_id, caso_id, canal, origem, status, assunto_principal, iniciada_em, ultima_mensagem_em, encerrada_em, responsavel_id, precisa_humano, total_mensagens, criado_por, atualizado_por, versao, ativo, observacoes)
values
  ('CON-000001', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'Email', 'Cliente', 'Aberta', 'Renovacao do CR', now() - interval '7 days', now() - interval '2 days', NULL, 'USR-000002', false, 2, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000002', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'WhatsApp', 'Cliente', 'Aguardando cliente', 'Envio de documento', now() - interval '6 days', now() - interval '1 days', NULL, 'USR-000002', false, 1, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000003', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'Email', 'Cliente', 'Aguardando cliente', 'Primeiro CR -- documentos', now() - interval '11 days', now() - interval '6 days', NULL, 'USR-000002', false, 1, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000004', 'EMP-000001', 'CLI-000005', 'CAS-000005', 'Email', 'Cliente', 'Aberta', 'Duvida sobre CRAF', now() - interval '27 days', now() - interval '22 days', NULL, 'USR-000002', false, 1, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000005', 'EMP-000001', 'CLI-000007', 'CAS-000007', 'Email', 'Cliente', 'Aberta', 'Reclamacao de demora', now() - interval '6 days', now() - interval '1 days', NULL, 'USR-000002', true, 1, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000006', 'EMP-000001', 'CLI-000006', 'CAS-000006', 'Email', 'Cliente', 'Aberta', 'Consulta de habitualidade', now() - interval '8 days', now() - interval '3 days', NULL, 'USR-000002', false, 1, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000007', 'EMP-000001', 'CLI-000013', 'CAS-000013', 'WhatsApp', 'Cliente', 'Aberta', 'Registro de arma', now() - interval '7 days', now() - interval '2 days', NULL, 'USR-000002', false, 1, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000008', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'Email', 'Cliente', 'Encerrada', 'Apostilamento concluido', now() - interval '35 days', now() - interval '30 days', now() - interval '30 days', 'USR-000003', false, 1, 'Motor IA', 'Motor IA', 1, true, NULL),
  ('CON-000009', 'EMP-000001', 'CLI-000012', 'CAS-000012', 'Email', 'Cliente', 'Encerrada', 'Transferencia concluida', now() - interval '65 days', now() - interval '60 days', now() - interval '60 days', 'USR-000003', false, 1, 'Motor IA', 'Motor IA', 1, true, NULL);

-- As duas mensagens com `resposta_ia` NULL e status 'Pendente de
-- aprovacao' sao a fila da tela Aprovacoes Pendentes: a IA escreveu, e
-- o freio `revisao_humana_ativa` segurou antes de sair.
insert into mensagem
  (mensagem_id, empresa_id, cliente_id, caso_id, conversa_id, processo_id, canal, data_hora, origem, email_remetente, assunto, mensagem, resposta_ia, intent, resumo_ia, precisa_humano, status_processamento, id_externo, responsavel_id, tempo_processamento_ms, modelo_ia, observacoes_ia)
values
  ('MSG-000001', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'CON-000001', NULL, 'Email', now() - interval '4 days', 'Motor IA', 'cli-000001@example.com', 'Renovacao do CR', 'Bom dia! Preciso renovar meu CR, quais documentos eu levo?', 'Bom dia! Para a renovacao do CR sao necessarios documento de identidade, comprovante de residencia, as quatro certidoes negativas, os laudos psicologico e de capacidade tecnica, a declaracao de habitualidade do clube e o comprovante da taxa. Ja abrimos seu caso.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, 'gpt-5-mini', NULL),
  ('MSG-000002', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'CON-000001', NULL, 'Email', now() - interval '3 days', 'Motor IA', 'cli-000001@example.com', 'Renovacao do CR', 'Mandei tudo por e-mail ontem, chegou?', 'Chegou sim! Nove itens ja foram conferidos e aprovados. Faltam duas certidoes, e a da Justica Federal precisou ser reenviada porque veio ilegivel.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, 'gpt-5-mini', NULL),
  ('MSG-000003', 'EMP-000001', 'CLI-000001', 'CAS-000001', 'CON-000002', NULL, 'WhatsApp', now() - interval '2 days', 'Atendente', NULL, 'Envio de documento', 'Vou mandar a foto da certidao agora', 'Perfeito, pode enviar. Assim que chegar, entra na fila de conferencia.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, NULL, NULL),
  ('MSG-000004', 'EMP-000001', 'CLI-000002', 'CAS-000002', 'CON-000003', NULL, 'Email', now() - interval '7 days', 'Motor IA', 'cli-000002@example.com', 'Primeiro CR -- documentos', 'Quais documentos faltam para o meu primeiro CR?', 'Faltam as certidoes negativas da Justica Militar e Eleitoral, e a foto 3x4.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, 'gpt-5-mini', NULL),
  ('MSG-000005', 'EMP-000001', 'CLI-000005', 'CAS-000005', 'CON-000004', NULL, 'Email', now() - interval '23 days', 'Motor IA', 'cli-000005@example.com', 'Duvida sobre CRAF', 'O que exatamente e o CRAF? E diferente do CR?', 'Sao coisas diferentes: o CR e o seu registro como colecionador, atirador ou cacador. O CRAF e o registro de CADA arma, um por arma.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, 'gpt-5-mini', NULL),
  ('MSG-000006', 'EMP-000001', 'CLI-000007', 'CAS-000007', 'CON-000005', NULL, 'Email', now() - interval '2 days', 'Cliente', 'cli-000007@example.com', 'Reclamacao de demora', 'Ja faz tres semanas e ninguem me deu retorno. Isso e normal?', NULL, 'consulta_documentos', NULL, true, 'Pendente de aprovacao', NULL, NULL, NULL, NULL, NULL),
  ('MSG-000007', 'EMP-000001', 'CLI-000006', 'CAS-000006', 'CON-000006', NULL, 'Email', now() - interval '4 days', 'Cliente', 'cli-000006@example.com', 'Consulta de habitualidade', 'Quantos treinos eu preciso fazer por ano?', NULL, 'consulta_documentos', NULL, false, 'Pendente de aprovacao', NULL, NULL, NULL, NULL, NULL),
  ('MSG-000008', 'EMP-000001', 'CLI-000013', 'CAS-000013', 'CON-000007', NULL, 'WhatsApp', now() - interval '3 days', 'Motor IA', NULL, 'Registro de arma', 'Comprei uma pistola, como faco o registro?', 'Para registrar a arma voce vai precisar do CR valido, da nota fiscal com o numero de serie, da autorizacao de compra e do comprovante da taxa.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, 'gpt-5-mini', NULL),
  ('MSG-000009', 'EMP-000001', 'CLI-000003', 'CAS-000003', 'CON-000008', NULL, 'Email', now() - interval '31 days', 'Atendente', 'cli-000003@example.com', 'Apostilamento concluido', 'O apostilamento saiu?', 'Saiu sim! O processo foi concluido e a arma ja consta no seu CR.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, NULL, NULL),
  ('MSG-000010', 'EMP-000001', 'CLI-000012', 'CAS-000012', 'CON-000009', NULL, 'Email', now() - interval '61 days', 'Atendente', 'cli-000012@example.com', 'Transferencia concluida', 'A transferencia foi finalizada?', 'Foi finalizada. A arma ja esta registrada em seu nome.', 'consulta_documentos', NULL, false, 'Processado', NULL, NULL, 1800, NULL, NULL);

insert into historico
  (historico_id, empresa_id, caso_id, tipo_evento, descricao, valor_anterior, valor_novo, criado_em, criado_por)
values
  ('HIS-000001', 'EMP-000001', 'CAS-000001', 'criacao', 'Caso criado.', NULL, 'Em andamento', now() - interval '55 days', 'Motor IA'),
  ('HIS-000002', 'EMP-000001', 'CAS-000001', 'mudanca_status', 'Status alterado.', 'Aberto', 'Em andamento', now() - interval '2 days', 'Caio Bentivoglio'),
  ('HIS-000003', 'EMP-000001', 'CAS-000002', 'criacao', 'Caso criado.', NULL, 'Aguardando cliente', now() - interval '40 days', 'Motor IA'),
  ('HIS-000004', 'EMP-000001', 'CAS-000002', 'mudanca_status', 'Status alterado.', 'Aberto', 'Aguardando cliente', now() - interval '6 days', 'Caio Bentivoglio'),
  ('HIS-000005', 'EMP-000001', 'CAS-000003', 'criacao', 'Caso criado.', NULL, 'Encerrado', now() - interval '120 days', 'Motor IA'),
  ('HIS-000006', 'EMP-000001', 'CAS-000003', 'encerramento', 'Caso encerrado.', 'Em andamento', 'Encerrado', now() - interval '30 days', 'Marina Alvarenga'),
  ('HIS-000007', 'EMP-000001', 'CAS-000004', 'criacao', 'Caso criado.', NULL, 'Em andamento', now() - interval '35 days', 'Motor IA'),
  ('HIS-000008', 'EMP-000001', 'CAS-000004', 'mudanca_status', 'Status alterado.', 'Aberto', 'Em andamento', now() - interval '1 days', 'Caio Bentivoglio'),
  ('HIS-000009', 'EMP-000001', 'CAS-000005', 'criacao', 'Caso criado.', NULL, 'Aberto', now() - interval '22 days', 'Motor IA'),
  ('HIS-000010', 'EMP-000001', 'CAS-000006', 'criacao', 'Caso criado.', NULL, 'Em triagem', now() - interval '12 days', 'Motor IA'),
  ('HIS-000011', 'EMP-000001', 'CAS-000006', 'mudanca_status', 'Status alterado.', 'Aberto', 'Em triagem', now() - interval '3 days', 'Caio Bentivoglio'),
  ('HIS-000012', 'EMP-000001', 'CAS-000007', 'criacao', 'Caso criado.', NULL, 'Aberto', now() - interval '4 days', 'Motor IA'),
  ('HIS-000013', 'EMP-000001', 'CAS-000008', 'criacao', 'Caso criado.', NULL, 'Em andamento', now() - interval '28 days', 'Motor IA'),
  ('HIS-000014', 'EMP-000001', 'CAS-000008', 'mudanca_status', 'Status alterado.', 'Aberto', 'Em andamento', now() - interval '5 days', 'Caio Bentivoglio'),
  ('HIS-000015', 'EMP-000001', 'CAS-000009', 'criacao', 'Caso criado.', NULL, 'Encerrado', now() - interval '200 days', 'Motor IA'),
  ('HIS-000016', 'EMP-000001', 'CAS-000009', 'encerramento', 'Caso encerrado.', 'Em andamento', 'Encerrado', now() - interval '95 days', 'Marina Alvarenga'),
  ('HIS-000017', 'EMP-000001', 'CAS-000010', 'criacao', 'Caso criado.', NULL, 'Aguardando cliente', now() - interval '45 days', 'Motor IA'),
  ('HIS-000018', 'EMP-000001', 'CAS-000010', 'mudanca_status', 'Status alterado.', 'Aberto', 'Aguardando cliente', now() - interval '8 days', 'Caio Bentivoglio'),
  ('HIS-000019', 'EMP-000001', 'CAS-000011', 'criacao', 'Caso criado.', NULL, 'Aberto', now() - interval '18 days', 'Motor IA'),
  ('HIS-000020', 'EMP-000001', 'CAS-000012', 'criacao', 'Caso criado.', NULL, 'Encerrado', now() - interval '160 days', 'Motor IA'),
  ('HIS-000021', 'EMP-000001', 'CAS-000012', 'encerramento', 'Caso encerrado.', 'Em andamento', 'Encerrado', now() - interval '60 days', 'Marina Alvarenga'),
  ('HIS-000022', 'EMP-000001', 'CAS-000013', 'criacao', 'Caso criado.', NULL, 'Em triagem', now() - interval '9 days', 'Motor IA'),
  ('HIS-000023', 'EMP-000001', 'CAS-000013', 'mudanca_status', 'Status alterado.', 'Aberto', 'Em triagem', now() - interval '2 days', 'Caio Bentivoglio'),
  ('HIS-000024', 'EMP-000001', 'CAS-000014', 'criacao', 'Caso criado.', NULL, 'Aberto', now() - interval '6 days', 'Motor IA'),
  ('HIS-000025', 'EMP-000001', 'CAS-000015', 'criacao', 'Caso criado.', NULL, 'Aguardando terceiro', now() - interval '30 days', 'Motor IA'),
  ('HIS-000026', 'EMP-000001', 'CAS-000015', 'mudanca_status', 'Status alterado.', 'Aberto', 'Aguardando terceiro', now() - interval '4 days', 'Caio Bentivoglio'),
  ('HIS-000027', 'EMP-000001', 'CAS-000016', 'criacao', 'Caso criado.', NULL, 'Cancelado', now() - interval '90 days', 'Motor IA'),
  ('HIS-000028', 'EMP-000001', 'CAS-000016', 'encerramento', 'Caso encerrado.', 'Em andamento', 'Cancelado', now() - interval '75 days', 'Marina Alvarenga'),
  ('HIS-000029', 'EMP-000001', 'CAS-000017', 'criacao', 'Caso criado.', NULL, 'Suspenso', now() - interval '70 days', 'Motor IA'),
  ('HIS-000030', 'EMP-000001', 'CAS-000017', 'mudanca_status', 'Status alterado.', 'Aberto', 'Suspenso', now() - interval '25 days', 'Caio Bentivoglio'),
  ('HIS-000031', 'EMP-000001', 'CAS-000018', 'criacao', 'Caso criado.', NULL, 'Aberto', now() - interval '3 days', 'Motor IA'),
  ('HIS-000032', 'EMP-000001', 'CAS-000019', 'criacao', 'Caso criado.', NULL, 'Em andamento', now() - interval '10 days', 'Marina Alvarenga'),
  ('HIS-000033', 'EMP-000001', 'CAS-000019', 'mudanca_status', 'Status alterado.', 'Aberto', 'Em andamento', now(), 'Caio Bentivoglio'),
  ('HIS-000034', 'EMP-000001', 'CAS-000020', 'criacao', 'Caso criado.', NULL, 'Aguardando cliente', now() - interval '20 days', 'Marina Alvarenga'),
  ('HIS-000035', 'EMP-000001', 'CAS-000020', 'mudanca_status', 'Status alterado.', 'Aberto', 'Aguardando cliente', now() - interval '7 days', 'Caio Bentivoglio'),
  ('HIS-000036', 'EMP-000002', 'CAS-000021', 'criacao', 'Caso criado.', NULL, 'Em andamento', now() - interval '30 days', 'Silvana Toledo'),
  ('HIS-000037', 'EMP-000002', 'CAS-000022', 'criacao', 'Caso criado.', NULL, 'Em andamento', now() - interval '35 days', 'Silvana Toledo'),
  ('HIS-000038', 'EMP-000002', 'CAS-000023', 'criacao', 'Caso criado.', NULL, 'Em andamento', now() - interval '40 days', 'Silvana Toledo');

-- ------------------------------------------------------------------
-- 11. LOGS
--     Repare nos ACESSO_DADO_SENSIVEL com valor_novo='NEGADO': tres
--     seguidos no MESMO cliente. E exatamente o padrao que a tela de
--     Auditoria (8.12) precisa avisar -- alguem tentando adivinhar o
--     CPF de outra pessoa. Um negado isolado seria so digitacao errada.
-- ------------------------------------------------------------------
insert into log_ia
  (log_id, empresa_id, caso_id, prompt_key, modelo, tokens_entrada, tokens_saida, tempo_processamento_ms, resultado, erro, criado_em)
values
  ('LOG-000001', 'EMP-000001', 'CAS-000002', 'planejador', 'gpt-5-mini', 837, 161, 960, 'Sucesso', NULL, now() - interval '2 days'),
  ('LOG-000002', 'EMP-000001', 'CAS-000003', 'consultor', 'gpt-5-mini', 874, 172, 1020, 'Sucesso', NULL, now() - interval '3 days'),
  ('LOG-000003', 'EMP-000001', 'CAS-000004', 'redator', 'gpt-5-mini', 911, 183, 1080, 'Sucesso', NULL, now() - interval '4 days'),
  ('LOG-000004', 'EMP-000001', 'CAS-000005', 'auditor', 'gpt-5-mini', 948, 194, 1140, 'Sucesso', NULL, now() - interval '5 days'),
  ('LOG-000005', 'EMP-000001', 'CAS-000006', 'classificador', 'gpt-5-mini', 985, 205, 1200, 'Sucesso', NULL, now() - interval '6 days'),
  ('LOG-000006', 'EMP-000001', 'CAS-000007', 'planejador', 'gpt-5-mini', 1022, 216, 1260, 'Sucesso', NULL, now() - interval '7 days'),
  ('LOG-000007', 'EMP-000001', 'CAS-000008', 'consultor', 'gpt-5-mini', 1059, 227, 1320, 'Sucesso', NULL, now() - interval '8 days'),
  ('LOG-000008', 'EMP-000001', 'CAS-000009', 'redator', 'gpt-5-mini', 1096, 238, 1380, 'Sucesso', NULL, now() - interval '9 days'),
  ('LOG-000009', 'EMP-000001', 'CAS-000010', 'auditor', 'gpt-5-mini', 1133, 249, 1440, 'Erro', 'Timeout ao chamar a API do modelo.', now() - interval '10 days'),
  ('LOG-000010', 'EMP-000001', 'CAS-000011', 'classificador', 'gpt-5-mini', 1170, 260, 1500, 'Sucesso', NULL, now() - interval '11 days'),
  ('LOG-000011', 'EMP-000001', 'CAS-000012', 'planejador', 'gpt-5-mini', 1207, 271, 1560, 'Sucesso', NULL, now() - interval '12 days'),
  ('LOG-000012', 'EMP-000001', 'CAS-000013', 'consultor', 'gpt-5-mini', 1244, 282, 1620, 'Sucesso', NULL, now() - interval '13 days'),
  ('LOG-000013', 'EMP-000001', 'CAS-000014', 'redator', 'gpt-5-mini', 1281, 293, 1680, 'Sucesso', NULL, now() - interval '14 days'),
  ('LOG-000014', 'EMP-000001', 'CAS-000015', 'auditor', 'gpt-5-mini', 1318, 304, 1740, 'Sucesso', NULL, now() - interval '15 days'),
  ('LOG-000015', 'EMP-000001', 'CAS-000016', 'classificador', 'gpt-5-mini', 1355, 315, 1800, 'Sucesso', NULL, now() - interval '16 days'),
  ('LOG-000016', 'EMP-000001', 'CAS-000017', 'planejador', 'gpt-5-mini', 1392, 326, 1860, 'Sucesso', NULL, now() - interval '17 days'),
  ('LOG-000017', 'EMP-000001', 'CAS-000018', 'consultor', 'gpt-5-mini', 1429, 337, 1920, 'Sucesso', NULL, now() - interval '18 days'),
  ('LOG-000018', 'EMP-000001', 'CAS-000019', 'redator', 'gpt-5-mini', 1466, 348, 1980, 'Erro', 'Timeout ao chamar a API do modelo.', now() - interval '19 days'),
  ('LOG-000019', 'EMP-000001', 'CAS-000020', 'auditor', 'gpt-5-mini', 1503, 359, 2040, 'Sucesso', NULL, now() - interval '20 days'),
  ('LOG-000020', 'EMP-000001', 'CAS-000001', 'classificador', 'gpt-5-mini', 1540, 370, 2100, 'Sucesso', NULL, now() - interval '21 days'),
  ('LOG-000021', 'EMP-000001', 'CAS-000002', 'planejador', 'gpt-5-mini', 1577, 381, 2160, 'Sucesso', NULL, now() - interval '22 days'),
  ('LOG-000022', 'EMP-000001', 'CAS-000003', 'consultor', 'gpt-5-mini', 1614, 392, 2220, 'Sucesso', NULL, now() - interval '23 days'),
  ('LOG-000023', 'EMP-000001', 'CAS-000004', 'redator', 'gpt-5-mini', 1651, 403, 2280, 'Sucesso', NULL, now() - interval '24 days'),
  ('LOG-000024', 'EMP-000001', 'CAS-000005', 'auditor', 'gpt-5-mini', 1688, 414, 2340, 'Sucesso', NULL, now() - interval '25 days'),
  ('LOG-000025', 'EMP-000001', 'CAS-000006', 'classificador', 'gpt-5-mini', 1725, 425, 2400, 'Sucesso', NULL, now() - interval '26 days'),
  ('LOG-000026', 'EMP-000001', 'CAS-000007', 'planejador', 'gpt-5-mini', 1762, 436, 2460, 'Sucesso', NULL, now() - interval '27 days'),
  ('LOG-000027', 'EMP-000001', 'CAS-000008', 'consultor', 'gpt-5-mini', 1799, 447, 2520, 'Erro', 'Timeout ao chamar a API do modelo.', now() - interval '28 days'),
  ('LOG-000028', 'EMP-000001', 'CAS-000009', 'redator', 'gpt-5-mini', 1836, 458, 2580, 'Sucesso', NULL, now() - interval '1 days'),
  ('LOG-000029', 'EMP-000001', 'CAS-000010', 'auditor', 'gpt-5-mini', 1873, 469, 2640, 'Sucesso', NULL, now() - interval '2 days'),
  ('LOG-000030', 'EMP-000001', 'CAS-000011', 'classificador', 'gpt-5-mini', 1910, 480, 2700, 'Sucesso', NULL, now() - interval '3 days');

insert into log_administrativo
  (log_administrativo_id, empresa_id, tipo_evento, alvo, descricao, valor_anterior, valor_novo, criado_em, criado_por)
values
  ('ADM-000001', 'EMP-000001', 'MUDANCA_CONFIGURACAO', 'revisao_humana_ativa', 'Freio de revisao humana religado.', 'Não', 'Sim', now() - interval '35 days', 'Marina Alvarenga'),
  ('ADM-000002', 'EMP-000001', 'MUDANCA_PAPEL', 'USR-000003', 'Papel alterado.', 'Gestor', 'Atendente', now() - interval '30 days', 'Marina Alvarenga'),
  ('ADM-000003', 'EMP-000001', 'MUDANCA_PERMISSAO', 'USR-000003', 'Funcao ''aprovacoes_pendentes'' desligada.', 'Sim', 'Não', now() - interval '30 days', 'Marina Alvarenga'),
  ('ADM-000004', 'EMP-000001', 'MUDANCA_PERMISSAO', 'USR-000003', 'Funcao ''testar_pipeline'' desligada.', 'Sim', 'Não', now() - interval '30 days', 'Marina Alvarenga'),
  ('ADM-000005', 'EMP-000001', 'MUDANCA_CONFIGURACAO', 'modelo_openai', 'Modelo alterado.', 'gpt-4o-mini', 'gpt-5-mini', now() - interval '20 days', 'Marina Alvarenga'),
  ('ADM-000006', 'EMP-000001', 'MUDANCA_PAPEL', 'USR-000004', 'Usuario desativado.', 'Sim', 'Não', now() - interval '14 days', 'Marina Alvarenga'),
  ('ADM-000007', 'EMP-000001', 'ACESSO_DADO_SENSIVEL', 'CLI-000006', 'Consulta de habitualidade liberada.', NULL, 'LIBERADO', now() - interval '3 days', 'Motor IA'),
  ('ADM-000008', 'EMP-000001', 'ACESSO_DADO_SENSIVEL', 'CLI-000014', 'Consulta de habitualidade liberada.', NULL, 'LIBERADO', now() - interval '3 days', 'Motor IA'),
  ('ADM-000009', 'EMP-000001', 'ACESSO_DADO_SENSIVEL', 'CLI-000015', 'CPF informado nao confere com o cadastro.', NULL, 'NEGADO', now() - interval '2 days', 'Motor IA'),
  ('ADM-000010', 'EMP-000001', 'ACESSO_DADO_SENSIVEL', 'CLI-000015', 'CPF informado nao confere com o cadastro.', NULL, 'NEGADO', now() - interval '2 days', 'Motor IA'),
  ('ADM-000011', 'EMP-000001', 'ACESSO_DADO_SENSIVEL', 'CLI-000015', 'CPF informado nao confere com o cadastro.', NULL, 'NEGADO', now() - interval '2 days', 'Motor IA'),
  ('ADM-000012', 'EMP-000001', 'ACESSO_DADO_SENSIVEL', 'CLI-000005', 'Identificado apenas pelo nome -- origem insuficiente.', NULL, 'NEGADO', now() - interval '1 days', 'Motor IA'),
  ('ADM-000013', 'EMP-000001', 'ACESSO_DADO_SENSIVEL', 'CLI-000001', 'Consulta de CR liberada.', NULL, 'LIBERADO', now(), 'Motor IA');

-- ==================================================================
-- SCHEMA `dominio` -- conhecimento de clube de tiro
-- ==================================================================
-- `conhecimento` NAO tem empresa_id: e legislacao federal, a mesma
-- para todo despachante. Duplicar por empresa seria manter N copias
-- da mesma lei, que divergem com o tempo.
insert into dominio.conhecimento
  (conhecimento_id, categoria, pergunta, resposta, aprovado, ativo, criado_em)
values
  ('KNW-000001', 'CR', 'O que e o CR?', 'CR e o Certificado de Registro, o documento que autoriza a pessoa a atuar como colecionador, atirador desportivo ou cacador (CAC). Ele e emitido pelo Exercito e e diferente do CRAF, que registra cada arma.', true, true, now() - interval '300 days'),
  ('KNW-000002', 'CR', 'O CR vence?', 'Pelo Decreto no 11.615/2023 o CR nao vence: ele passa por confirmacao cadastral periodica. Nao confundir confirmacao cadastral com renovacao.', true, true, now() - interval '300 days'),
  ('KNW-000003', 'CRAF', 'O que e o CRAF?', 'CRAF e o Certificado de Registro de Arma de Fogo. Existe um por arma, e acompanha a arma quando ela e transferida.', true, true, now() - interval '300 days'),
  ('KNW-000004', 'Habitualidade', 'O que conta como habitualidade?', 'Habitualidade e a comprovacao de pratica regular de tiro desportivo, registrada pelo clube. O minimo exigido depende do nivel do CR.', true, true, now() - interval '300 days'),
  ('KNW-000005', 'Habitualidade', 'Quantos treinos preciso fazer?', 'Depende do nivel do CR (art. 35 do Decreto no 11.615/2023). O sistema NAO afirma se voce cumpriu o minimo, porque nao tem acesso ao seu nivel de CR.', true, true, now() - interval '300 days'),
  ('KNW-000006', 'Transferencia', 'Como transferir uma arma?', 'A transferencia exige CR valido das duas partes, o CRAF da arma, termo assinado pelos dois e recolhimento da taxa.', true, true, now() - interval '300 days'),
  ('KNW-000007', 'Guias', 'Para que serve a Guia de Trafego?', 'A Guia de Trafego autoriza o transporte da arma entre origem e destino, num periodo determinado. Ela e POR ARMA.', true, true, now() - interval '300 days'),
  ('KNW-000008', 'Legislacao', 'Qual e a lei que rege o assunto hoje?', 'O Decreto no 11.615/2023 e a norma principal, junto das portarias do Comando do Exercito e das instrucoes da Policia Federal.', true, true, now() - interval '300 days');

-- Modalidades. O grupo de id 1000 vem com NOME VAZIO da API (e onde
-- ficam as modalidades criadas pelo proprio clube) e recebe o rotulo
-- 'Sem grupo' na leitura -- sem isso a tela mostra um cabecalho em
-- branco com itens embaixo.
insert into dominio.modalidade
  (modalidade_id, empresa_id, grupo_id_sh, grupo, modalidade_id_sh, nome, ativo, sincronizado_em)
values
  ('MOD-000001', 'EMP-000001', 1, 'Pistola', 101, 'Pistola Livre 25m', true, now() - interval '4 days'),
  ('MOD-000002', 'EMP-000001', 1, 'Pistola', 102, 'Pistola de Ar 10m', true, now() - interval '4 days'),
  ('MOD-000003', 'EMP-000001', 1, 'Pistola', 103, 'Pistola Padrao 25m', true, now() - interval '4 days'),
  ('MOD-000004', 'EMP-000001', 1, 'Pistola', 104, 'Pistola Rapida 25m', true, now() - interval '4 days'),
  ('MOD-000005', 'EMP-000001', 1, 'Pistola', 105, 'Pistola Standard', true, now() - interval '4 days'),
  ('MOD-000006', 'EMP-000001', 2, 'Revolver', 201, 'Revolver Acao Simples', true, now() - interval '4 days'),
  ('MOD-000007', 'EMP-000001', 2, 'Revolver', 202, 'Revolver Acao Dupla', true, now() - interval '4 days'),
  ('MOD-000008', 'EMP-000001', 2, 'Revolver', 203, 'Revolver 357', true, now() - interval '4 days'),
  ('MOD-000009', 'EMP-000001', 3, 'Carabina', 301, 'Carabina .22 50m', true, now() - interval '4 days'),
  ('MOD-000010', 'EMP-000001', 3, 'Carabina', 302, 'Carabina de Ar 10m', true, now() - interval '4 days'),
  ('MOD-000011', 'EMP-000001', 3, 'Carabina', 303, 'Carabina Tatica', true, now() - interval '4 days'),
  ('MOD-000012', 'EMP-000001', 4, 'Espingarda', 401, 'Trap', true, now() - interval '4 days'),
  ('MOD-000013', 'EMP-000001', 4, 'Espingarda', 402, 'Skeet', true, now() - interval '4 days'),
  ('MOD-000014', 'EMP-000001', 4, 'Espingarda', 403, 'Fossa Olimpica', true, now() - interval '4 days'),
  ('MOD-000015', 'EMP-000001', 1000, 'Sem grupo', 100001, 'Desafio Interno Aurora', true, now() - interval '4 days'),
  ('MOD-000016', 'EMP-000001', 1000, 'Sem grupo', 100002, 'Copa da Casa', true, now() - interval '4 days'),
  ('MOD-000017', 'EMP-000001', 1000, 'Sem grupo', 100003, 'Treino Livre Cronometrado', true, now() - interval '4 days');

insert into dominio.campeonato
  (campeonato_id, empresa_id, nome, data_inicio, data_fim, local, observacoes, origem, ativo, criado_em, atualizado_em)
values
  ('CAM-000001', 'EMP-000001', '1a Etapa -- Copa Aurora', current_date - 120, current_date - 120, 'Sede do clube', 'Prova ficticia para teste.', 'manual', true, now() - interval '200 days', now() - interval '30 days'),
  ('CAM-000002', 'EMP-000001', '2a Etapa -- Copa Aurora', current_date - 60, current_date - 60, 'Sede do clube', 'Prova ficticia para teste.', 'manual', true, now() - interval '200 days', now() - interval '30 days'),
  ('CAM-000003', 'EMP-000001', '3a Etapa -- Copa Aurora', current_date - 15, current_date - 15, 'Sede do clube', 'Prova ficticia para teste.', 'manual', true, now() - interval '200 days', now() - interval '30 days'),
  ('CAM-000004', 'EMP-000001', 'Torneio Regional de Inverno', current_date + 25, current_date + 26, 'Clube convidado -- Bauru', 'Prova ficticia para teste.', 'manual', true, now() - interval '200 days', now() - interval '30 days'),
  ('CAM-000005', 'EMP-000001', '4a Etapa -- Copa Aurora', current_date + 55, current_date + 55, NULL, 'Prova ficticia para teste.', 'manual', true, now() - interval '200 days', now() - interval '30 days');

-- Resultados: a tela mostra a classificacao COMPLETA da prova, nao so
-- o resultado do cliente logado. Por isso `nome_atirador` e sempre
-- preenchido e `cliente_id` e NULL para quem nao e cliente -- da para
-- destacar 'voce' sem exigir que todo participante esteja cadastrado.
insert into dominio.resultado_campeonato
  (resultado_id, empresa_id, campeonato_id, cliente_id, nome_atirador, modalidade, colocacao, pontuacao, observacoes, origem, criado_em, atualizado_em)
values
  ('RES-000001', 'EMP-000001', 'CAM-000001', 'CLI-000001', 'Roberto Almeida', 'Pistola Livre 25m', 1, '573 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000002', 'EMP-000001', 'CAM-000001', NULL, 'Adriano Petrucci', 'Pistola Livre 25m', 2, '566 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000003', 'EMP-000001', 'CAM-000001', 'CLI-000004', 'Fernanda Lima', 'Pistola Livre 25m', 3, '559 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000004', 'EMP-000001', 'CAM-000001', NULL, 'Beatriz Yamaguchi', 'Pistola Livre 25m', 4, '552 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000005', 'EMP-000001', 'CAM-000001', 'CLI-000013', 'Thiago Moreira', 'Pistola Livre 25m', 5, '545 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000006', 'EMP-000001', 'CAM-000001', NULL, 'Cesar Malaquias', 'Pistola Livre 25m', 6, '538 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000007', 'EMP-000001', 'CAM-000001', 'CLI-000019', 'Diego Martins', 'Pistola Livre 25m', 7, '531 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000008', 'EMP-000001', 'CAM-000001', NULL, 'Dora Vilanova', 'Pistola Livre 25m', 8, '524 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000009', 'EMP-000001', 'CAM-000002', 'CLI-000001', 'Roberto Almeida', 'Carabina .22 50m', 1, '573 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000010', 'EMP-000001', 'CAM-000002', NULL, 'Adriano Petrucci', 'Carabina .22 50m', 2, '566 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000011', 'EMP-000001', 'CAM-000002', 'CLI-000004', 'Fernanda Lima', 'Carabina .22 50m', 3, '559 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000012', 'EMP-000001', 'CAM-000002', NULL, 'Beatriz Yamaguchi', 'Carabina .22 50m', 4, '552 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000013', 'EMP-000001', 'CAM-000002', 'CLI-000013', 'Thiago Moreira', 'Carabina .22 50m', 5, '545 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000014', 'EMP-000001', 'CAM-000002', NULL, 'Cesar Malaquias', 'Carabina .22 50m', 6, '538 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000015', 'EMP-000001', 'CAM-000002', 'CLI-000019', 'Diego Martins', 'Carabina .22 50m', 7, '531 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000016', 'EMP-000001', 'CAM-000002', NULL, 'Dora Vilanova', 'Carabina .22 50m', 8, '524 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000017', 'EMP-000001', 'CAM-000003', 'CLI-000001', 'Roberto Almeida', 'Pistola de Ar 10m', 1, '573 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000018', 'EMP-000001', 'CAM-000003', NULL, 'Adriano Petrucci', 'Pistola de Ar 10m', 2, '566 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000019', 'EMP-000001', 'CAM-000003', 'CLI-000004', 'Fernanda Lima', 'Pistola de Ar 10m', 3, '559 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000020', 'EMP-000001', 'CAM-000003', NULL, 'Beatriz Yamaguchi', 'Pistola de Ar 10m', 4, '552 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000021', 'EMP-000001', 'CAM-000003', 'CLI-000013', 'Thiago Moreira', 'Pistola de Ar 10m', 5, '545 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000022', 'EMP-000001', 'CAM-000003', NULL, 'Cesar Malaquias', 'Pistola de Ar 10m', 6, '538 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000023', 'EMP-000001', 'CAM-000003', 'CLI-000019', 'Diego Martins', 'Pistola de Ar 10m', 7, '531 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days'),
  ('RES-000024', 'EMP-000001', 'CAM-000003', NULL, 'Dora Vilanova', 'Pistola de Ar 10m', 8, '524 pontos', NULL, 'manual', now() - interval '100 days', now() - interval '100 days');

-- ------------------------------------------------------------------
-- FILIADOS DO CLUBE -- espelho somente leitura
--
--  A TELA E OBRIGADA A MOSTRAR `sincronizado_em` junto dos numeros de
--  habitualidade. Sem isso o usuario nao sabe se esta lendo o retrato
--  de hoje ou o de tres semanas atras.
--
--  OS CASOS QUE ESTE BLOCO EXISTE PARA TESTAR:
--   * participacoes_12m = NULL  -> NUNCA sincronizado. Nao e zero.
--   * participacoes_12m = 0     -> consultado, nao treinou. E zero.
--   * anuidade_em_dia = NULL    -> o campo nao veio. NAO e devedor.
--   * anuidade_em_dia = true COM anuidade_validade vencida -> os dois
--     campos DISCORDAM, e isso acontece de verdade. A tela mostra os
--     dois estados separados e avisa que nao coincidem (8.9).
-- ------------------------------------------------------------------
insert into dominio.filiado
  (filiado_id, empresa_id, idatirador, matricula, nome, cpf, email, status_filiacao, data_filiacao, tipo_filiado, participacoes_12m, ultima_participacao, participacoes_datas, sincronizado_em, sincronizacao_erro, anuidade_em_dia, anuidade_validade, financeiro_em_dia, cr_numero, cr_validade, cr_em_dia, tem_pedido_aberto, criado_em, atualizado_em)
values
  ('FIL-000001', 'EMP-000001', 5001, 'F101', 'Roberto Almeida', '10000000001', 'filiado1@example.com', 'Ativo', current_date - 400, 'F', 22, current_date - 6, NULL, now() - interval '1 days', NULL, true, current_date + 200, true, 'CR900001', current_date + 700, true, true, now() - interval '420 days', now() - interval '1 days'),
  ('FIL-000002', 'EMP-000001', 5002, 'F102', 'Carla Mendes', '10000000002', 'filiado2@example.com', 'Ativo', current_date - 430, 'F', 8, current_date - 40, NULL, now() - interval '1 days', NULL, true, current_date + 20, true, 'CR900002', current_date + 900, true, false, now() - interval '420 days', now() - interval '1 days'),
  ('FIL-000003', 'EMP-000001', 5003, 'F103', 'Eduardo Santos', '10000000003', 'filiado3@example.com', 'Ativo', current_date - 460, 'F', 0, NULL, '[]'::jsonb, now() - interval '2 days', NULL, false, current_date - 60, false, 'CR900003', current_date + 400, true, false, now() - interval '420 days', now() - interval '2 days'),
  ('FIL-000004', 'EMP-000001', 5004, 'F104', 'Fernanda Lima', '10000000004', 'filiado4@example.com', 'Ativo', current_date - 490, 'F', 31, current_date - 3, NULL, now() - interval '1 days', NULL, true, current_date - 18, true, 'CR900004', current_date + 500, true, false, now() - interval '420 days', now() - interval '1 days'),
  ('FIL-000005', 'EMP-000001', 5005, 'F105', 'Helena Costa', '10000000006', 'filiado5@example.com', 'Ativo', current_date - 520, 'F', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, now() - interval '420 days', now() - interval '420 days'),
  ('FIL-000006', 'EMP-000001', 5006, 'F106', 'Juliana Rocha', '10000000008', 'filiado6@example.com', 'Ativo', current_date - 550, 'F', 14, current_date - 12, NULL, now() - interval '1 days', NULL, NULL, NULL, true, 'CR900006', current_date + 300, true, false, now() - interval '420 days', now() - interval '1 days'),
  ('FIL-000007', 'EMP-000001', 5007, 'F107', 'Marcelo Dias', '10000000009', 'filiado7@example.com', 'Ativo', current_date - 580, 'F', 3, current_date - 180, NULL, now() - interval '3 days', NULL, false, current_date - 200, false, 'CR900007', current_date - 95, false, true, now() - interval '420 days', now() - interval '3 days'),
  ('FIL-000008', 'EMP-000001', 5008, 'F108', 'Patricia Souza', '10000000010', 'filiado8@example.com', 'Ativo', current_date - 610, 'F', 27, current_date - 36, NULL, now() - interval '2 days', NULL, true, current_date + 117, false, 'CR900008', current_date + 390, true, false, now() - interval '420 days', now() - interval '2 days'),
  ('FIL-000009', 'EMP-000001', 5009, 'F109', 'Sandra Vieira', '10000000012', 'filiado9@example.com', 'Ativo', current_date - 640, 'F', 30, current_date - 41, NULL, now() - interval '3 days', NULL, true, current_date + 108, true, 'CR900009', current_date + 410, true, false, now() - interval '420 days', now() - interval '3 days'),
  ('FIL-000010', 'EMP-000001', 5010, 'F110', 'Thiago Moreira', '10000000013', 'filiado10@example.com', 'Ativo', current_date - 670, 'F', 7, current_date - 46, NULL, now() - interval '1 days', NULL, true, current_date + 99, true, 'CR900010', current_date + 430, true, false, now() - interval '420 days', now() - interval '1 days'),
  ('FIL-000011', 'EMP-000001', 5011, 'F111', 'Vanessa Teixeira', '10000000014', 'filiado11@example.com', 'Ativo', current_date - 700, 'F', 10, current_date - 51, NULL, now() - interval '2 days', NULL, false, current_date + 90, true, 'CR900011', current_date + 450, true, false, now() - interval '420 days', now() - interval '2 days'),
  ('FIL-000012', 'EMP-000001', 5012, 'F112', 'William Cardoso', '10000000015', 'filiado12@example.com', 'Ativo', current_date - 730, 'F', 13, current_date - 56, NULL, now() - interval '3 days', NULL, true, current_date + 81, true, 'CR900012', current_date + 470, true, false, now() - interval '420 days', now() - interval '3 days'),
  ('FIL-000013', 'EMP-000001', 5013, 'F113', 'Bruno Carvalho', '10000000017', 'filiado13@example.com', 'Ativo', current_date - 760, 'F', 16, current_date - 1, NULL, now() - interval '1 days', NULL, true, current_date + 72, true, 'CR900013', current_date + 490, true, true, now() - interval '420 days', now() - interval '1 days'),
  ('FIL-000014', 'EMP-000001', 5014, 'F114', 'Camila Duarte', '10000000018', 'filiado14@example.com', 'Ativo', current_date - 790, 'F', 19, current_date - 6, NULL, now() - interval '2 days', NULL, true, current_date + 63, true, 'CR900014', current_date + 510, true, false, now() - interval '420 days', now() - interval '2 days'),
  ('FIL-000015', 'EMP-000001', 5015, 'F115', 'Diego Martins', '10000000019', 'filiado15@example.com', 'Ativo', current_date - 820, 'F', 22, current_date - 11, NULL, now() - interval '3 days', NULL, true, current_date + 54, false, 'CR900015', current_date + 530, true, false, now() - interval '420 days', now() - interval '3 days'),
  ('FIL-000016', 'EMP-000001', 5016, 'F116', 'Larissa Barbosa', '10000000020', 'filiado16@example.com', 'Ativo', current_date - 850, 'F', 25, current_date - 16, NULL, now() - interval '1 days', NULL, false, current_date + 45, true, 'CR900016', current_date + 550, true, false, now() - interval '420 days', now() - interval '1 days'),
  ('FIL-000017', 'EMP-000001', 5017, 'F117', 'Adriano Petrucci', '10000000201', 'filiado17@example.com', 'Inativo', current_date - 200, 'F', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'CR900017', current_date + 300, false, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000018', 'EMP-000001', 5018, 'F118', 'Beatriz Yamaguchi', '10000000202', 'filiado18@example.com', 'Ativo', current_date - 225, 'F', 11, current_date - 6, NULL, now() - interval '2 days', NULL, true, current_date + 144, true, 'CR900018', current_date + 292, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000019', 'EMP-000001', 5019, 'F119', 'Cesar Malaquias', '10000000203', 'filiado19@example.com', 'Ativo', current_date - 250, 'F', 18, current_date - 10, NULL, now() - interval '3 days', NULL, true, current_date + 138, true, 'CR900019', current_date + 284, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000020', 'EMP-000001', 5020, 'F120', 'Dora Vilanova', '10000000204', 'filiado20@example.com', 'Ativo', current_date - 275, 'F', 25, current_date - 14, NULL, now() - interval '4 days', NULL, true, current_date + 132, true, 'CR900020', current_date + 276, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000021', 'EMP-000001', 5021, 'F121', 'Elias Tanaka', '10000000205', 'filiado21@example.com', 'Ativo', current_date - 300, 'F', 32, current_date - 18, NULL, now() - interval '1 days', NULL, false, current_date + 126, true, 'CR900021', current_date + 268, true, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000022', 'EMP-000001', 5022, 'F122', 'Flavia Ottoni', '10000000206', 'filiado22@example.com', 'Ativo', current_date - 325, 'F', 9, current_date - 22, NULL, now() - interval '2 days', NULL, true, current_date + 120, true, 'CR900022', current_date + 260, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000023', 'EMP-000001', 5023, 'F123', 'Gilberto Assuncao', '10000000207', 'filiado23@example.com', 'Ativo', current_date - 350, 'F', 16, current_date - 26, NULL, now() - interval '3 days', NULL, true, current_date + 114, false, 'CR900023', current_date + 252, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000024', 'EMP-000001', 5024, 'F124', 'Heloisa Bandeira', '10000000208', 'filiado24@example.com', 'Ativo', current_date - 375, 'F', 23, current_date - 30, NULL, now() - interval '4 days', 'Tempo esgotado ao consultar o CPF.', true, current_date + 108, true, 'CR900024', current_date + 244, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000025', 'EMP-000001', 5025, 'F125', 'Ivan Mesquita', '10000000209', 'filiado25@example.com', 'Ativo', current_date - 400, 'F', 30, current_date - 34, NULL, now() - interval '1 days', NULL, false, current_date + 102, true, 'CR900025', current_date + 236, false, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000026', 'EMP-000001', 5026, 'F126', 'Joana Sarmento', '10000000210', 'filiado26@example.com', 'Inativo', current_date - 425, 'F', 7, current_date - 38, NULL, now() - interval '2 days', NULL, true, current_date + 96, true, 'CR900026', current_date + 228, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000027', 'EMP-000001', 5027, 'F127', 'Kleber Antunes', '10000000211', 'filiado27@example.com', 'Ativo', current_date - 450, 'F', 14, current_date - 42, NULL, now() - interval '3 days', NULL, NULL, NULL, NULL, 'CR900027', current_date + 220, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000028', 'EMP-000001', 5028, 'F128', 'Lucia Verissimo', '10000000212', 'filiado28@example.com', 'Ativo', current_date - 475, 'F', NULL, NULL, NULL, NULL, NULL, true, current_date + 84, true, 'CR900028', current_date + 212, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000029', 'EMP-000001', 5029, 'F129', 'Mauro Guimaraes', '10000000213', 'filiado29@example.com', 'Ativo', current_date - 500, 'F', 28, current_date - 50, NULL, now() - interval '1 days', NULL, false, current_date + 78, false, 'CR900029', current_date + 204, true, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000030', 'EMP-000001', 5030, 'F130', 'Nadia Correia', '10000000214', 'filiado30@example.com', 'Ativo', current_date - 525, 'F', 0, NULL, '[]'::jsonb, now() - interval '2 days', NULL, true, current_date + 72, true, 'CR900030', current_date + 196, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000031', 'EMP-000001', 5031, 'F131', 'Otacilio Freire', '10000000215', 'filiado31@example.com', 'Ativo', current_date - 550, 'F', 12, current_date - 58, NULL, now() - interval '3 days', NULL, true, current_date + 66, true, 'CR900031', current_date + 188, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000032', 'EMP-000001', 5032, 'F132', 'Priscila Gouveia', '10000000216', 'filiado32@example.com', 'Ativo', current_date - 575, 'F', 19, current_date - 62, NULL, now() - interval '4 days', NULL, true, current_date + 60, true, 'CR900032', current_date + 180, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000033', 'EMP-000001', 5033, 'F133', 'Quiteria Bastos', '10000000217', 'filiado33@example.com', 'Ativo', current_date - 600, 'F', 26, current_date - 66, NULL, now() - interval '1 days', NULL, false, current_date + 54, true, 'CR900033', current_date + 172, false, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000034', 'EMP-000001', 5034, 'F134', 'Rodolfo Simoes', '10000000218', 'filiado34@example.com', 'Ativo', current_date - 625, 'F', 33, current_date - 70, NULL, now() - interval '2 days', NULL, true, current_date + 48, true, 'CR900034', current_date + 164, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000035', 'EMP-000001', 5035, 'F135', 'Selma Andrade', '10000000219', 'filiado35@example.com', 'Inativo', current_date - 650, 'F', 10, current_date - 4, NULL, now() - interval '3 days', NULL, true, current_date + 42, false, 'CR900035', current_date + 156, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000036', 'EMP-000001', 5036, 'F136', 'Tarcisio Lemos', '10000000220', 'filiado36@example.com', 'Ativo', current_date - 675, 'F', 17, current_date - 8, NULL, now() - interval '4 days', NULL, true, current_date + 36, true, 'CR900036', current_date + 148, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000037', 'EMP-000001', 5037, 'F137', 'Ubirajara Pinho', '10000000221', 'filiado37@example.com', 'Ativo', current_date - 700, 'F', 24, current_date - 12, NULL, now() - interval '1 days', NULL, NULL, NULL, NULL, 'CR900037', current_date + 140, true, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000038', 'EMP-000001', 5038, 'F138', 'Valeria Nogueira', '10000000222', 'filiado38@example.com', 'Ativo', current_date - 725, 'F', 31, current_date - 16, NULL, now() - interval '2 days', NULL, true, current_date + 24, true, 'CR900038', current_date + 132, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000039', 'EMP-000001', 5039, 'F139', 'Wagner Estrela', '10000000223', 'filiado39@example.com', 'Ativo', current_date - 750, 'F', NULL, NULL, NULL, NULL, NULL, true, current_date + 18, true, 'CR900039', current_date + 124, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000040', 'EMP-000001', 5040, 'F140', 'Xenia Portela', '10000000224', 'filiado40@example.com', 'Ativo', current_date - 775, 'F', 15, current_date - 24, NULL, now() - interval '4 days', NULL, true, current_date + 12, true, 'CR900040', current_date + 116, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000041', 'EMP-000001', 5041, 'F141', 'Yuri Cavalcante', '10000000225', 'filiado41@example.com', 'Ativo', current_date - 800, 'F', 22, current_date - 28, NULL, now() - interval '1 days', NULL, false, current_date + 6, false, 'CR900041', current_date + 108, false, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000042', 'EMP-000001', 5042, 'F142', 'Zilda Marcondes', '10000000226', 'filiado42@example.com', 'Ativo', current_date - 825, 'F', 29, current_date - 32, NULL, now() - interval '2 days', NULL, true, current_date, true, 'CR900042', current_date + 100, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000043', 'EMP-000001', 5043, 'F143', 'Almir Bittencourt', '10000000227', 'filiado43@example.com', 'Ativo', current_date - 850, 'F', 0, NULL, '[]'::jsonb, now() - interval '3 days', NULL, true, current_date - 6, true, 'CR900043', current_date + 92, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000044', 'EMP-000001', 5044, 'F144', 'Bianca Rezende', '10000000228', 'filiado44@example.com', 'Inativo', current_date - 875, 'F', 13, current_date - 40, NULL, now() - interval '4 days', NULL, true, current_date - 12, true, 'CR900044', current_date + 84, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000045', 'EMP-000001', 5045, 'F145', 'Caio Delgado', '10000000229', 'filiado45@example.com', 'Ativo', current_date - 900, 'F', 20, current_date - 44, NULL, now() - interval '1 days', NULL, false, current_date - 18, true, 'CR900045', current_date + 76, true, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000046', 'EMP-000001', 5046, 'F146', 'Danilo Furtado', '10000000230', 'filiado46@example.com', 'Ativo', current_date - 925, 'F', 27, current_date - 48, NULL, now() - interval '2 days', NULL, true, current_date - 24, true, 'CR900046', current_date + 68, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000047', 'EMP-000001', 5047, 'F147', 'Estela Quintana', '10000000231', 'filiado47@example.com', 'Ativo', current_date - 950, 'F', 4, current_date - 52, NULL, now() - interval '3 days', NULL, NULL, NULL, NULL, 'CR900047', current_date + 60, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000048', 'EMP-000001', 5048, 'F148', 'Fabio Loureiro', '10000000232', 'filiado48@example.com', 'Ativo', current_date - 975, 'F', 11, current_date - 56, NULL, now() - interval '4 days', NULL, true, current_date - 36, true, 'CR900048', current_date + 52, true, false, now() - interval '220 days', now() - interval '4 days'),
  ('FIL-000049', 'EMP-000001', 5049, 'F149', 'Gabriela Serpa', '10000000233', 'filiado49@example.com', 'Ativo', current_date - 1000, 'F', 18, current_date - 60, NULL, now() - interval '1 days', NULL, false, current_date - 42, true, 'CR900049', current_date + 44, false, false, now() - interval '220 days', now() - interval '1 days'),
  ('FIL-000050', 'EMP-000001', 5050, 'F150', 'Hugo Vasques', '10000000234', 'filiado50@example.com', 'Ativo', current_date - 1025, 'F', NULL, NULL, NULL, NULL, NULL, true, current_date - 48, true, 'CR900050', current_date + 36, true, false, now() - interval '220 days', now() - interval '2 days'),
  ('FIL-000051', 'EMP-000001', 5051, 'F151', 'Irene Palhares', '10000000235', 'filiado51@example.com', 'Ativo', current_date - 1050, 'F', 32, current_date - 68, NULL, now() - interval '3 days', NULL, true, current_date - 54, true, 'CR900051', current_date + 28, true, false, now() - interval '220 days', now() - interval '3 days'),
  ('FIL-000052', 'EMP-000001', 5052, 'F152', 'Joaquim Beltrao', '10000000236', 'filiado52@example.com', 'Ativo', current_date - 1075, 'F', 9, current_date - 2, NULL, now() - interval '4 days', NULL, true, current_date - 60, true, 'CR900052', current_date + 20, true, false, now() - interval '220 days', now() - interval '4 days');

-- As datas de participacao, para o grafico de habitualidade por dia.
-- Geradas por SQL a partir de `participacoes_12m` para nao virar uma
-- parede de literais aqui -- o efeito e o mesmo. Repare que quem tem
-- participacoes_12m NULL continua com participacoes_datas NULL.
update dominio.filiado f
set participacoes_datas = (
  select jsonb_agg(to_char(
           current_date - ((random() * 350)::int), 'YYYY-MM-DD'))
  from generate_series(1, f.participacoes_12m)
)
where f.participacoes_12m is not null
  and f.participacoes_12m > 0;

-- ------------------------------------------------------------------
-- 12. SEQUENCES
--     PASSO OBRIGATORIO. Este seed grava IDs explicitos, entao as
--     sequences continuam em 1 -- e o primeiro caso criado pelo app
--     tentaria nascer CAS-000001, que ja existe, e estouraria em
--     chave duplicada. Isto adianta cada uma para depois do seed.
-- ------------------------------------------------------------------
select setval('seq_cliente', 23, true);
select setval('seq_caso', 23, true);
select setval('seq_processo', 12, true);
select setval('seq_documento', 75, true);
select setval('seq_documento_checklist', 52, true);
select setval('seq_documento_exigido', 76, true);
select setval('seq_tarefa', 16, true);
select setval('seq_conversa', 9, true);
select setval('seq_mensagem', 10, true);
select setval('seq_historico', 38, true);
select setval('seq_usuario', 5, true);
select setval('seq_servico', 8, true);
select setval('seq_config', 31, true);
select setval('seq_template', 3, true);
select setval('seq_log_ia', 30, true);
select setval('seq_log_adm', 13, true);
select setval('seq_conhecimento', 8, true);
select setval('seq_modalidade', 17, true);
select setval('seq_campeonato', 5, true);
select setval('seq_resultado', 24, true);
select setval('seq_filiado', 52, true);

commit;

-- ====================================================================
-- 13. ULTIMO PASSO: LIGAR OS USUARIOS AO SUPABASE AUTH
-- ====================================================================
-- Este seed NAO cria login. Senha e credencial vivem no Authentication do
-- Supabase, nao numa tabela sua -- e SQL nenhum deveria estar criando
-- usuario de autenticacao.
--
-- Faca assim:
--
--   1. Authentication > Users > Add user. Crie estes, com a senha que
--      voce quiser (e um ambiente de teste com dado inventado):
--
--        marina@example.com    -> Gestora,   EMP-000001
--        caio@example.com      -> Atendente, EMP-000001
--        renata@example.com    -> Atendente, EMP-000001 (com 2 funcoes desligadas)
--        silvana@example.com   -> Gestora,   EMP-000002  <- para testar isolamento
--
--   2. Rode o bloco abaixo. Ele acha cada um pelo e-mail e cria a linha
--      em `perfil`, que e o que faz `empresa_atual()` devolver algo.
--
-- insert into perfil (id, empresa_id, tipo, usuario_id)
-- select u.id, x.empresa_id, 'staff', x.usuario_id
-- from auth.users u
-- join (values
--   ('marina@example.com',  'EMP-000001', 'USR-000001'),
--   ('caio@example.com',    'EMP-000001', 'USR-000002'),
--   ('renata@example.com',  'EMP-000001', 'USR-000003'),
--   ('silvana@example.com', 'EMP-000002', 'USR-000005')
-- ) as x(email, empresa_id, usuario_id) on x.email = u.email
-- on conflict (id) do nothing;
--
--   3. Para testar o PORTAL, crie um usuario com o e-mail de um cliente
--      (ex.: roberto.1@example.com) e ligue como tipo='cliente':
--
-- insert into perfil (id, empresa_id, tipo, cliente_id)
-- select u.id, 'EMP-000001', 'cliente', 'CLI-000001'
-- from auth.users u where u.email = 'roberto.1@example.com'
-- on conflict (id) do nothing;
--
-- ====================================================================
-- O TESTE QUE VALE MAIS QUE TODOS OS OUTROS
-- ====================================================================
-- Logue como silvana@example.com (EMP-000002) e abra a lista de Clientes.
-- Ela precisa mostrar TRES nomes: Nilton, Olivia e Paulo. Se aparecer
-- Roberto Almeida, o RLS nao esta funcionando -- e nesse caso pare tudo
-- e conserte antes de construir mais qualquer tela.
-- ====================================================================