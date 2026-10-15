"""Cookie de sessão com SameSite=Lax nos dois apps (2026-10-14).

Sem a marcação, Safari e Firefox mandam o cookie de login também em POST
que vem de OUTRO site: uma página qualquer aberta por quem está logado
podia remover anúncio, enviar arquivo ou mexer em caso em nome da pessoa
(CSRF). O teste olha o cabeçalho de verdade que sai pro navegador, não
só a configuração -- é o cabeçalho que o navegador obedece.
"""
import core.motor_portal_auth as motor_auth
from core import limitador_tentativas


def _cookie(resposta, nome):
    return next(c for c in resposta.headers.getlist("Set-Cookie") if c.startswith(f"{nome}="))


def test_cookie_do_portal_sai_com_samesite_lax(banco, monkeypatch):
    from portal.app import app

    app.config.update(TESTING=True)
    limitador_tentativas._tentativas.clear()
    monkeypatch.setattr(motor_auth, "_gerar_codigo", lambda: "123456")
    cliente_http = app.test_client()

    cliente_http.post("/portal/login", data={"identificador": "111.111.111-11"})
    resposta = cliente_http.post("/portal/login/codigo", data={"codigo": "123456"})

    assert "SameSite=Lax" in _cookie(resposta, "portal_session")


def test_cookie_do_painel_sai_com_samesite_lax(banco):
    """Grava uma sessão pelo mesmo mecanismo que o login do painel usa e
    lê o cabeçalho que sairia -- sem depender de senha de usuário."""
    from flask import session

    from webapp.app import app

    with app.test_request_context("/login"):
        session["usuario_id"] = "USR-000001"
        resposta = app.response_class()
        app.session_interface.save_session(app, session, resposta)

    assert "SameSite=Lax" in _cookie(resposta, app.config["SESSION_COOKIE_NAME"])
