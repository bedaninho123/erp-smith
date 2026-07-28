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

from core import motor_mensagens
from core.configuracoes import obter_configuracoes
from integracoes.gmail import enviar_email, gmail_configurado
from motor_ia.orquestrador import atender_mensagem


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
) -> dict:
    texto = (texto or "").strip()
    identificador_canal = identificador_canal or remetente_email

    if not texto:
        return {"erro": "Campo de texto da mensagem é obrigatório."}
    if not (remetente_email or remetente_cpf or remetente_nome):
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
    )

    saida = {
        "identificado": True,
        "cliente_id": resultado["cliente_id"],
        "sessao_id": resultado["sessao_id"],
        "caso_id": resultado["caso_id"],
        "mensagem_id": mensagem_id,
        "intencao": resultado["classificacao"].intencao,
        "acao": acao,
        "motivo_auditoria": resultado["auditoria"].motivo,
        "resposta": resposta_texto,
        "pendente_revisao": pendente_revisao,
        "email_enviado": False,
    }

    if pode_enviar and enviar_resposta and canal == "Email" and remetente_email and gmail_configurado():
        try:
            enviar_email(
                remetente_email,
                assunto=f"Re: {assunto}" if assunto else "Resposta do atendimento",
                corpo=resposta_texto,
            )
            saida["email_enviado"] = True
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

    destinatario = msg["email_remetente"] or msg["cliente_email"]
    if not (destinatario and gmail_configurado()):
        return {"erro": "Sem e-mail de destino ou Gmail não configurado -- não é possível enviar."}

    try:
        enviar_email(
            destinatario,
            assunto=f"Re: {msg['assunto']}" if msg["assunto"] else "Resposta do atendimento",
            corpo=texto_para_enviar,
        )
    except Exception as e:
        traceback.print_exc()
        return {"erro": f"{type(e).__name__}: {e}"}

    motor_mensagens.marcar_status(
        empresa_id, mensagem_id, motor_mensagens.STATUS_ENVIADO,
        resposta_final=texto_para_enviar, responsavel_id=responsavel_id,
    )
    return {"mensagem_id": mensagem_id, "email_enviado": True}


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
