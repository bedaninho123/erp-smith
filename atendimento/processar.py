"""Lógica de processamento de uma mensagem recebida, compartilhada entre
o webhook (POST /webhook/mensagem) e o poller (verificação automática da
caixa de entrada) -- os dois canais de entrada de e-mail chamam esta
mesma função, sem duplicar lógica.

MULTI-TENANT: empresa_id é o primeiro parâmetro de tudo aqui, igual ao
resto do Core, e quem chama decide de onde ele vem -- os canais de
entrada usam atendimento/config.py (é configuração do servidor, nunca
entrada do remetente); o painel usa a empresa do usuário logado. Uma
mensagem que chega sem saber de que empresa é não tem como ser
processada com segurança: identificar o remetente é justamente onde o
vazamento aconteceria (ver o achado sobre identificador_cliente.py em
docs/schema_multi_tenant.md).
"""
import traceback
from typing import Optional

from core import motor_conversas, motor_mensagens
from core.configuracoes import obter_configuracoes
from integracoes.gmail import enviar_email, gmail_configurado
from integracoes.whatsapp import enviar_mensagem as enviar_whatsapp
from motor_ia.orquestrador import atender_mensagem


def entregar_resposta(
    canal: str, destino: Optional[str], texto: str, assunto: Optional[str] = None,
) -> dict:
    """Entrega a resposta pelo canal de onde a mensagem veio.

    Pública porque o painel também entrega por aqui (resposta escrita à
    mão na tela de Atendimentos) -- ter uma segunda implementação de
    "como se manda mensagem" lá seria repetir o erro que a existência do
    próprio processar.py evitou entre webhook e poller.

    Ponto único de saída do sistema para o cliente -- antes disto,
    `processar_mensagem` mandava e-mail direto e tratava qualquer outro
    canal como "não envia", o que teria feito toda resposta de WhatsApp
    ser gerada e descartada em silêncio.

    Devolve `{"enviado": bool, "simulado": bool, "motivo": str|None}`.
    Nunca levanta exceção por canal não configurado: não ter Gmail
    autorizado nesta máquina, ou WhatsApp ainda em modo simulado, é
    estado esperado do projeto, não erro de programação.
    """
    if not destino:
        return {"enviado": False, "simulado": False, "motivo": f"Sem destino para o canal {canal}."}

    if canal == "Email":
        if not gmail_configurado():
            return {"enviado": False, "simulado": False, "motivo": "Gmail não autorizado nesta máquina."}
        enviar_email(
            destino,
            assunto=f"Re: {assunto}" if assunto else "Resposta do atendimento",
            corpo=texto,
        )
        return {"enviado": True, "simulado": False, "motivo": None}

    if canal == "WhatsApp":
        # Sem credencial, `enviar_whatsapp` grava no log simulado e
        # devolve simulado=True -- de propósito não é tratado como
        # falha: o fluxo inteiro precisa poder ser testado sem migrar o
        # número do clube para a Cloud API.
        resultado = enviar_whatsapp(destino, texto)
        return {"enviado": True, "simulado": resultado["simulado"], "motivo": None}

    return {"enviado": False, "simulado": False, "motivo": f"Canal sem entrega implementada: {canal}."}


