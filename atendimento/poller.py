"""Verifica periodicamente a caixa de entrada por e-mails novos e
processa cada um pelo mesmo Motor que o webhook usa (atendimento.processar)
-- fecha o ciclo de entrada sem depender de chamada manual nem do Make.

Usa polling (checar a cada X segundos), não notificação push -- push via
Google Cloud Pub/Sub exigiria um servidor público, que este projeto
ainda não tem. Simples e suficiente para o estágio atual.

Toda mensagem verificada é marcada como lida, para nunca ser processada
duas vezes -- mesmo quando o resultado foi "encaminhar a humano" ou
"revisar" (nesses casos a mensagem já foi registrada no caso/sessão;
alguém ainda precisa olhar, mas não faz sentido o robô ficar reprocessando).
"""
import time

from integracoes.gmail import gmail_configurado, listar_mensagens_nao_lidas, marcar_como_lida
from atendimento.processar import processar_mensagem

INTERVALO_SEGUNDOS = 60


def verificar_uma_vez() -> int:
    if not gmail_configurado():
        print("Gmail ainda não autorizado -- nada para verificar.")
        return 0

    mensagens = listar_mensagens_nao_lidas()
    for msg in mensagens:
        print(f"Processando e-mail de {msg['remetente_email']}: {msg['assunto']!r}")
        resultado = processar_mensagem(
            texto=msg["corpo"],
            canal="Email",
            assunto=msg["assunto"],
            remetente_email=msg["remetente_email"],
        )
        if resultado.get("erro"):
            print(f"  -> erro: {resultado['erro']}")
        else:
            print(f"  -> intenção: {resultado.get('intencao')}, ação: {resultado.get('acao')}, "
                  f"enviado: {resultado.get('email_enviado')}")

        marcar_como_lida(msg["id"])

    return len(mensagens)


def loop():
    print(f"Verificando e-mails novos a cada {INTERVALO_SEGUNDOS}s. Ctrl+C para parar.")
    while True:
        n = verificar_uma_vez()
        if n:
            print(f"{n} mensagem(ns) processada(s) nesta rodada.")
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    loop()
