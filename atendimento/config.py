"""Carrega configuração do endpoint de Atendimento a partir do .env
local. Nunca imprimir/logar o valor de WEBHOOK_SECRET."""
import os

from dotenv import load_dotenv

load_dotenv()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

# De qual empresa é o e-mail que entra por estes canais
# (docs/schema_multi_tenant.md §6). Hoje o sistema vigia UMA caixa do
# Gmail, com um token.json só -- ou seja, esta instalação atende uma
# empresa. Quando cada empresa tiver a credencial dela, o poller passa a
# percorrer as empresas e esta variável vira o padrão de quem não
# informou nada, não a resposta única.
#
# Por que não vem do corpo da requisição no webhook: o único
# autenticador de lá é um segredo compartilhado. Se o chamador pudesse
# escolher a empresa, quem tem o segredo escreveria dado em qualquer uma
# delas. A empresa é configuração do servidor, não entrada do cliente.
EMPRESA_ID = os.getenv("ERP_EMPRESA_ID", "EMP-000001")

# Para onde mandar alerta quando o poller/webhook falhar (ver
# atendimento/alertas.py). Sem isso configurado, os alertas só ficam
# no log local (atendimento/poller.log), sem e-mail.
ALERTA_EMAIL = os.getenv("ALERTA_EMAIL")
