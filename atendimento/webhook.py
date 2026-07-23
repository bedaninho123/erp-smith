"""Endpoint único de entrada do Atendimento (PROJETO_1.md, Fase 4). Todo
canal (hoje: e-mail via Make; futuro: WhatsApp, Portal, API) chama este
mesmo endpoint, que chama o mesmo orquestrador -- não há lógica
duplicada por canal.

O que este endpoint FAZ: recebe a mensagem, identifica o cliente, roda
o pipeline completo (motor_ia.orquestrador) e devolve a resposta pronta
(ou a decisão de encaminhar a humano / reter para revisão).

O que este endpoint AINDA NÃO FAZ: enviar a resposta de volta pelo
canal de origem (ex.: responder o e-mail via Gmail). Isso é uma
integração separada (Gmail API) que ainda não foi construída -- quem
chama este endpoint hoje precisa decidir o que fazer com o campo
"resposta" do retorno.

Segurança: se WEBHOOK_SECRET estiver configurado no .env, exige o
cabeçalho X-Webhook-Secret com o mesmo valor. Sem isso configurado
(dev local), aceita qualquer chamada.
"""
import traceback

from flask import Flask, jsonify, request

from atendimento.config import WEBHOOK_SECRET
from motor_ia.orquestrador import atender_mensagem

app = Flask(__name__)


def _autorizado(req) -> bool:
    if not WEBHOOK_SECRET:
        return True
    return req.headers.get("X-Webhook-Secret") == WEBHOOK_SECRET


@app.route("/webhook/mensagem", methods=["POST"])
def receber_mensagem():
    if not _autorizado(request):
        return jsonify(erro="Não autorizado."), 401

    corpo = request.get_json(force=True, silent=True) or {}

    canal = corpo.get("canal", "Email")
    remetente_email = (corpo.get("remetente_email") or "").strip() or None
    remetente_cpf = (corpo.get("remetente_cpf") or "").strip() or None
    remetente_nome = (corpo.get("remetente_nome") or "").strip() or None
    assunto = (corpo.get("assunto") or "").strip()
    texto = (corpo.get("corpo") or "").strip()
    identificador_canal = (corpo.get("identificador_canal") or "").strip() or remetente_email

    if not texto:
        return jsonify(erro="Campo 'corpo' (texto da mensagem) é obrigatório."), 400
    if not (remetente_email or remetente_cpf or remetente_nome):
        return jsonify(
            erro="Informe ao menos um identificador do remetente: "
                 "remetente_email, remetente_cpf ou remetente_nome."
        ), 400

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
        return jsonify(erro=f"{type(e).__name__}: {e}"), 500

    if "erro" in resultado:
        return jsonify(identificado=False, erro=resultado["erro"]), 200

    return jsonify(
        identificado=True,
        cliente_id=resultado["cliente_id"],
        sessao_id=resultado["sessao_id"],
        caso_id=resultado["caso_id"],
        intencao=resultado["classificacao"].intencao,
        acao=resultado["auditoria"].acao,
        motivo_auditoria=resultado["auditoria"].motivo,
        resposta=resultado["resposta"] if resultado["auditoria"].acao != "encaminhar_humano" else None,
    )


@app.route("/webhook/saude")
def saude():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