def processar_mensagem(
    empresa_id: str,
    texto: str,
    canal: str = "Email",
    assunto: str = "",
    remetente_email: Optional[str] = None,
    remetente_cpf: Optional[str] = None,
    remetente_nome: Optional[str] = None,
    identificador_canal: Optional[str] = None,
    enviar_resposta: bool = True,
    remetente_telefone: Optional[str] = None,
    id_externo: Optional[str] = None,
) -> dict:
    texto = (texto or "").strip()
    identificador_canal = identificador_canal or remetente_email or remetente_telefone

    if not texto:
        return {"erro": "Campo de texto da mensagem é obrigatório."}
    if not (remetente_email or remetente_cpf or remetente_nome or remetente_telefone):
        return {"erro": "Informe ao menos um identificador do remetente."}

    mensagem_completa = f"Assunto: {assunto}\n\n{texto}" if assunto else texto

    try:
        resultado = atender_mensagem(
            empresa_id,
            mensagem_completa,
            canal=canal,
            identificador_canal=identificador_canal,
            email=remetente_email,
            cpf=remetente_cpf,
            nome=remetente_nome,
            telefone=remetente_telefone,
            criar_contato_se_novo=True,
        )
    except Exception as e:
        traceback.print_exc()
        return {"erro": f"{type(e).__name__}: {e}"}

    if "erro" in resultado:
        return {"identificado": False, "erro": resultado["erro"]}

    acao = resultado["auditoria"].acao
    config = obter_configuracoes(empresa_id)
    revisao_ativa = config.get("revisao_humana_ativa", "Não") == "Sim"

    # "revisar" sempre fica pendente de revisão humana -- o Auditor achou
    # uma inconsistência factual, isso nunca é enviado automaticamente,
    # com ou sem o modo de revisão geral ligado. "enviar" só fica pendente
    # se o modo de revisão (configuracoes.revisao_humana_ativa) estiver
    # ligado -- é o freio de segurança temporário enquanto o sistema ainda
    # está em validação (ver CFG-000028). "encaminhar_humano" sempre sai
    # na hora: é sempre a mesma mensagem institucional fixa, não um texto
    # que a IA inventou, então não tem o mesmo risco.
    pendente_revisao = acao == "revisar" or (acao == "enviar" and revisao_ativa)

    if acao == "encaminhar_humano":
        resposta_texto = config.get(
            "mensagem_encaminhamento_humano",
            "Sua solicitação será encaminhada para um de nossos atendentes.",
        )
        status_msg = motor_mensagens.STATUS_ENCAMINHADO
        pode_enviar = True
    elif pendente_revisao:
        resposta_texto = resultado["resposta"]
        status_msg = motor_mensagens.STATUS_AGUARDANDO_REVISAO
        pode_enviar = False
    elif acao == "enviar":
        resposta_texto = resultado["resposta"]
        status_msg = motor_mensagens.STATUS_ENVIADO
        pode_enviar = True
    else:
        # Não deveria cair aqui hoje (só existem enviar/encaminhar_humano/
        # revisar) -- mas por segurança nunca inventa um envio.
        resposta_texto = None
        status_msg = motor_mensagens.STATUS_ERRO
        pode_enviar = False

    # Envelope de conversa (tela de Atendimentos/CRM). Só existe quando o
    # remetente é cliente cadastrado -- `conversa.cliente_id` é NOT NULL,
    # mesma limitação que sessão/caso/memória já têm. Uma falha aqui não
    # pode derrubar o atendimento: o histórico é importante, mas menos
    # que responder o cliente.
    conversa_id = None
    if resultado["cliente_id"]:
        try:
            conversa_id = motor_conversas.localizar_ou_criar_conversa(
                empresa_id,
                resultado["cliente_id"],
                canal=canal,
                caso_id=resultado["caso_id"],
                assunto=assunto or None,
            )
        except Exception:
            traceback.print_exc()

    mensagem_id = motor_mensagens.registrar_mensagem(
        empresa_id,
        cliente_id=resultado["cliente_id"],
        texto_recebido=mensagem_completa,
        resposta_ia=resposta_texto,
        status_processamento=status_msg,
        canal=canal,
        caso_id=resultado["caso_id"],
        email_remetente=remetente_email,
        assunto=assunto,
        intent=resultado["classificacao"].intencao,
        precisa_humano="Sim" if acao != "enviar" else "Não",
        modelo_ia=config.get("modelo_openai"),
        conversa_id=conversa_id,
        id_externo=id_externo,
    )

    if conversa_id:
        try:
            motor_conversas.registrar_movimento(
                empresa_id, conversa_id, caso_id=resultado["caso_id"],
                assunto=assunto or None,
                precisa_humano="Sim" if acao != "enviar" else None,
            )
        except Exception:
            traceback.print_exc()

    saida = {
        "identificado": True,
        "cliente_id": resultado["cliente_id"],
        "sessao_id": resultado["sessao_id"],
        "caso_id": resultado["caso_id"],
        "conversa_id": conversa_id,
        "mensagem_id": mensagem_id,
        "intencao": resultado["classificacao"].intencao,
        "acao": acao,
        "motivo_auditoria": resultado["auditoria"].motivo,
        "resposta": resposta_texto,
        "pendente_revisao": pendente_revisao,
        "email_enviado": False,
        "resposta_entregue": False,
    }

    if pode_enviar and enviar_resposta:
        destino = remetente_telefone if canal == "WhatsApp" else remetente_email
        try:
            entrega = entregar_resposta(canal, destino, resposta_texto, assunto=assunto)
            saida["resposta_entregue"] = entrega["enviado"]
            saida["envio_simulado"] = entrega["simulado"]
            # Mantido por compatibilidade: o painel e os testes já liam
            # esta chave antes de existir mais de um canal.
            saida["email_enviado"] = entrega["enviado"] and canal == "Email"
            if not entrega["enviado"] and entrega["motivo"]:
                saida["motivo_nao_envio"] = entrega["motivo"]
        except Exception as e:
            traceback.print_exc()
            saida["erro_envio"] = f"{type(e).__name__}: {e}"
            if mensagem_id:
                motor_mensagens.marcar_status(
                    empresa_id, mensagem_id, motor_mensagens.STATUS_ERRO
                )

    return saida


