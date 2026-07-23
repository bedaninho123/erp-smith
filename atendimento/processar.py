"""Lógica de processamento de uma mensagem recebida, compartilhada entre
o webhook (POST /webhook/mensagem) e o poller (verificação automática da
caixa de entrada) -- os dois canais de entrada de e-mail chamam esta
mesma função, sem duplicar lógica.
"""
import traceback
from typing import Optional

from integracoes.gmail import enviar_email, gmail_configurado
from motor_ia.orquestrador import atender_mensagem


def processar_mensagem(
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

    pode_enviar = resultado["auditoria"].acao == "enviar"
    resposta_texto = resultado["resposta"] if pode_enviar else None

    saida = {
        "identificado": True,
        "cliente_id": resultado["cliente_id"],
        "sessao_id": resultado["sessao_id"],
        "caso_id": resultado["caso_id"],
        "intencao": resultado["classificacao"].intencao,
        "acao": resultado["auditoria"].acao,
        "motivo_auditoria": resultado["auditoria"].motivo,
        "resposta": resposta_texto,
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

    return saida
