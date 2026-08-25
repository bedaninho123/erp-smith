"""Carrega configurações de integrações externas a partir do .env local.
Nunca imprimir/logar usuário/senha em lugar nenhum."""
import os

from dotenv import load_dotenv

load_dotenv()

SHOOTING_HOUSE_BASE_URL = os.getenv(
    "SHOOTING_HOUSE_BASE_URL", "https://apibeta.shootinghouse.com.br/v1/partners"
).rstrip("/")
SHOOTING_HOUSE_USER = os.getenv("SHOOTING_HOUSE_USER")
SHOOTING_HOUSE_PASSWORD = os.getenv("SHOOTING_HOUSE_PASSWORD")
# Chave geral, separada da credencial de propósito (2026-08-25). Antes
# disso, a simples presença de usuário/senha no .env colocava o sistema
# INTEIRO em modo real de uma vez -- inclusive o poller, que roda a cada
# 2 min pela Tarefa Agendada do Windows. Ou seja: não existia como
# guardar a credencial e conferir uma resposta antes, sem já estar
# atendendo cliente de verdade com ela. Agora a credencial pode ficar
# parada no .env, e o modo real só liga com SHOOTING_HOUSE_ATIVO=Sim.
#
# É também o botão de pânico: suspeita de problema na integração, põe
# vazio aqui e o sistema volta pro simulado sem precisar apagar a
# credencial nem mexer em código.
SHOOTING_HOUSE_ATIVO = (os.getenv("SHOOTING_HOUSE_ATIVO") or "").strip().lower() in (
    "sim", "true", "1",
)


def shooting_house_credencial_presente() -> bool:
    """Só diz se usuário e senha existem no .env -- NÃO significa que o
    sistema está consultando de verdade. Quem responde isso é
    shooting_house_ativo(). Usado pelo diagnóstico, que precisa da
    credencial mesmo com a chave geral desligada."""
    return bool(SHOOTING_HOUSE_USER and SHOOTING_HOUSE_PASSWORD)


def validar_base_url() -> None:
    """A autenticação da API do Shooting House é Basic Auth: usuário e
    senha viajam em toda chamada, só embrulhados em base64 -- que NÃO é
    criptografia, é só uma forma de escrever. Sem HTTPS, qualquer um no
    caminho da rede lê a credencial em texto claro e passa a consultar o
    CPF de qualquer atirador do clube.

    Por isso isto falha alto, na cara, em vez de deixar passar: é o tipo
    de erro que ninguém percebe olhando a tela, porque o sistema
    continua funcionando normalmente enquanto vaza."""
    if not SHOOTING_HOUSE_BASE_URL.lower().startswith("https://"):
        raise RuntimeError(
            "SHOOTING_HOUSE_BASE_URL precisa começar com https:// -- a credencial "
            "do Shooting House viaja em toda chamada e sem HTTPS ela vai em texto "
            f"claro. Valor configurado: {SHOOTING_HOUSE_BASE_URL!r}"
        )


def shooting_house_ativo() -> bool:
    """Modo real ligado = credencial presente E chave geral ligada E URL
    em HTTPS. Qualquer um dos três faltando mantém tudo no simulado."""
    if not (shooting_house_credencial_presente() and SHOOTING_HOUSE_ATIVO):
        return False
    validar_base_url()
    return True


# WhatsApp Business Cloud API (Meta). Sem estas variáveis, integracoes/
# whatsapp.py entra em modo simulado -- ver o cabeçalho daquele módulo
# antes de preencher: migrar o número para a API o tira do aplicativo
# WhatsApp Business do celular, é decisão sem volta fácil.
WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
# Segredo que a Meta ecoa ao validar o webhook (GET /webhook/whatsapp) e
# a chave usada para assinar cada POST (X-Hub-Signature-256). São dois
# valores diferentes e ambos vêm do painel de app da Meta.
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")


def whatsapp_configurado() -> bool:
    return bool(WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID)
