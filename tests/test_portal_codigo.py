"""Código de 6 dígitos do Portal (2026-10-14) -- a porta do app instalado.

No iPhone o app instalado tem cookies separados do Safari, então o link
mágico do e-mail abre e loga no Safari, não no app. O mesmo e-mail leva
um código, digitado dentro do app (core/motor_portal_auth.py).

O link continua sendo a credencial forte. O código é curto o bastante
para ser chutado, então o que está testado aqui são as travas dele:
preso ao aparelho que pediu, 5 tentativas, uso único junto com o link,
e a tela que não revela se um CPF é cliente.
"""
import json
from datetime import timedelta

import pytest

import core.motor_portal_auth as motor_auth
from core import limitador_tentativas
from core.conexao import conectar_admin
from core.motor_portal_auth import (
    CODIGO_MAX_TENTATIVAS,
    _agora,
    _iso,
    criar_acesso,
    criar_token,
    validar_e_consumir_codigo,
    validar_e_consumir_token,
)

from tests.conftest import EMPRESA_A, EMPRESA_B

APARELHO = "aparelho-da-ana"


@pytest.fixture
def codigo_fixo(monkeypatch):
    monkeypatch.setattr(motor_auth, "_gerar_codigo", lambda: "123456")
    return "123456"


# --------------------------------------------------------------------
# O motor
# --------------------------------------------------------------------

def test_codigo_certo_no_aparelho_certo_devolve_o_dono(banco):
    _token, codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)

    assert len(codigo) == 6 and codigo.isdigit()
    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, codigo) == "CLI-000001"


def test_codigo_nao_serve_duas_vezes(banco):
    _token, codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)

    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, codigo) == "CLI-000001"
    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, codigo) is None


def test_codigo_nao_vale_em_outro_aparelho(banco):
    """Quem tem só o código (leu o e-mail por cima do ombro) e não pediu
    o acesso daquele aparelho não entra."""
    _token, codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)

    assert validar_e_consumir_codigo(EMPRESA_A, "outro-aparelho", codigo) is None
    assert validar_e_consumir_codigo(EMPRESA_A, None, codigo) is None


def test_quinto_erro_mata_o_codigo_mesmo_o_certo(banco, codigo_fixo):
    """Sem esta trava, 1 milhão de combinações viram questão de tempo."""
    criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)

    for errado in range(CODIGO_MAX_TENTATIVAS):
        assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, f"00000{errado}") is None

    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, codigo_fixo) is None


def test_erros_abaixo_do_limite_nao_trancam_o_dono(banco, codigo_fixo):
    """Controle do teste acima: errar a digitação algumas vezes não pode
    deixar o próprio cliente de fora. Espaço no meio também vale -- é
    como o código aparece no e-mail lido em voz alta."""
    criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)

    for _ in range(CODIGO_MAX_TENTATIVAS - 1):
        validar_e_consumir_codigo(EMPRESA_A, APARELHO, "999999")

    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, "123 456") == "CLI-000001"


def test_codigo_expirado_nao_serve(banco):
    _token, codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)
    con = conectar_admin()
    con.execute(
        "UPDATE portal_token SET expira_em = ? WHERE desafio = ?",
        (_iso(_agora() - timedelta(minutes=1)), APARELHO),
    )
    con.commit()
    con.close()

    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, codigo) is None


def test_link_e_codigo_sao_o_mesmo_acesso(banco):
    """Usar uma porta fecha a outra -- senão um e-mail abriria duas
    sessões, uma em cada aparelho."""
    token, codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)
    assert validar_e_consumir_token(EMPRESA_A, token) == "CLI-000001"
    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, codigo) is None

    token, codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio="aparelho-da-ana-2")
    assert validar_e_consumir_codigo(EMPRESA_A, "aparelho-da-ana-2", codigo) == "CLI-000001"
    assert validar_e_consumir_token(EMPRESA_A, token) is None


def test_codigo_esgotado_nao_derruba_o_link(banco, codigo_fixo):
    """Quem chutou 5 vezes matou o código, não o acesso do dono: o link
    do mesmo e-mail continua entrando."""
    token, _codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)
    for _ in range(CODIGO_MAX_TENTATIVAS):
        validar_e_consumir_codigo(EMPRESA_A, APARELHO, "000000")

    assert validar_e_consumir_token(EMPRESA_A, token) == "CLI-000001"


def test_codigo_de_uma_empresa_nao_vale_na_outra(banco):
    _token, codigo = criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)

    assert validar_e_consumir_codigo(EMPRESA_B, APARELHO, codigo) is None
    # E a recusa lá fora não gastou o acesso daqui.
    assert validar_e_consumir_codigo(EMPRESA_A, APARELHO, codigo) == "CLI-000001"


def test_codigo_nao_fica_gravado_em_claro(banco, monkeypatch):
    monkeypatch.setattr(motor_auth, "_gerar_codigo", lambda: "482913")
    criar_acesso(EMPRESA_A, "CLI-000001", desafio=APARELHO)

    con = conectar_admin()
    linha = con.execute("SELECT * FROM portal_token WHERE desafio = ?", (APARELHO,)).fetchone()
    con.close()
    assert not any("482913" in str(valor) for valor in tuple(linha))


