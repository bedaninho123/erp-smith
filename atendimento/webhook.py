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

Multi-tenant: a empresa dona da mensagem vem de atendimento/config.py
(ERP_EMPRESA_ID), NUNCA do corpo da requisição. O único autenticador
aqui é um segredo compartilhado -- se o chamador escolhesse a empresa,
quem tivesse o segredo escreveria dado em qualquer uma delas.
"""
import hashlib
import hmac
import traceback

from flask import Flask, jsonify, request

from atendimento.config import EMPRESA_ID, WEBHOOK_SECRET
from atendimento.processar import processar_mensagem
from integracoes.config import WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN
from integracoes.whatsapp import extrair_mensagens

app = Flask(__name__)

if not WEBHOOK_SECRET:
    print(
        "AVISO: WEBHOOK_SECRET não configurado em .env -- este endpoint "
        "aceita qualquer chamada sem autenticação (ok para teste local, "
        "nunca exponha assim além de localhost -- ver .env.example)."
    )


def _autorizado(req) -> bool:
    if not WEBHOOK_SECRET:
        return True
    recebido = req.headers.get("X-Webhook-Secret") or ""
    return hmac.compare_digest(recebido, WEBHOOK_SECRET)


@app.route("/webhook/mensagem", methods=["POST"])
def receber_mensagem():
    if not _autorizado(request):
        return jsonify(erro="Não autorizado."), 401

    corpo = request.get_json(force=True, silent=True) or {}

    resultado = processar_mensagem(
        EMPRESA_ID,
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


def _assinatura_valida(req) -> bool:
    """Confere o X-Hub-Signature-256 que a Meta manda em cada POST.

    Diferente de /webhook/mensagem (segredo compartilhado num cabeçalho
    próprio), aqui quem dita o esquema é a Meta: HMAC-SHA256 do corpo
    CRU da requisição com o App Secret. Tem que ser o corpo cru mesmo --
    reserializar o JSON muda espaço e ordem de chave, e o hash não bate.

    Sem WHATSAPP_APP_SECRET configurado, aceita (mesma escolha de
    WEBHOOK_SECRET vazio: destrava o desenvolvimento local, e o aviso no
    console diz que está assim).
    """
    if not WHATSAPP_APP_SECRET:
        return True
    recebida = req.headers.get("X-Hub-Signature-256") or ""
    esperada = "sha256=" + hmac.new(
        WHATSAPP_APP_SECRET.encode(), req.get_data(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(recebida, esperada)


@app.route("/webhook/whatsapp", methods=["GET"])
def whatsapp_verificar():
    """Handshake que a Meta faz UMA vez, ao cadastrar a URL do webhook:
    ela chama com um desafio e só aceita a URL se receber o desafio de
    volta em texto puro. Sem isto, não há como registrar o webhook."""
    if request.args.get("hub.verify_token") != WHATSAPP_VERIFY_TOKEN:
        return "Token de verificação inválido.", 403
    return request.args.get("hub.challenge", ""), 200


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_receber():
    """Mensagem recebida pelo WhatsApp -- mesmo orquestrador do e-mail.

    Responde 200 mesmo quando o processamento de uma mensagem falha, de
    propósito: a Meta reenvia o que não recebeu 200, e um erro nosso
    (ex.: OpenAI fora do ar) viraria reenvio infinito da mesma mensagem.
    O que der errado fica no console e no log, não vira fila presa.
    """
    if not _assinatura_valida(request):
        return jsonify(erro="Assinatura inválida."), 401

    corpo = request.get_json(force=True, silent=True) or {}
    processadas = []

    for msg in extrair_mensagens(corpo):
        if not msg["suportado"]:
            # Áudio/imagem/documento: ainda não sabemos ler. Fica
            # registrado para alguém ver na tela em vez de o cliente
            # ficar sem resposta e ninguém saber que ele escreveu.
            print(
                f"[whatsapp] tipo não suportado ({msg['tipo']}) de {msg['telefone']} "
                f"-- id {msg['id_externo']}"
            )
            processadas.append({"id_externo": msg["id_externo"], "ignorado": msg["tipo"]})
            continue
        try:
            resultado = processar_mensagem(
                EMPRESA_ID,
                texto=msg["texto"],
                canal="WhatsApp",
                remetente_telefone=msg["telefone"],
                remetente_nome=msg["nome"],
                identificador_canal=msg["telefone"],
                id_externo=msg["id_externo"],
            )
            processadas.append({"id_externo": msg["id_externo"], **resultado})
        except Exception:
            traceback.print_exc()
            processadas.append({"id_externo": msg["id_externo"], "erro": "falha no processamento"})

    return jsonify(recebidas=len(processadas), resultados=processadas), 200


@app.route("/webhook/saude")
def saude():
    return jsonify(status="ok")


if __name__ == "__main__":
    # debug=False desliga o debugger interativo do Werkzeug (ele permite
    # rodar codigo Python arbitrario pelo navegador em qualquer excecao --
    # risco serio se este processo algum dia for exposto alem de
    # localhost).
    #
    # use_reloader=False de proposito (2026-07-30): nesta maquina, com
    # dois Pythons instalados (.venv e a instalacao global), o reloader
    # do Werkzeug entrava num loop -- cada reinicio alternava entre os
    # dois interpretadores e gerava mais um processo filho, sem nunca
    # convergir. Custo de deixar desligado: editar o arquivo exige
    # reiniciar o processo na mao pra valer.
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)
