"""Carrega configuração do endpoint de Atendimento a partir do .env
local. Nunca imprimir/logar o valor de WEBHOOK_SECRET."""
import os

from dotenv import load_dotenv

load_dotenv()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