def aprovar_mensagem_pendente(
    empresa_id: str, mensagem_id: str, texto_final: Optional[str] = None,
    responsavel_id: Optional[str] = None,
) -> dict:
    """Manda de verdade um rascunho que estava esperando revisão humana
    (status "Aguardando Revisão"). `texto_final` permite editar o texto
    antes de enviar; se não vier, usa o que a IA escreveu sem alteração.

    O empresa_id vem do usuário logado no painel, e é ele que faz
    obter_mensagem() devolver None quando o mensagem_id é de outra
    empresa -- ou seja, aprovar o rascunho alheio dá "não encontrada",
    não um envio indevido.
    """
    msg = motor_mensagens.obter_mensagem(empresa_id, mensagem_id)
    if not msg:
        return {"erro": f"Mensagem não encontrada: {mensagem_id}"}
    if msg["status_processamento"] != motor_mensagens.STATUS_AGUARDANDO_REVISAO:
        return {"erro": f"Mensagem {mensagem_id} não está aguardando revisão (status atual: {msg['status_processamento']})."}

    texto_para_enviar = (texto_final or msg["resposta_ia"] or "").strip()
    if not texto_para_enviar:
        return {"erro": "Texto de resposta vazio -- nada para enviar."}

    # O rascunho volta pelo canal por onde a pergunta chegou -- responder
    # por e-mail uma dúvida que veio no WhatsApp seria mudar de canal sem
    # o cliente pedir.
    canal = msg.get("canal") or "Email"
    if canal == "WhatsApp":
        destinatario = msg["cliente_telefone"]
    else:
        destinatario = msg["email_remetente"] or msg["cliente_email"]

    try:
        entrega = entregar_resposta(
            canal, destinatario, texto_para_enviar, assunto=msg.get("assunto")
        )
    except Exception as e:
        traceback.print_exc()
        return {"erro": f"{type(e).__name__}: {e}"}

    if not entrega["enviado"]:
        return {"erro": entrega["motivo"] or f"Não foi possível enviar pelo canal {canal}."}

    motor_mensagens.marcar_status(
        empresa_id, mensagem_id, motor_mensagens.STATUS_ENVIADO,
        resposta_final=texto_para_enviar, responsavel_id=responsavel_id,
    )
    return {
        "mensagem_id": mensagem_id,
        "canal": canal,
        "enviado": True,
        "simulado": entrega["simulado"],
        # Compatibilidade com o painel/testes anteriores ao multi-canal.
        "email_enviado": canal == "Email",
    }


def rejeitar_mensagem_pendente(
    empresa_id: str, mensagem_id: str, responsavel_id: Optional[str] = None
) -> dict:
    """Marca um rascunho pendente como rejeitado -- não envia nada. Quem
    precisar responder o cliente por fora do sistema faz isso manualmente.
    """
    msg = motor_mensagens.obter_mensagem(empresa_id, mensagem_id)
    if not msg:
        return {"erro": f"Mensagem não encontrada: {mensagem_id}"}
    if msg["status_processamento"] != motor_mensagens.STATUS_AGUARDANDO_REVISAO:
        return {"erro": f"Mensagem {mensagem_id} não está aguardando revisão (status atual: {msg['status_processamento']})."}

    motor_mensagens.marcar_status(
        empresa_id, mensagem_id, motor_mensagens.STATUS_REJEITADO,
        responsavel_id=responsavel_id,
    )
    return {"mensagem_id": mensagem_id, "rejeitado": True}
