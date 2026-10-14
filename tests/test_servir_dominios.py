"""Um endereço para cada app (webapp/servir.py, 2026-10-14).

Em produção o mesmo processo atende painel e Portal. Com domínio próprio,
quem escolhe o app é o endereço digitado. O que não pode acontecer:
cliente chegar à tela de login da equipe pelo endereço do Portal, e o
endereço antigo (*.up.railway.app) parar de funcionar -- e-mail já
enviado e a política de privacidade cadastrada no Google apontam pra ele.
"""
import pytest
from werkzeug.test import Client

from webapp import servir

PORTAL = "portal.smithclubedetiro.com.br"
PAINEL = "painel.smithclubedetiro.com.br"
ANTIGO = "erp-smith-painel-production.up.railway.app"


@pytest.fixture
def servidor(banco, monkeypatch):
    monkeypatch.setattr(servir, "PORTAL_HOST", PORTAL)
    monkeypatch.setattr(servir, "PAINEL_HOST", PAINEL)
    return Client(servir._despachar_por_prefixo)


def test_endereco_do_portal_abre_o_portal(servidor):
    resposta = servidor.get("/portal/login", headers={"Host": PORTAL})

    assert resposta.status_code == 200
    assert "Portal do Cliente" in resposta.get_data(as_text=True)


def test_raiz_do_portal_leva_ao_login_do_portal(servidor):
    resposta = servidor.get("/", headers={"Host": PORTAL})

    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/portal/login")


def test_painel_nao_existe_no_endereco_do_portal(servidor):
    """A tela de login da equipe não pode ser alcançada por quem só
    conhece o endereço que os clientes usam."""
    resposta = servidor.get("/login", headers={"Host": PORTAL})

    assert resposta.status_code == 404


def test_endereco_do_painel_abre_o_painel(servidor):
    resposta = servidor.get("/login", headers={"Host": PAINEL})

    assert resposta.status_code == 200
    assert "Portal do Cliente" not in resposta.get_data(as_text=True)


def test_portal_pelo_endereco_do_painel_vai_pro_endereco_certo(servidor):
    resposta = servidor.get("/portal/entrar/abc?x=1", headers={"Host": PAINEL})

    assert resposta.status_code == 302
    assert resposta.headers["Location"] == f"https://{PORTAL}/portal/entrar/abc?x=1"


def test_endereco_antigo_continua_dividido_pelo_prefixo(servidor):
    portal = servidor.get("/portal/login", headers={"Host": ANTIGO})
    painel = servidor.get("/login", headers={"Host": ANTIGO})

    assert "Portal do Cliente" in portal.get_data(as_text=True)
    assert painel.status_code == 200 and "Portal do Cliente" not in painel.get_data(as_text=True)


def test_host_vem_do_proxy_do_railway(servidor):
    """A borda do Railway pode repassar o endereço digitado em
    X-Forwarded-Host; é ele que vale."""
    resposta = servidor.get("/login", headers={"Host": "interno:8080", "X-Forwarded-Host": PORTAL})

    assert resposta.status_code == 404


def test_sem_configuracao_tudo_fica_como_antes(banco, monkeypatch):
    monkeypatch.setattr(servir, "PORTAL_HOST", "")
    monkeypatch.setattr(servir, "PAINEL_HOST", "")
    servidor = Client(servir._despachar_por_prefixo)

    assert "Portal do Cliente" in servidor.get("/portal/login", headers={"Host": PORTAL}).get_data(as_text=True)
    assert servidor.get("/login", headers={"Host": PORTAL}).status_code == 200
