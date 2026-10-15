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

MULTI-TENANT, e este é o ponto mais frágil da migração inteira
(docs/schema_multi_tenant.md §6, item de peso "Alto"): hoje existe UMA
caixa de Gmail e UM token.json, então tudo que chega aqui é da empresa
de atendimento/config.py::EMPRESA_ID. Quando cada empresa tiver a
credencial dela, este módulo passa a percorrer as empresas -- uma
listagem de caixa de entrada por empresa, cada uma com o seu
empresa_id -- em vez de assumir uma só. Enquanto isso não existe, é
melhor a suposição estar escrita aqui do que embutida sem aviso.
"""
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from core import saude
from core.motor_clientes import remetente_automatico
from integracoes.gmail import gmail_configurado, listar_mensagens_nao_lidas, marcar_como_lida
from atendimento.alertas import alertar_excecao, alertar_falha
from atendimento.config import EMPRESA_ID
from atendimento.processar import processar_mensagem
from core.motor_casos import localizar_caso_aberto
from core.motor_documentos import salvar_documento

INTERVALO_SEGUNDOS = 60
LOG_PATH = Path(__file__).resolve().parent / "poller.log"
LOCK_PATH = Path(__file__).resolve().parent / "poller.lock"
# Se a Tarefa Agendada (a cada 2 min) e uma execução manual (verificar_
# agora.bat, ou terminal aberto) coincidirem, as duas listam e-mails não
# lidos antes de qualquer uma marcar como lido -- processam a mesma
# mensagem duas vezes. Trava de arquivo simples evita isso; acima deste
# tempo, considera que o processo anterior travou/morreu sem limpar e
# libera sozinho (em vez de travar o poller pra sempre).
TRAVA_EXPIRA_SEGUNDOS = 300


def _adquirir_trava() -> bool:
    if LOCK_PATH.exists():
        idade = time.time() - LOCK_PATH.stat().st_mtime
        if idade >= TRAVA_EXPIRA_SEGUNDOS:
            LOCK_PATH.unlink(missing_ok=True)
    try:
        with open(LOCK_PATH, "x", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False


def _liberar_trava() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def _salvar_anexos(empresa_id: str, msg: dict, resultado: dict, anexos: list) -> None:
    """Vincula os anexos (já filtrados por foto/PDF em integracoes/gmail.py)
    ao caso do cliente. Nunca deixa um anexo desaparecer em silêncio: se
    não dá pra achar cliente/caso pra vincular (restrição do banco --
    documento exige caso_id ou processo_id), alerta em vez de tentar
    gravar e falhar, ou pior, gravar errado.
    """
    cliente_id = resultado.get("cliente_id")
    nomes = ", ".join(a["nome_arquivo"] for a in anexos)

    if not cliente_id:
        alertar_falha(
            f"Anexo recebido de remetente não identificado ({msg['remetente_email']})",
            f"{len(anexos)} arquivo(s) não foram salvos, precisa tratar manualmente: {nomes}",
        )
        return

    caso_id = resultado.get("caso_id") or localizar_caso_aberto(empresa_id, cliente_id)
    if not caso_id:
        alertar_falha(
            f"Anexo recebido sem caso aberto para associar (cliente {cliente_id})",
            f"{len(anexos)} arquivo(s) não foram salvos, precisa tratar manualmente: {nomes}",
        )
        return

    for anexo in anexos:
        try:
            documento_id = salvar_documento(
                empresa_id,
                cliente_id=cliente_id,
                conteudo=anexo["conteudo"],
                nome_arquivo_original=anexo["nome_arquivo"],
                caso_id=caso_id,
                mensagem_id=resultado.get("mensagem_id"),
                observacoes=f"Recebido por e-mail de {msg['remetente_email']} -- assunto: {msg['assunto']!r}",
            )
            print(f"  -> anexo salvo: {documento_id} ({anexo['nome_arquivo']})")
        except Exception as e:
            alertar_excecao(f"Falha ao salvar anexo {anexo['nome_arquivo']!r} do cliente {cliente_id}", e)


def verificar_uma_vez() -> int:
    if not _adquirir_trava():
        print(
            "Outra verificação já está em andamento (Tarefa Agendada ou "
            "outro terminal) -- pulando esta rodada pra não processar o "
            "mesmo e-mail duas vezes."
        )
        return 0
    try:
        return _verificar_uma_vez_com_trava()
    finally:
        _liberar_trava()


def _verificar_uma_vez_com_trava() -> int:
    if not gmail_configurado():
        print("Gmail ainda não autorizado -- nada para verificar.")
        return 0

    try:
        mensagens = listar_mensagens_nao_lidas()
    except Exception as e:
        alertar_excecao("Falha ao consultar a caixa de entrada", e)
        raise
    # Batimento só depois de o Gmail responder de verdade: é o que separa
    # "a rotina está rodando" de "a caixa está sendo lida" (core/saude.py).
    saude.registrar("email")

    for msg in mensagens:
        if remetente_automatico(msg["remetente_email"]):
            # Alerta de segurança do Google, aviso de sistema, devolução:
            # ninguém lê a resposta. Antes, a IA respondia a eles mesmo
            # assim (2026-10-07: dois "Alerta de segurança" da conta nova
            # viraram rascunho de resposta). Continuam na caixa do Gmail.
            print(f"Ignorado (remetente automático) {msg['remetente_email']}: {msg['assunto']!r}")
            marcar_como_lida(msg["id"])
            continue
        print(f"Processando e-mail de {msg['remetente_email']}: {msg['assunto']!r}")
        try:
            resultado = processar_mensagem(
                EMPRESA_ID,
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

        if msg.get("anexos"):
            _salvar_anexos(EMPRESA_ID, msg, resultado, msg["anexos"])

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
