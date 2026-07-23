"""Envio e leitura de e-mails via API do Gmail (fecha a Fase 4 do
PROJETO_1.md: substitui a necessidade do Make tanto para enviar quanto
para receber mensagens).

Requer duas coisas que só o usuário pode configurar (login do Google,
não é uma chave simples):
  1. credentials.json na raiz do projeto -- baixado do Google Cloud
     Console (ver integracoes/gmail_autorizar.py para o passo a passo).
  2. token.json na raiz do projeto -- gerado rodando
     `python -m integracoes.gmail_autorizar`, que abre o navegador para
     você autorizar o acesso à sua conta. Se o escopo mudou desde a
     última vez (ex.: agora inclui leitura), é preciso rodar de novo --
     o token antigo não tem a permissão nova.

Nenhum dos dois arquivos é commitado (estão no .gitignore).
"""
import base64
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]
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


def _extrair_corpo(payload: dict) -> str:
    """Extrai o texto simples de uma mensagem, mesmo quando ela vem em
    partes (multipart/alternative com HTML + texto, anexos etc.)."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for parte in payload.get("parts", []) or []:
        texto = _extrair_corpo(parte)
        if texto:
            return texto
    return ""


def _cabecalho(headers: list[dict], nome: str) -> str:
    for h in headers:
        if h["name"].lower() == nome.lower():
            return h["value"]
    return ""


def obter_email_proprio() -> str:
    creds = _obter_credenciais()
    service = build("gmail", "v1", credentials=creds)
    return service.users().getProfile(userId="me").execute()["emailAddress"].lower()


def listar_mensagens_nao_lidas(max_resultados: int = 10) -> list[dict]:
    """Lista mensagens não lidas na caixa de entrada, já com remetente,
    assunto e corpo extraídos -- prontas para o orquestrador processar.

    Mensagens vindas do próprio e-mail da conta (ex.: uma resposta
    automática que caiu na própria caixa de entrada, comum só em teste
    onde remetente e destinatário são a mesma conta) são ignoradas e
    marcadas como lidas sem processar -- evita loop de auto-resposta.
    """
    creds = _obter_credenciais()
    service = build("gmail", "v1", credentials=creds)
    email_proprio = obter_email_proprio()

    resultado = service.users().messages().list(
        userId="me", q="is:unread in:inbox", maxResults=max_resultados
    ).execute()

    mensagens = []
    for item in resultado.get("messages", []):
        msg = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
        headers = msg["payload"].get("headers", [])
        remetente_bruto = _cabecalho(headers, "From")
        # "Nome Sobrenome <email@dominio.com>" -> só o e-mail
        email = remetente_bruto.split("<")[-1].replace(">", "").strip() if "<" in remetente_bruto else remetente_bruto.strip()

        if email.lower() == email_proprio:
            marcar_como_lida(msg["id"])
            continue

        mensagens.append({
            "id": msg["id"],
            "thread_id": msg["threadId"],
            "remetente_email": email,
            "assunto": _cabecalho(headers, "Subject"),
            "corpo": _extrair_corpo(msg["payload"]).strip(),
        })
    return mensagens


def marcar_como_lida(message_id: str) -> None:
    creds = _obter_credenciais()
    service = build("gmail", "v1", credentials=creds)
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


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
