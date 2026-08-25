"""Envio e recebimento de mensagem por WhatsApp via Meta Cloud API
(https://developers.facebook.com/docs/whatsapp/cloud-api).

MODO SIMULADO, igual a integracoes/shooting_house.py: enquanto
WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID não estão no .env, `enviar_
mensagem` não chama a Meta -- grava o que TERIA sido enviado em
integracoes/whatsapp_simulado.log e devolve sucesso. Isso permite testar
a tela de Atendimentos e o pipeline inteiro sem depender de migrar o
número do clube para a API.

POR QUE ISSO IMPORTA AQUI MAIS DO QUE NO SHOOTING HOUSE -- ler antes de
configurar as credenciais:

1. O WhatsApp Business (o aplicativo) NÃO tem API. Para o sistema mandar
   mensagem, o número precisa ser migrado para a Cloud API, e ao migrar
   ele SAI do aplicativo: não dá para ter os dois no mesmo número. Todo
   atendimento passa a acontecer por aqui.
2. A Meta entrega mensagem recebida via webhook HTTPS público. Enquanto
   o sistema roda em localhost com port-forward (decisão de 2026-07-25,
   docs/portal_cliente_arquitetura.md §4), não há endereço para ela
   chamar -- receber exige resolver hospedagem antes.
3. Janela de 24h: fora de 24h da última mensagem do cliente, a Meta só
   aceita template previamente aprovado por ela, não texto livre. Por
   isso `enviar_mensagem` distingue os dois casos e falha alto em vez de
   deixar a mensagem sumir em silêncio.

Bibliotecas não-oficiais que automatizam o WhatsApp Web (whatsapp-web.js
e afins) ficaram deliberadamente de fora: violam os termos da Meta e o
risco é o número do clube ser banido -- caro demais num negócio real com
um número só.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from integracoes.config import (
    WHATSAPP_API_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
    WHATSAPP_TOKEN,
    whatsapp_configurado,
)

# Log do modo simulado. Fica em arquivo (não no banco) de propósito: é
# registro de desenvolvimento, não dado de negócio -- e precisa funcionar
# mesmo se o banco for justamente o que estiver com problema, mesmo
# raciocínio de atendimento/ultimo_alerta.json.
LOG_SIMULADO = Path(__file__).resolve().parent / "whatsapp_simulado.log"

TIMEOUT_SEGUNDOS = 20


def normalizar_telefone(numero: str) -> str:
    """Só dígitos, com DDI 55 na frente -- é o formato que a Meta espera
    (`5514999998888`). Mesmo princípio do CPF do cliente, que o banco
    guarda sem pontuação: comparar telefone formatado de jeitos
    diferentes é fonte garantida de "cliente não encontrado".

    Número brasileiro sem DDI (10 ou 11 dígitos) ganha o 55. Número que
    já venha com DDI é devolvido como está -- não dá para saber se um
    número de 12 dígitos é estrangeiro ou brasileiro mal digitado, e
    reescrever o de outro país seria pior que não mexer.
    """
    digitos = re.sub(r"\D", "", numero or "")
    if len(digitos) in (10, 11):
        return f"55{digitos}"
    return digitos


def _registrar_simulado(destino: str, texto: str, tipo: str) -> None:
    LOG_SIMULADO.parent.mkdir(parents=True, exist_ok=True)
    with LOG_SIMULADO.open("a", encoding="utf-8") as arquivo:
        arquivo.write(
            json.dumps(
                {
                    "quando": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "destino": destino,
                    "tipo": tipo,
                    "texto": texto,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def enviar_mensagem(
    telefone: str, texto: str, template: Optional[str] = None,
) -> dict:
    """Manda uma mensagem de texto. Devolve `{"simulado": bool, "id": ...}`.

    `template` só é usado no modo real e fora da janela de 24h -- precisa
    ser o nome de um template já aprovado pela Meta. Sem ele, a API
    recusa a mensagem, e essa recusa vira exceção aqui em vez de um
    "enviado" mentiroso.
    """
    destino = normalizar_telefone(telefone)
    if not destino:
        raise ValueError("Telefone de destino vazio ou inválido.")
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("Texto da mensagem está vazio -- nada para enviar.")

    if not whatsapp_configurado():
        _registrar_simulado(destino, texto, "template" if template else "texto")
        return {"simulado": True, "id": None, "destino": destino}

    url = (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/"
        f"{WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    if template:
        corpo = {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "template",
            "template": {"name": template, "language": {"code": "pt_BR"}},
        }
    else:
        corpo = {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "text",
            "text": {"preview_url": False, "body": texto},
        }

    resposta = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        },
        json=corpo,
        timeout=TIMEOUT_SEGUNDOS,
    )
    if resposta.status_code >= 400:
        # Mensagem de erro da Meta vai inteira para quem chamou: o caso
        # comum aqui é "fora da janela de 24h, use template", e sem o
        # texto original ninguém descobriria isso olhando um 400 seco.
        raise RuntimeError(
            f"WhatsApp recusou o envio (HTTP {resposta.status_code}): {resposta.text[:500]}"
        )

    dados = resposta.json()
    identificador = (dados.get("messages") or [{}])[0].get("id")
    return {"simulado": False, "id": identificador, "destino": destino}


def extrair_mensagens(corpo: dict) -> list[dict]:
    """Traduz o payload de webhook da Meta para a forma simples que
    atendimento/processar.py já entende.

    O formato da Meta é aninhado fundo (entry → changes → value →
    messages) e traz também eventos que NÃO são mensagem de cliente --
    confirmação de entrega, de leitura, mudança de status. Esses são
    ignorados aqui: processá-los como se fossem pergunta de cliente
    geraria atendimento fantasma (mesma classe do bug de auto-resposta
    do poller de e-mail, 2026-07-23).
    """
    encontradas: list[dict] = []
    for entrada in corpo.get("entry", []) or []:
        for mudanca in entrada.get("changes", []) or []:
            valor = mudanca.get("value", {}) or {}
            # Nome de exibição do remetente, quando a Meta manda -- mesmo
            # motivo do remetente_nome do e-mail: sem ele a resposta sai
            # com "Olá Cliente" genérico para quem não está cadastrado.
            perfis = {
                contato.get("wa_id"): (contato.get("profile") or {}).get("name")
                for contato in (valor.get("contacts") or [])
            }
            for msg in valor.get("messages", []) or []:
                if msg.get("type") != "text":
                    # Áudio, imagem, documento e figurinha ainda não são
                    # tratados. Entram na lista assim mesmo, com texto
                    # vazio e o tipo preservado, para quem chamou decidir
                    # o que fazer -- descartar aqui em silêncio repetiria
                    # o erro do e-mail HTML-only, que fazia o cliente
                    # ficar sem resposta nenhuma sem ninguém saber.
                    encontradas.append({
                        "id_externo": msg.get("id"),
                        "telefone": msg.get("from"),
                        "nome": perfis.get(msg.get("from")),
                        "texto": "",
                        "tipo": msg.get("type"),
                        "suportado": False,
                    })
                    continue
                encontradas.append({
                    "id_externo": msg.get("id"),
                    "telefone": msg.get("from"),
                    "nome": perfis.get(msg.get("from")),
                    "texto": (msg.get("text") or {}).get("body", ""),
                    "tipo": "text",
                    "suportado": True,
                })
    return encontradas


def status_integracao() -> dict:
    """Resumo para a tela de Status do Projeto e para o cabeçalho da tela
    de Atendimentos -- deixa explícito na interface que o WhatsApp está
    simulado, em vez de o usuário descobrir isso quando um cliente real
    não receber resposta."""
    return {
        "configurado": whatsapp_configurado(),
        "modo": "Real (Meta Cloud API)" if whatsapp_configurado() else "Simulado",
        "log_simulado": str(LOG_SIMULADO) if not whatsapp_configurado() else None,
    }


if __name__ == "__main__":
    print(f"Status: {status_integracao()}")
    print(f"Normalização: '(14) 99999-8888' -> {normalizar_telefone('(14) 99999-8888')}")
    print(f"Normalização: '5514999998888'   -> {normalizar_telefone('5514999998888')}")
    resultado = enviar_mensagem("(14) 99999-8888", "Teste de fumaça do módulo WhatsApp.")
    print(f"Envio: {resultado}")
    if resultado["simulado"]:
        print(f"(gravado em {LOG_SIMULADO})")
