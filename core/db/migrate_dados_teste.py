"""Migra os dados de teste reais da planilha 'Banco de Dados - Clube de Tiro.xlsx'
para o banco do Core. Decisões desta migração (aprovadas com o usuário em 2026-07-22):
  - IDs de teste com 3 dígitos convertidos para 6 (ex.: CLI-001 -> CLI-000001).
  - 47 linhas duplicadas 'TEMP-000001' em Casos foram descartadas (lixo de teste).
  - Linha CLI-000004 (sem nome/cpf) foi descartada.
  - Processos 2 e 3 não tinham Caso na planilha original (caso_id é campo novo) ->
    foram criados 2 Casos sintéticos (CAS-000002, CAS-000003) para viabilizar a migração.
  - Usuários USR-000001 (Felipe) e USR-000002 (Ana) foram criados a partir dos nomes
    soltos em processo.responsavel/documento.revisado_por; não existe aba Usuários na planilha.
  - conversa.iniciada_em/ultima_mensagem_em reconstruídos (planilha tinha texto
    literal "data atual", não uma data real).
  - template: os 7 campos de texto-padrão tirados de servico (2ª rodada) viram
    7 linhas de template (4 fixas + 3 com marcador {campo}).

MULTI-TENANT (docs/schema_multi_tenant.md, 2026-07-28): este script é o
bootstrap do sistema inteiro -- cria a empresa EMP-000001 (Smith) e
grava todo o dado migrado como sendo dela.

Dois detalhes que mudaram junto e valem saber:
  - Todo INSERT passou a listar as colunas pelo nome. Com `INSERT INTO
    tabela VALUES (...)` posicional, acrescentar uma coluna ao schema
    quebra o script em silêncio -- foi exatamente o que aconteceu com
    usuario.senha_hash e documento.mensagem_id, que entraram no schema
    depois e deixaram este arquivo desatualizado sem ninguém notar.
  - O caminho do banco vem de core.conexao (que respeita ERP_CORE_DB),
    não mais de um literal aqui dentro.

Roda depois de `python -m core.db.criar_banco`, num banco vazio.
"""
from datetime import datetime, timedelta

from core.conexao import conectar
from core.motor_empresas import EMPRESA_PADRAO, criar_empresa, obter_empresa

EMPRESA = EMPRESA_PADRAO
EMPRESA_NOME = "Smith Clube de Tiro"
EMPRESA_DOMINIO = "clube_tiro"


def excel_to_iso(serial: float) -> str:
    dt = datetime(1899, 12, 30) + timedelta(days=serial)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _garantir_empresa() -> None:
    if obter_empresa(EMPRESA):
        print(f"Empresa {EMPRESA} já existe.")
        return
    criar_empresa(EMPRESA_NOME, EMPRESA_DOMINIO, empresa_id=EMPRESA)
    print(f"Empresa criada: {EMPRESA} -- {EMPRESA_NOME} (domínio {EMPRESA_DOMINIO}).")


