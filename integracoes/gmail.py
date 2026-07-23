"""Envio de respostas por e-mail via API do Gmail (fecha a Fase 4 do
PROJETO_1.md: substitui a necessidade do Make para enviar a resposta de
volta ao cliente).

Requer duas coisas que só o usuário pode configurar (login do Google,
não é uma chave simples):
  1. credentials.json na raiz do projeto -- baixado do Google Cloud
     Console (ver integracoes/gmail_autorizar.py para o passo a passo).
  2. token.json na raiz do projeto -- gerado uma única vez rodando
     `python -m integracoes.gmail_autorizar`, que abre o navegador para
     você autorizar o acesso à sua conta.

Nenhum dos dois arquivos é commitado (estão no .gitignore).
"""
import base64
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_PATH = Path(__file__).resolve().parent.parent / "token.json"


def gmail_configurado() -> bool:
    return TOKEN_PATH.exists()


def _obter_credenciais() -> Credentials:
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            "token.json não encontrado. Rode primeiro: "
            "python -m integracoes.gmail_autorizar"
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def enviar_email(destinatario: str, assunto: str, corpo: str, em_resposta_a: str = None) -> str:
    """Envia um e-mail e devolve o id da mensagem enviada. em_resposta_a é
    o Message-ID do e-mail original, se disponível, para manter o e-mail
    na mesma thread da conversa."""
    creds = _obter_credenciais()
    service = build("gmail", "v1", credentials=creds)

    mensagem = MIMEText(corpo)
    mensagem["to"] = destinatario
    mensagem["subject"] = assunto
    if em_resposta_a:
        mensagem["In-Reply-To"] = em_resposta_a
        mensagem["References"] = em_resposta_a

    raw = base64.urlsafe_b64encode(mensagem.as_bytes()).decode("utf-8")
    enviado = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return enviado["id"]


if __name__ == "__main__":
    if not gmail_configurado():
        print("Gmail ainda não autorizado. Rode: python -m integracoes.gmail_autorizar")
    else:
        destinatario = input("E-mail de teste para enviar (ex.: você mesmo): ").strip()
        msg_id = enviar_email(
            destinatario,
            assunto="Teste do ERP Smith",
            corpo="Este é um e-mail de teste enviado pelo módulo integracoes/gmail.py.",
        )
        print(f"Enviado! ID da mensagem: {msg_id}")
