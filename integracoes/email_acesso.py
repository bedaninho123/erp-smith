"""E-mail de acesso ao Portal pelo Resend (2026-11-04).

Em 04/11 o Google bloqueou a conta do clube depois de menos de 30 e-mails em
10 minutos: muitos e-mails quase iguais, com link de acesso, saindo de uma
conta pessoal. Este módulo é só para o e-mail de acesso, com o domínio do clube.
O resto (respostas do atendimento, convites, alertas) continua no Gmail.

O Resend entrou no lugar do Brevo porque a política do Brevo proíbe conteúdo
que promova ou venda armas, e o Portal tem Marketplace. A do Resend não cita
armas, mas deixa decisões a critério dele: por isso só o acesso passa por aqui,
nunca anúncio.

A diferença que importa para o Gmail: quando a cota acaba, o Resend recusa na
hora, e o sistema fica sabendo. O Gmail aceitava e devolvia o e-mail depois.

Sem as duas variáveis, `email_acesso_configurado()` é False e o Portal segue
pelo Gmail, como antes.
"""
import os

import requests

URL_ENVIO = "https://api.resend.com/emails"
TIMEOUT_SEGUNDOS = 15

# 429 também é `rate_limit_exceeded`, que passa em segundos e não é cota.
_ERROS_DE_COTA = {"daily_quota_exceeded", "monthly_quota_exceeded"}


class EnvioAcessoFalhou(Exception):
    """O texto nunca leva destinatário nem corpo: o corpo tem o link de
    acesso, e esta mensagem vai parar no log."""


class CotaEsgotada(EnvioAcessoFalhou):
    pass


def _chave() -> str:
    return (os.environ.get("RESEND_API_KEY") or "").strip()


def _remetente() -> str:
    return (os.environ.get("EMAIL_ACESSO_REMETENTE") or "").strip()


def email_acesso_configurado() -> bool:
    return bool(_chave() and _remetente())


def enviar_email_acesso(
    destinatario: str, assunto: str, corpo: str,
    nome_remetente: str = None, responder_para: str = None,
) -> str:
    """Envia e devolve o id do Resend. Levanta CotaEsgotada ou EnvioAcessoFalhou."""
    remetente = _remetente()
    if nome_remetente:
        limpo = nome_remetente.replace('"', "").replace("<", "").replace(">", "").strip()
        remetente = f"{limpo} <{remetente}>"
    dados = {"from": remetente, "to": [destinatario], "subject": assunto, "text": corpo}
    if responder_para:
        dados["reply_to"] = responder_para

    try:
        resposta = requests.post(
            URL_ENVIO, json=dados, timeout=TIMEOUT_SEGUNDOS, allow_redirects=False,
            headers={"Authorization": f"Bearer {_chave()}"},
        )
    except requests.RequestException as e:
        # `from None`: a exceção original pode trazer o pedido junto.
        raise EnvioAcessoFalhou(f"Resend não respondeu ({type(e).__name__}).") from None

    if resposta.status_code in (200, 201):
        return resposta.json().get("id", "")

    try:
        nome_erro = resposta.json().get("name", "")
    except ValueError:
        nome_erro = ""
    texto = f"Resend recusou o envio: HTTP {resposta.status_code} {nome_erro}".strip()
    if nome_erro in _ERROS_DE_COTA:
        raise CotaEsgotada(texto)
    raise EnvioAcessoFalhou(texto)
