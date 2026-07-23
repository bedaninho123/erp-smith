"""Avisa o administrador por e-mail quando algo falha no poller/webhook.
Sem isso, uma falha silenciosa (chave da OpenAI expirada, Gmail sem
acesso, banco travado etc.) só seria percebida por acaso -- foi
exatamente esse tipo de "silêncio sem explicação" que já causou
confusão antes (ver bug do remetente desconhecido).

Não manda alerta repetido da mesma falha com muita frequência -- guarda
o horário do último alerta de cada tipo num arquivo local (não banco,
pra funcionar mesmo se o problema for justamente o banco).
"""
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from atendimento.config import ALERTA_EMAIL

INTERVALO_MINIMO_MINUTOS = 30
_ESTADO_PATH = Path(__file__).resolve().parent / "ultimo_alerta.json"


def _carregar_estado() -> dict:
    if _ESTADO_PATH.exists():
        try:
            return json.loads(_ESTADO_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _salvar_estado(estado: dict) -> None:
    _ESTADO_PATH.write_text(json.dumps(estado), encoding="utf-8")


def alertar_falha(titulo: str, detalhe: str) -> None:
    """Registra a falha no log e, se configurado, manda e-mail -- no
    máximo um alerta do mesmo título a cada INTERVALO_MINIMO_MINUTOS,
    pra não inundar a caixa de entrada se o mesmo problema persistir."""
    agora = datetime.now(timezone.utc)
    estado = _carregar_estado()
    ultimo_iso = estado.get(titulo)

    if ultimo_iso:
        ultimo = datetime.fromisoformat(ultimo_iso)
        if agora - ultimo < timedelta(minutes=INTERVALO_MINIMO_MINUTOS):
            print(f"[ALERTA suprimido -- já avisado recentemente] {titulo}: {detalhe}")
            return

    print(f"[ALERTA] {titulo}: {detalhe}")

    if not ALERTA_EMAIL:
        return

    try:
        # Import tardio para evitar dependência circular e para o
        # alerta ainda funcionar (localmente, via log) mesmo se o
        # próprio módulo do Gmail for a causa da falha.
        from integracoes.gmail import enviar_email, gmail_configurado

        if not gmail_configurado():
            return

        enviar_email(
            ALERTA_EMAIL,
            assunto=f"[ERP Smith] Alerta: {titulo}",
            corpo=f"{detalhe}\n\nHorário: {agora.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        )
    except Exception:
        print("[ALERTA] Falha ao enviar o próprio alerta por e-mail:")
        traceback.print_exc()
        return  # não marca como avisado -- tenta de novo na próxima falha

    estado[titulo] = agora.isoformat()
    _salvar_estado(estado)


def alertar_excecao(titulo: str, excecao: Exception) -> None:
    alertar_falha(titulo, f"{type(excecao).__name__}: {excecao}")