def test_link_sem_aparelho_nao_ganha_codigo(banco):
    """criar_token (demonstração, testes antigos) não tem desafio, e um
    código sem aparelho valeria em qualquer lugar."""
    token = criar_token(EMPRESA_A, "CLI-000001")
    con = conectar_admin()
    linha = con.execute("SELECT codigo_hash FROM portal_token WHERE token = ?", (token,)).fetchone()
    con.close()
    assert linha["codigo_hash"] is None


# --------------------------------------------------------------------
# Pelo Portal de verdade: tela de login -> código -> sessão
# --------------------------------------------------------------------

@pytest.fixture
def anonimo(banco):
    from portal.app import app

    app.config.update(TESTING=True)
    # O limitador é memória do processo: sem zerar, os pedidos de login
    # dos testes anteriores esgotariam a cota deste.
    limitador_tentativas._tentativas.clear()
    return app.test_client()


def _pedir_acesso(cliente_http, identificador="111.111.111-11"):
    return cliente_http.post("/portal/login", data={"identificador": identificador})


def test_login_pelo_codigo_abre_a_sessao_do_dono(anonimo, codigo_fixo):
    assert 'name="codigo"' in _pedir_acesso(anonimo).get_data(as_text=True)

    resposta = anonimo.post("/portal/login/codigo", data={"codigo": codigo_fixo})

    assert resposta.status_code == 302
    assert resposta.headers["Location"] == "/portal"
    with anonimo.session_transaction() as sessao:
        assert sessao["cliente_id"] == "CLI-000001"
        assert sessao["empresa_id"] == EMPRESA_A
        assert "desafio_login" not in sessao


def test_cpf_desconhecido_ve_a_mesma_tela(anonimo):
    """A tela do código aparece igual com ou sem cadastro -- diferente
    seria um jeito de descobrir se um CPF é cliente."""
    conhecido = _pedir_acesso(anonimo).get_data(as_text=True)
    desconhecido = _pedir_acesso(anonimo, "999.999.999-99").get_data(as_text=True)

    assert conhecido == desconhecido
    anonimo.post("/portal/login/codigo", data={"codigo": "000000"})
    with anonimo.session_transaction() as sessao:
        assert "cliente_id" not in sessao


def test_codigo_errado_nao_abre_sessao(anonimo, codigo_fixo):
    _pedir_acesso(anonimo)

    resposta = anonimo.post("/portal/login/codigo", data={"codigo": "654321"})

    assert resposta.status_code == 200
    assert "Código incorreto ou expirado" in resposta.get_data(as_text=True)
    with anonimo.session_transaction() as sessao:
        assert "cliente_id" not in sessao


def test_codigo_pedido_em_outro_navegador_nao_entra(anonimo, codigo_fixo):
    """Alguém com o código da Ana, num aparelho que não pediu acesso."""
    from portal.app import app

    _pedir_acesso(anonimo)
    outro = app.test_client()

    resposta = outro.post("/portal/login/codigo", data={"codigo": codigo_fixo})

    assert "Código incorreto ou expirado" in resposta.get_data(as_text=True)
    with outro.session_transaction() as sessao:
        assert "cliente_id" not in sessao


def test_app_reaberto_volta_ao_campo_do_codigo(anonimo):
    """O iPhone pode fechar o app enquanto a pessoa vai ao e-mail; ao
    reabrir, a tela lembra que um código foi pedido."""
    _pedir_acesso(anonimo)

    assert 'name="codigo"' in anonimo.get("/portal/login").get_data(as_text=True)
    assert 'name="identificador"' in anonimo.get("/portal/login?novo=1").get_data(as_text=True)


def test_sessao_sobrevive_ao_fechar_o_app(anonimo, codigo_fixo):
    """Sessão com validade: sem isto o app instalado pediria código toda
    vez que o celular o tirasse da memória."""
    _pedir_acesso(anonimo)
    resposta = anonimo.post("/portal/login/codigo", data={"codigo": codigo_fixo})

    cookie = next(c for c in resposta.headers.getlist("Set-Cookie") if c.startswith("portal_session="))
    assert "Expires=" in cookie


# --------------------------------------------------------------------
# O app instalável não guarda dado de ninguém
# --------------------------------------------------------------------

def test_manifesto_e_service_worker_respondem_sem_login(anonimo):
    manifesto = anonimo.get("/portal/manifest.webmanifest")
    sw = anonimo.get("/portal/sw.js")

    assert manifesto.status_code == 200
    assert manifesto.get_json()["scope"] == "/portal"
    assert sw.status_code == 200
    assert sw.headers["Service-Worker-Allowed"] == "/portal"


def test_service_worker_so_guarda_arquivos_publicos(anonimo):
    """Celular perdido não pode levar CPF, arma ou documento numa cópia
    offline: a lista do que fica guardado é só visual."""
    codigo = anonimo.get("/portal/sw.js").get_data(as_text=True)
    lista = codigo.split("const ARQUIVOS = ", 1)[1].split(";", 1)[0]

    for caminho in json.loads(lista):
        assert caminho == "/portal/offline" or caminho.startswith("/portal/static/"), caminho
