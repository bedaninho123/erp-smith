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
import sys
import time
from datetime import datetime
from pathlib import Path

from integracoes.gmail import gmail_configurado, listar_mensagens_nao_lidas, marcar_como_lida
from atendimento.alertas import alertar_excecao, alertar_falha
from atendimento.processar import processar_mensagem

INTERVALO_SEGUNDOS = 60
LOG_PATH = Path(__file__).resolve().parent / "poller.log"


def verificar_uma_vez() -> int:
    if not gmail_configurado():
        print("Gmail ainda não autorizado -- nada para verificar.")
        return 0

    try:
        mensagens = listar_mensagens_nao_lidas()
    except Exception as e:
        alertar_excecao("Falha ao consultar a caixa de entrada", e)
        raise

    for msg in mensagens:
        print(f"Processando e-mail de {msg['remetente_email']}: {msg['assunto']!r}")
        try:
            resultado = processar_mensagem(
                texto=msg["corpo"],
                canal="Email",
                assunto=msg["assunto"],
                remetente_email=msg["remetente_email"],
                remetente_nome=msg.get("remetente_nome"),
            )
        except Exception as e:
            alertar_excecao(
                f"Falha ao processar e-mail de {msg['remetente_email']}", e
            )
            # Não marca como lida -- fica pra tentar de novo na próxima
            # rodada, em vez de perder a mensagem por causa de uma
            # falha temporária (ex.: OpenAI fora do ar por um instante).
            continue

        if resultado.get("erro"):
            print(f"  -> erro: {resultado['erro']}")
            alertar_falha(
                f"Erro ao responder e-mail de {msg['remetente_email']}",
                resultado["erro"],
            )
        else:
            print(f"  -> intenção: {resultado.get('intencao')}, ação: {resultado.get('acao')}, "
                  f"enviado: {resultado.get('email_enviado')}")
            if resultado.get("erro_envio"):
                alertar_falha(
                    "Resposta gerada mas falhou ao enviar",
                    f"Cliente {resultado.get('cliente_id')}: {resultado['erro_envio']}",
                )

        marcar_como_lida(msg["id"])

    return len(mensagens)


def loop():
    print(f"Verificando e-mails novos a cada {INTERVALO_SEGUNDOS}s. Ctrl+C para parar.")
    while True:
        try:
            n = verificar_uma_vez()
            if n:
                print(f"{n} mensagem(ns) processada(s) nesta rodada.")
        except Exception as e:
            # Uma falha numa rodada não deve derrubar o loop pra sempre
            # -- o alerta já foi enviado dentro de verificar_uma_vez();
            # aqui só evita que o processo morra e pare de tentar.
            print(f"Falha nesta rodada, tentando de novo em {INTERVALO_SEGUNDOS}s: {e}")
        time.sleep(INTERVALO_SEGUNDOS)


if __name__ == "__main__":
    # --uma-vez: verifica uma vez e sai (usado pela Tarefa Agendada do
    # Windows, que já cuida de repetir a cada N minutos sozinha -- rodar
    # o loop() infinito dentro de uma tarefa agendada duplicaria a
    # repetição). Sem esse argumento, roda o loop contínuo (uso manual,
    # terminal aberto).
    if "--uma-vez" in sys.argv:
        # A Tarefa Agendada chama pythonw.exe diretamente (sem cmd.exe/
        # batch no meio, pra não flashar janela nenhuma) -- por isso não
        # tem console, e sys.stdout/stderr chegam como None nesse caso.
        # Sem desviar pro arquivo, qualquer print() derrubaria o processo
        # com AttributeError. Quando roda manualmente num terminal de
        # verdade (verificar_agora.bat, ou python.exe direto), sys.stdout
        # já existe -- nesse caso deixa imprimir na tela normalmente, pra
        # dar feedback imediato de quem está rodando na hora.
        if sys.stdout is None:
            log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
            sys.stdout = log
            sys.stderr = log
            print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        n = verificar_uma_vez()
        print(f"{n} mensagem(ns) processada(s).")
    else:
        loop()
