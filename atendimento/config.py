"""Carrega configuração do endpoint de Atendimento a partir do .env
local. Nunca imprimir/logar o valor de WEBHOOK_SECRET."""
import os

from dotenv import load_dotenv

load_dotenv()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# Para onde mandar alerta quando o poller/webhook falhar (ver
# atendimento/alertas.py). Sem isso configurado, os alertas só ficam
# no log local (atendimento/poller.log), sem e-mail.
ALERTA_EMAIL = os.getenv("ALERTA_EMAIL")