def main():
    _garantir_empresa()

    con = conectar(EMPRESA)
    cur = con.cursor()

    # Este script insere IDs fixos (CLI-000001, CAS-000001...); rodar duas
    # vezes daria erro de chave primária no meio do caminho, deixando o
    # banco pela metade. Melhor recusar antes de escrever qualquer coisa.
    ja_migrado = cur.execute(
        "SELECT 1 FROM cliente WHERE empresa_id = ? LIMIT 1", (EMPRESA,)
    ).fetchone()
    if ja_migrado:
        con.close()
        raise SystemExit(
            "Este banco já tem cliente cadastrado -- a migração não roda "
            "duas vezes.\nPara começar do zero: "
            ".venv\\Scripts\\python.exe -m core.db.criar_banco --recriar"
        )

    # 1) cliente
    cur.executemany(
        "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, email, telefone, "
        "cidade, status, atendimento_ia, data_cadastro, ultima_interacao, observacoes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("CLI-000001", EMPRESA, "Felipe Bedani", "12345678900", "bedaninho123@gmail.com",
             "5514999990001", "Marília", "Ativo", "Sim",
             excel_to_iso(46204.0), excel_to_iso(46216.791666666664),
             "Cliente de teste principal."),
            ("CLI-000002", EMPRESA, "João da Silva", "98765432100", "joao.teste@example.com",
             "5514999990002", "Bauru", "Ativo", "Sim",
             excel_to_iso(46193.0), excel_to_iso(46213.604166666664),
             "Aguardando documento."),
            ("CLI-000003", EMPRESA, "Maria Oliveira", "45678912300", "maria.teste@example.com",
             "5514999990003", "Assis", "Inativo", "Não",
             excel_to_iso(46157.0), excel_to_iso(46203.385416666664),
             "Atendimento humano obrigatório."),
        ],
    )

    # 2) usuario (inferidos; não existe aba Usuários na planilha).
    #    senha_hash fica NULL de propósito: senha nunca é definida por
    #    código, só por webapp/definir_senha.py rodado pelo próprio dono.
    cur.executemany(
        "INSERT INTO usuario (usuario_id, empresa_id, nome, email, papel, equipe, "
        "ativo, criado_em) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("USR-000001", EMPRESA, "Felipe", "bedaninho123@gmail.com", "Gestor",
             "Despachante", "Sim", "2026-07-22T00:00:00Z"),
            ("USR-000002", EMPRESA, "Ana", "ana.despachante@smithclube.local", "Atendente",
             "Despachante", "Sim", "2026-07-22T00:00:00Z"),
        ],
    )

    # 3) servico (IDs convertidos de 3 para 6 dígitos)
    cur.executemany(
        "INSERT INTO servico (service_id, empresa_id, service_key, nome_servico, "
        "descricao, categoria, prazo_estimado_dias, valor_referencia, "
        "documentos_obrigatorios, ativo, observacoes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("SER-000001", EMPRESA, "renovacao_cr", "Renovação do CR",
             "Renovação do Certificado de Registro.", "Regularização documental",
             45, 850.00, "RG; CPF; comprovante; certidões; laudo; capacidade técnica.",
             "Sim", "Pode variar conforme o Exército."),
            ("SER-000002", EMPRESA, "primeiro_cr", "Primeiro CR",
             "Primeiro Certificado de Registro.", "Regularização documental",
             60, 1200.00, "RG; CPF; comprovante; certidões; laudo; capacidade técnica.",
             "Sim", "Primeira emissão."),
            ("SER-000003", EMPRESA, "apostilamento", "Apostilamento", "Apostilamento.",
             "Regularização documental", 30, 500.00,
             "Documento da arma; comprovante; documentos pessoais.",
             "Sim", "Inclusão de arma."),
            ("SER-000004", EMPRESA, "transferencia_arma", "Transferência",
             "Transferência de arma.", "Transferência", 40, 650.00,
             "Documentação das partes e da arma.", "Sim", "Transferência."),
        ],
    )

    # 4) sessao (caso_id e ultimo_processo_id ficam NULL por enquanto; ver passo 9)
    cur.execute(
        "INSERT INTO sessao (sessao_id, empresa_id, cliente_id, caso_id, canal, "
        "identificador_canal, assunto_atual, ultima_intencao, ultimo_servico_id, "
        "ultimo_processo_id, ultima_mensagem_cliente, ultima_resposta_ia, "
        "resumo_sessao, status_sessao, iniciada_em, ultima_interacao_em, expira_em, "
        "encaminhada_humano, responsavel_id, conversa_id_origem, ativo, observacoes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("SES-000001", EMPRESA, "CLI-000001", None, "Email", "cliente@email.com",
         "Renovação do CR", "consulta_documentos", "SER-000001", None,
         "Quais documentos preciso para renovar meu CR?",
         "Para renovar seu CR, são necessários os documentos cadastrados para o serviço.",
         "Cliente solicitou informações sobre documentos para renovação do CR. "
         "Existe processo vinculado em análise.",
         "Aberta", excel_to_iso(46221.625), excel_to_iso(46221.62847222222),
         excel_to_iso(46222.62847222222), "Não", None, None, "Sim",
         "Registro de exemplo migrado da planilha. Campo responsavel original era "
         "\"IA Smith\" (não é usuário humano, por isso ficou vazio)."),
    )

    # 5) memoria_ia
    cur.execute(
        "INSERT INTO memoria_ia (memoria_id, empresa_id, cliente_id, resumo_cliente, "
        "assuntos_recentes, servicos_recentes, processos_recentes, ultima_intencao, "
        "preferencia_canal, tom_recomendado, informacoes_importantes, "
        "restricoes_atendimento, ultima_sessao_id, atualizada_em, atualizada_por, "
        "versao, ativo, observacoes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("MEM-000001", EMPRESA, "CLI-000001",
         "Cliente possui atendimento relacionado à renovação do CR e já solicitou "
         "informações sobre documentação e andamento.",
         "Renovação do CR; consulta de documentos; status de processo",
         "SER-000001 - Renovação do CR", "PRO-000001 - Em análise",
         "consulta_documentos", "Email", "Profissional, claro e objetivo",
         "Sempre confirmar protocolo e próxima ação quando existirem.",
         "Nunca informar documentos, prazos ou valores diferentes dos cadastrados.",
         "SES-000001", excel_to_iso(46221.62847222222), "Make", 1, "Sim",
         "Memória de exemplo para teste"),
    )

    # 6) caso real (CAS-000001) — criado_em/atualizado_em vazios na origem;
    #    reconstruídos a partir das datas de sessao/memoria_ia do mesmo cenário.
    COLUNAS_CASO = (
        "INSERT INTO caso (caso_id, empresa_id, cliente_id, titulo, descricao, "
        "categoria, tipo_caso, origem, canal_origem, status, fase, prioridade, "
        "responsavel_id, equipe_responsavel, sessao_principal_id, memoria_id, "
        "criado_em, atualizado_em, prazo_previsto, encerrado_em, criado_por, "
        "alterado_por, versao, ativo, motivo_encerramento, observacoes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )
    cur.execute(
        COLUNAS_CASO,
        ("CAS-000001", EMPRESA, "CLI-000001", "Renovação de CR",
         "Cliente deseja renovar o CR e organizar os documentos necessários.",
         "Regularização documental", "Solicitação", "Atendimento", "Email",
         "Em triagem", "Triagem", "Normal", "USR-000001", "Despachante",
         "SES-000001", "MEM-000001",
         excel_to_iso(46221.625), excel_to_iso(46221.62847222222),
         None, None, "Make", "Make", 1, "Sim", None,
         "Linha de exemplo migrada da planilha; criado_em/atualizado_em "
         "reconstruídos (estavam vazios na origem)."),
    )

    # 7) casos sintéticos, criados na migração para os processos 2 e 3
    #    (caso_id não existia como coluna na planilha original de Processos).
    cur.executemany(
        COLUNAS_CASO,
        [
            ("CAS-000002", EMPRESA, "CLI-000002", "Primeiro CR",
             "Caso criado automaticamente na migração para vincular o processo "
             "PRO-000002 (Primeiro CR).",
             "Regularização documental", "Solicitação", "Atendimento", "Email",
             "Aguardando cliente", "Documentação", "Normal", "USR-000001",
             "Despachante", None, None,
             excel_to_iso(46205.0), excel_to_iso(46213.458333333336),
             None, None, "Migração", "Migração", 1, "Sim", None,
             "Caso sintético: não existia na planilha original, criado só para "
             "satisfazer a exigência de caso_id do processo PRO-000002."),
            ("CAS-000003", EMPRESA, "CLI-000003", "Apostilamento",
             "Caso criado automaticamente na migração para vincular o processo "
             "PRO-000003 (Apostilamento).",
             "Regularização documental", "Solicitação", "Atendimento", "Email",
             "Encerrado", "Conclusão", "Normal", "USR-000002",
             "Despachante", None, None,
             excel_to_iso(46152.0), excel_to_iso(46178.416666666664),
             None, excel_to_iso(46178.416666666664), "Migração", "Migração", 1,
             "Sim", "Concluído com sucesso",
             "Caso sintético: não existia na planilha original, criado só para "
             "satisfazer a exigência de caso_id do processo PRO-000003."),
        ],
    )

    # 8) processo
    cur.executemany(
        "INSERT INTO processo (processo_id, empresa_id, caso_id, cliente_id, "
        "servico_id, protocolo, status, data_abertura, prazo_estimado, proxima_acao, "
        "responsavel_id, ultima_atualizacao, observacoes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("PRO-000001", EMPRESA, "CAS-000001", "CLI-000001", "SER-000001",
             "PROTO-2026-001", "Em análise", excel_to_iso(46198.0),
             excel_to_iso(46243.0), "Aguardar retorno do órgão", "USR-000001",
             excel_to_iso(46215.680555555555), "Sem pendências registradas."),
            ("PRO-000002", EMPRESA, "CAS-000002", "CLI-000002", "SER-000002",
             None, "Aguardando documentos", excel_to_iso(46205.0),
             excel_to_iso(46265.0), "Receber comprovante de residência",
             "USR-000001", excel_to_iso(46213.458333333336),
             "Falta comprovante de residência atualizado."),
            ("PRO-000003", EMPRESA, "CAS-000003", "CLI-000003", "SER-000003",
             "PROTO-2026-003", "Concluído", excel_to_iso(46152.0),
             excel_to_iso(46182.0), "Nenhuma", "USR-000002",
             excel_to_iso(46178.416666666664), "Processo concluído para teste."),
        ],
    )

    # 9) fecha o ciclo sessao <-> caso/processo, agora que ambos existem
    cur.execute(
        "UPDATE sessao SET caso_id = ?, ultimo_processo_id = ? "
        "WHERE sessao_id = ? AND empresa_id = ?",
        ("CAS-000001", "PRO-000001", "SES-000001", EMPRESA),
    )

    # 10) documento — mensagem_id fica NULL: documento migrado da planilha
    #     não veio de anexo de e-mail nenhum.
    cur.executemany(
        "INSERT INTO documento (documento_id, empresa_id, cliente_id, caso_id, "
        "processo_id, tipo_documento, nome_arquivo, link_arquivo, status, "
        "data_envio, data_validade, revisado_por_id, observacoes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("DOC-000001", EMPRESA, "CLI-000001", None, "PRO-000001", "RG",
             "rg_felipe.pdf", "https://example.com/arquivo-teste-1", "Aprovado",
             excel_to_iso(46198.0), excel_to_iso(49851.0), "USR-000001",
             "Documento fictício."),
            ("DOC-000002", EMPRESA, "CLI-000002", None, "PRO-000002",
             "Comprovante de residência", None, None, "Pendente", None, None,
             None, "Cliente ainda não enviou."),
            ("DOC-000003", EMPRESA, "CLI-000003", None, "PRO-000003", "Documento do item",
             "documento_item.pdf", "https://example.com/arquivo-teste-3",
             "Aprovado", excel_to_iso(46154.0), None, "USR-000002",
             "Documento fictício."),
        ],
    )

    # 11) conversa — planilha tinha iniciada_em/ultima_mensagem_em como texto
    #     literal "data atual" (não uma data de verdade); reconstruído a partir
    #     de sessao.iniciada_em, do mesmo cenário de teste.
    cur.execute(
        "INSERT INTO conversa (conversa_id, empresa_id, cliente_id, caso_id, "
        "sessao_id, canal, origem, status, assunto_principal, iniciada_em, "
        "ultima_mensagem_em, encerrada_em, responsavel_id, precisa_humano, "
        "total_mensagens, criado_por, atualizado_por, versao, ativo, observacoes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("CON-000001", EMPRESA, "CLI-000001", "CAS-000001", "SES-000001", "Webhook",
         "Sistema", "Aberta", "Novo Atendimento",
         excel_to_iso(46221.625), excel_to_iso(46221.625), None, None, "Não", 1,
         "make", "make", 1, "Sim",
         "Conversa criada automaticamente. iniciada_em/ultima_mensagem_em "
         "reconstruídos (planilha tinha texto literal \"data atual\")."),
    )

    # 12) fecha o ciclo sessao <-> conversa, agora que conversa existe
    cur.execute(
        "UPDATE sessao SET conversa_id_origem = ? WHERE sessao_id = ? AND empresa_id = ?",
        ("CON-000001", "SES-000001", EMPRESA),
    )

    # 13) template — recupera os 7 campos tirados de servico na 2ª rodada.
    cur.executemany(
        "INSERT INTO template (template_id, empresa_id, template_key, nome, "
        "categoria, conteudo, canal, ativo, observacoes) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("TPL-000001", EMPRESA, "resposta_sem_processo", "Resposta: sem processo",
             "processo", "Não localizei processo vinculado.", None, "Sim", None),
            ("TPL-000002", EMPRESA, "resposta_em_analise", "Resposta: em análise",
             "processo", "Processo em análise.", None, "Sim", None),
            ("TPL-000003", EMPRESA, "resposta_documento_pendente",
             "Resposta: documento pendente", "processo",
             "Documentação pendente.", None, "Sim", None),
            ("TPL-000004", EMPRESA, "resposta_concluido", "Resposta: concluído",
             "processo", "Processo concluído.", None, "Sim", None),
            ("TPL-000005", EMPRESA, "mensagem_padrao_servico", "Mensagem padrão de serviço",
             "servico", "Localizei o serviço de {nome_servico}.", None, "Sim",
             None),
            ("TPL-000006", EMPRESA, "prazo_texto_servico", "Texto de prazo do serviço",
             "servico", "Prazo médio de {prazo_estimado_dias} dias.", None,
             "Sim", None),
            ("TPL-000007", EMPRESA, "valor_texto_servico", "Texto de valor do serviço",
             "servico", "Valor de referência: R$ {valor_referencia}.", None,
             "Sim", None),
        ],
    )

    # 14) mensagem — a linha "TEMP" (sem cliente_id, mensagem corrompida) foi
    #     descartada, mesmo padrão do TEMP-000001 em Casos. As 2 linhas reais
    #     tinham mensagem_id/caso_id/conversa_id/processo_id vazios ou ausentes
    #     na origem; preenchidos por inferência lógica (ver docs/schema_mensagem.md).
    resposta_ia_msg1 = (
        "Olá, Felipe Bedani.\n\n"
        "Localizei seu processo e seguem as informações atualizadas:\n\n"
        "Serviço: Renovação do CR\n"
        "Protocolo: PROTO-2026-001\n"
        "Status atual: Em análise\n"
        "Data de abertura: 25/06/2026\n"
        "Prazo estimado: 09/08/2026\n"
        "Próxima ação: Aguardar retorno do órgão\n"
        "Responsável: Felipe\n"
        "Última atualização: 12/07/2026 às 16:20\n"
        "Observações: Sem pendências registradas.\n\n"
        "O processo permanece em análise. No momento não é necessária nenhuma "
        "ação de sua parte; estamos aguardando o retorno do órgão responsável e "
        "acompanharemos a evolução até a próxima atualização.\n\n"
        "Caso tenha qualquer dúvida ou precise de novas informações sobre seu "
        "processo, estou à disposição para ajudar.\n\n"
        "Atenciosamente,\n\nEquipe Smith Clube de Tiro"
    )
    cur.executemany(
        "INSERT INTO mensagem (mensagem_id, empresa_id, cliente_id, caso_id, "
        "conversa_id, processo_id, canal, data_hora, origem, email_remetente, "
        "assunto, mensagem, intent, resumo_ia, precisa_humano, "
        "status_processamento, id_externo, resposta_ia, responsavel_id, "
        "tempo_processamento_ms, modelo_ia, observacoes_ia) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("MSG-000001", EMPRESA, "CLI-000001", "CAS-000001", "CON-000001",
             "PRO-000001", "Email", "2026-07-17T22:15:29Z", "Cliente",
             "bedaninho123@gmail.com", "Teste Update Row", None,
             "consulta_processo",
             "Cliente solicita consulta de status de processo. "
             "CPF informado: 12345678900.",
             "Não", "Respondido", "19f7225fa87214da", resposta_ia_msg1,
             "USR-000001", None, "gpt-5-mini",
             "Corpo original da mensagem estava corrompido no Make (texto "
             "literal \"System.Xml.XmlElement\", bug de serialização). "
             "precisa_humano normalizado de \"0\" para \"Não\". caso_id/"
             "conversa_id inferidos (único caso/conversa do cliente)."),
            ("MSG-000002", EMPRESA, "CLI-000002", "CAS-000002", None, "PRO-000002",
             "Email", excel_to_iso(46213.604166666664), "Sistema",
             "sistema@example.com", "Documento pendente",
             "Precisamos do comprovante de residência atualizado.",
             "envio_documento", "Solicitação automática de documento pendente.",
             "Não", "Enviado", "gmail-test-002", None, None, None, None,
             "caso_id/processo_id inferidos: assunto e conteúdo batem "
             "exatamente com PRO-000002 (pendência de comprovante de "
             "residência)."),
        ],
    )

    # 15) configuracoes — 20_Configuracoes tinha 28 linhas, mas 2 chaves
    #     duplicadas (mesmo valor, config_id diferente); migradas uma única
    #     vez cada (permitir_valores_referencia, permitir_prazos_referencia).
    #     São as configurações DESTA empresa: outra empresa terá as dela,
    #     com as mesmas chaves e valores diferentes.
    cur.executemany(
        "INSERT INTO configuracoes (config_id, empresa_id, chave, valor, "
        "categoria, descricao, ativo) VALUES (?,?,?,?,?,?,?)",
        [
            ("CFG-000001", EMPRESA, "nome_empresa", "Smith Clube de Tiro", "empresa",
             "Nome utilizado nas mensagens", "Sim"),
            ("CFG-000002", EMPRESA, "nome_assistente", "Assistente Virtual Smith", "ia",
             "Nome do atendente virtual", "Sim"),
            ("CFG-000003", EMPRESA, "cidade", "Marília", "empresa",
             "Cidade da empresa", "Sim"),
            ("CFG-000004", EMPRESA, "estado", "SP", "empresa", "Estado da empresa",
             "Sim"),
            ("CFG-000005", EMPRESA, "telefone", "(14)99805-9500 / (14) 99815-7890",
             "contato", "Telefone principal", "Sim"),
            ("CFG-000006", EMPRESA, "whatsapp", "(14)99805-9500 / (14) 99815-7890",
             "contato", "WhatsApp de atendimento", "Sim"),
            ("CFG-000007", EMPRESA, "email_atendimento", "smithclube@gmail.com",
             "contato", "E-mail de atendimento", "Sim"),
            ("CFG-000008", EMPRESA, "site", "www.smithloja.com.br", "contato",
             "Site oficial", "Não"),
            ("CFG-000009", EMPRESA, "horario_semana",
             "Terça e Sexta: 9h as 18h / Quarta 14h as 21h / Quinta 13h as 20h",
             "atendimento", "Horário de atendimento semanal", "Sim"),
            ("CFG-000010", EMPRESA, "horario_sabado", "Sábado, das 9h às 17h",
             "atendimento", "Horário de sábado", "Sim"),
            ("CFG-000011", EMPRESA, "horario_domingo", "Fechado", "atendimento",
             "Horário de domingo", "Sim"),
            ("CFG-000012", EMPRESA, "saudacao_padrao", "Olá! Como podemos ajudar?",
             "mensagens", "Saudação inicial", "Sim"),
            ("CFG-000013", EMPRESA, "mensagem_fora_horario",
             "Recebemos sua mensagem fora do nosso horário de atendimento. "
             "Retornaremos assim que possível.", "mensagens",
             "Resposta fora do expediente", "Sim"),
            ("CFG-000014", EMPRESA, "mensagem_encaminhamento_humano",
             "Sua solicitação será encaminhada para nossa equipe de atendimento.",
             "mensagens", "Aviso de transferência", "Sim"),
            ("CFG-000015", EMPRESA, "assinatura_email", "Equipe Smith Clube de Tiro",
             "mensagens", "Assinatura dos e-mails", "Sim"),
            ("CFG-000016", EMPRESA, "prazo_resposta_humano", "Em até 1 dia útil",
             "atendimento", "Prazo estimado para resposta humana", "Sim"),
            ("CFG-000017", EMPRESA, "moeda", "BRL", "sistema",
             "Moeda utilizada nos valores", "Sim"),
            ("CFG-000018", EMPRESA, "idioma", "pt-BR", "sistema",
             "Idioma das respostas", "Sim"),
            ("CFG-000019", EMPRESA, "permitir_valores_referencia", "Sim", "ia",
             "Permite informar valores cadastrados", "Sim"),
            ("CFG-000020", EMPRESA, "permitir_prazos_referencia", "Sim", "ia",
             "Permite informar prazos cadastrados", "Sim"),
            ("CFG-000021", EMPRESA, "aviso_valor",
             "Os valores informados são referências e podem variar conforme "
             "o serviço e as particularidades do caso.", "mensagens",
             "Aviso utilizado junto aos valores", "Sim"),
            ("CFG-000022", EMPRESA, "aviso_prazo",
             "Os prazos informados são estimativas e podem variar conforme "
             "a análise do órgão competente.", "mensagens",
             "Aviso utilizado junto aos prazos", "Sim"),
            ("CFG-000023", EMPRESA, "temperatura_ia", "0.2", "ia",
             "Criatividade das respostas", "Sim"),
            ("CFG-000024", EMPRESA, "max_tokens", "1200", "ia",
             "Máximo de tokens das respostas", "Sim"),
            ("CFG-000025", EMPRESA, "modelo_openai", "gpt-5-mini", "ia",
             "Modelo utilizado", "Sim"),
            ("CFG-000026", EMPRESA, "idioma_resposta", "pt-BR", "ia",
             "Idioma padrão das respostas", "Sim"),
            ("CFG-000027", EMPRESA, "mensagem_cliente_nao_encontrado",
             "Não localizamos um cadastro com esses dados em nosso sistema. "
             "Se você já é nosso cliente, poderia nos informar seu CPF para "
             "localizarmos seu cadastro? Caso ainda não seja cliente, "
             "ficaremos felizes em ajudar -- conte um pouco mais sobre o que "
             "você precisa.",
             "mensagens",
             "Resposta para remetente não identificado como cliente cadastrado",
             "Sim"),
            ("CFG-000028", EMPRESA, "revisao_humana_ativa", "Sim", "atendimento",
             "Enquanto 'Sim', respostas que a IA mesma escreveu (ação "
             "'enviar') ficam pendentes de aprovação humana antes de sair "
             "de verdade -- modo de segurança temporário para a fase de "
             "validação. Desligar (mudar para 'Não') quando o sistema "
             "estiver validado o suficiente para enviar 100% automático.",
             "Sim"),
            ("CFG-000029", EMPRESA, "notificar_cliente_mudanca_status", "Sim", "portal",
             "Enquanto 'Sim', o cliente recebe um e-mail genérico (sem "
             "detalhe do novo status no corpo, só um link pro Portal) "
             "sempre que o status de um caso ou processo dele muda pelo "
             "painel administrativo. Desligar (mudar para 'Não') se o "
             "volume de e-mail incomodar ou precisar pausar por algum bug.",
             "Sim"),
        ],
    )

    # 16) tarefas — caso_id (campo novo) inferido via processo_id.
    cur.executemany(
        "INSERT INTO tarefas (tarefa_id, empresa_id, caso_id, cliente_id, "
        "processo_id, tipo, descricao, responsavel_id, prazo, prioridade, status, "
        "data_conclusao, observacoes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("TAR-000001", EMPRESA, "CAS-000002", "CLI-000002", "PRO-000002",
             "Cobrar documento",
             "Solicitar comprovante de residência atualizado.", "USR-000001",
             excel_to_iso(46218.0), "Alta", "Pendente", None,
             "Enviar lembrete por e-mail."),
            ("TAR-000002", EMPRESA, "CAS-000001", "CLI-000001", "PRO-000001",
             "Consultar andamento",
             "Verificar atualização no órgão responsável.", "USR-000001",
             excel_to_iso(46223.0), "Normal", "Pendente", None, None),
        ],
    )

    con.commit()

    print(f"Migração concluída sob {EMPRESA}. Contagem de linhas por tabela:")
    for tabela in ["cliente", "usuario", "servico", "caso", "processo",
                   "documento", "sessao", "memoria_ia", "conversa", "template",
                   "mensagem", "configuracoes", "tarefas"]:
        n = cur.execute(
            f"SELECT COUNT(*) FROM {tabela} WHERE empresa_id = ?", (EMPRESA,)
        ).fetchone()[0]
        print(f"  {tabela}: {n}")

    con.close()


if __name__ == "__main__":
    main()
