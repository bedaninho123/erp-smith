"""Monitor de saúde (2026-10-14): core/saude.py e a rota /saude do painel.

A leitura de e-mail ficou quase dois meses parada com o site no ar. O
que está guardado aqui: a rotina só conta como viva quando o Gmail
respondeu de verdade; subida recente não dispara alarme; prazo vencido
dispara; e a rota pública não mostra nada além de "ok"/"falha" por parte.
"""
import time

import pytest

from core import saude

AGORA = 1_000_000.0


@pytest.fixture(autouse=True)
def _saude_zerada(monkeypatch):
    monkeypatch.setattr(saude, "_batidas", {})
    monkeypatch.setattr(saude, "_inicio", AGORA)


def test_recem_subido_e_aguardando_nao_falha():
    assert saude.avaliar(agora=AGORA + 60) == {
        "email": "aguardando", "backup": "aguardando", "documentos_drive": "aguardando",
    }


def test_email_que_nunca_rodou_vira_atrasado_depois_do_prazo():
    estado = saude.avaliar(agora=AGORA + saude.LIMITES_SEGUNDOS["email"] + 1)

    assert estado["email"] == "atrasado"
    assert estado["backup"] == "aguardando"


def test_batida_recente_e_ok_e_batida_velha_e_atrasado(monkeypatch):
    saude._batidas["email"] = AGORA
    saude._batidas["backup"] = AGORA

    assert saude.avaliar(agora=AGORA + 60)["email"] == "ok"
    assert saude.avaliar(agora=AGORA + saude.LIMITES_SEGUNDOS["email"] + 1)["email"] == "atrasado"
    assert saude.avaliar(agora=AGORA + 25 * 3600)["backup"] == "ok"
    assert saude.avaliar(agora=AGORA + 27 * 3600)["backup"] == "atrasado"


# --------------------------------------------------------------------
# O batimento do e-mail só vem com o Gmail respondendo
# --------------------------------------------------------------------

@pytest.fixture
def poller(monkeypatch):
    from atendimento import poller as modulo

    monkeypatch.setattr(modulo, "gmail_configurado", lambda: True)
    monkeypatch.setattr(modulo, "alertar_excecao", lambda *a, **k: None)
    return modulo


def test_gmail_respondendo_registra_o_batimento(poller, monkeypatch):
    monkeypatch.setattr(poller, "listar_mensagens_nao_lidas", lambda: [])

    poller._verificar_uma_vez_com_trava()

    assert "email" in saude._batidas


def test_gmail_quebrado_nao_registra(poller, monkeypatch):
    """O caso de julho: token vencido, rotina rodando, caixa sem ler."""
    def _token_vencido():
        raise RuntimeError("invalid_grant")
    monkeypatch.setattr(poller, "listar_mensagens_nao_lidas", _token_vencido)

    with pytest.raises(RuntimeError):
        poller._verificar_uma_vez_com_trava()

    assert "email" not in saude._batidas


def test_gmail_nao_autorizado_nao_registra(poller, monkeypatch):
    monkeypatch.setattr(poller, "gmail_configurado", lambda: False)

    poller._verificar_uma_vez_com_trava()

    assert "email" not in saude._batidas


# --------------------------------------------------------------------
# A rota pública
# --------------------------------------------------------------------

@pytest.fixture
def anonimo(banco):
    from webapp.app import app

    app.config.update(TESTING=True)
    return app.test_client()


def test_tudo_bem_responde_200_sem_login(anonimo, monkeypatch):
    monkeypatch.setattr(saude, "_inicio", time.time())

    resposta = anonimo.get("/saude")

    assert resposta.status_code == 200
    assert resposta.get_json() == {
        "status": "ok",
        "partes": {"email": "aguardando", "backup": "aguardando",
                   "documentos_drive": "aguardando", "banco": "ok"},
    }


def test_email_parado_responde_503(anonimo, monkeypatch):
    """É o código que o monitor gratuito enxerga -- 200 com 'falha' no
    texto passaria despercebido."""
    monkeypatch.setattr(saude, "_inicio", 0)

    resposta = anonimo.get("/saude")

    assert resposta.status_code == 503
    assert resposta.get_json()["partes"]["email"] == "atrasado"


def test_saude_nao_mostra_nada_alem_do_estado(anonimo):
    corpo = anonimo.get("/saude").get_json()

    assert set(corpo) == {"status", "partes"}
    assert set(corpo["partes"].values()) <= {"ok", "aguardando", "atrasado", "falha"}
