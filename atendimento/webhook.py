"""Endpoint único de entrada do Atendimento (PROJETO_1.md, Fase 4). Todo
canal (hoje: e-mail; futuro: WhatsApp, Portal, API) chama este mesmo
endpoint, que chama o mesmo orquestrador -- não há lógica duplicada por
canal. A lógica de processamento em si vive em atendimento/processar.py,
compartilhada com o poller (verificação automática de e-mail).

Quando o canal é Email e o Gmail já foi autorizado, o endpoint também
ENVIA a resposta de volta automaticamente. Sem autorização configurada,
só devolve o campo "resposta" pronto.

Segurança: se WEBHOOK_SECRET estiver configurado no .env, exige o
cabeçalho X-Webhook-Secret com o mesmo valor. Sem isso configurado
(dev local), aceita qualquer chamada.
"""
from flask import Flask, jsonify, request

from atendimento.config import WEBHOOK_SECRET
from atendimento.processar import processar_mensagem

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

    resultado = processar_mensagem(
        texto=corpo.get("corpo", ""),
        canal=corpo.get("canal", "Email"),
        assunto=corpo.get("assunto", ""),
        remetente_email=(corpo.get("remetente_email") or "").strip() or None,
        remetente_cpf=(corpo.get("remetente_cpf") or "").strip() or None,
        remetente_nome=(corpo.get("remetente_nome") or "").strip() or None,
        identificador_canal=(corpo.get("identificador_canal") or "").strip() or None,
    )

    status = 400 if resultado.get("erro") and "identificado" not in resultado else 200
    return jsonify(resultado), status


@app.route("/webhook/saude")
def saude():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(debug=True, port=5001)
