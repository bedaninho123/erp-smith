"""Carrega configurações de ambiente (chaves, segredos) a partir do .env
local. Nunca imprimir/logar o valor de OPENAI_API_KEY em lugar nenhum."""
import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def chave_configurada() -> bool:
    return bool(OPENAI_API_KEY)
