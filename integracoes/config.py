"""Carrega configurações de integrações externas a partir do .env local.
Nunca imprimir/logar usuário/senha em lugar nenhum."""
import os

from dotenv import load_dotenv

load_dotenv()

SHOOTING_HOUSE_BASE_URL = os.getenv(
    "SHOOTING_HOUSE_BASE_URL", "https://apibeta.shootinghouse.com.br/v1/partners"
)
SHOOTING_HOUSE_USER = os.getenv("SHOOTING_HOUSE_USER")
SHOOTING_HOUSE_PASSWORD = os.getenv("SHOOTING_HOUSE_PASSWORD")


def shooting_house_configurado() -> bool:
    return bool(SHOOTING_HOUSE_USER and SHOOTING_HOUSE_PASSWORD)
