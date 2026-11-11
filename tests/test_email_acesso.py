"""E-mail de acesso pelo Resend (2026-11-04).

O que estes testes guardam:

- configurado, o acesso sai pelo Resend e não pelo Gmail; sem configurar, nada muda;
- a chave e o link nunca vão parar no log nem na mensagem de erro;
- falha no envio não muda a tela: revelaria quem está cadastrado;
- cota esgotada liga a pausa sozinha, e fica na Auditoria.
"""
import pytest
import requests

import integracoes.email_acesso as email_acesso
import portal.app as portal_app
from core import limitador_tentativas
from core.conexao import conectar_admin
from core.db.migrar_pausa_envio_portal import migrar
from core.motor_portal_auth import CHAVE_PAUSA_ENVIO, envio_codigos_pausado
from tests.conftest import EMPRESA_A

CHAVE = "re_chave_de_teste_nao_real"


class RespostaFalsa:
    def __init__(self, status, corpo):
        self.status_code = status
        self._corpo = corpo

    def json(self):
        if self._corpo is None:
            raise ValueError("sem json")
        return self._corpo


@pytest.fixture
def resend(monkeypatch):
    """Resend configurado, com o POST capturado. `saida` é o que ele responde."""
    monkeypatch.setenv("RESEND_API_KEY", CHAVE)
    monkeypatch.setenv("EMAIL_ACESSO_REMETENTE", "acesso@envio.exemplo.com")
    estado = {"chamadas": [], "saida": RespostaFalsa(200, {"id": "abc"})}

    def post(url, **kwargs):
        estado["chamadas"].append({"url": url, **kwargs})
        if isinstance(estado["saida"], Exception):
            raise estado["saida"]
        return estado["saida"]

    monkeypatch.setattr(email_acesso.requests, "post", post)
    return estado


@pytest.fixture
def anonimo(banco, monkeypatch):
    monkeypatch.setattr(portal_app, "PORTAL_EMPRESA_ID", EMPRESA_A)
    limitador_tentativas._tentativas.clear()
    portal_app.app.config.update(TESTING=True)
    return portal_app.app.test_client()


@pytest.fixture
def gmail(monkeypatch):
    enviados = []
    monkeypatch.setattr(portal_app, "gmail_configurado", lambda: True)
    monkeypatch.setattr(portal_app, "enviar_email", lambda **k: enviados.append(k))
    return enviados


def _email_ana():
    con = conectar_admin()
    try:
        return con.execute("SELECT email FROM cliente WHERE cliente_id = 'CLI-000001'").fetchone()[0]
    finally:
        con.close()


def _pedir(cliente_http, identificador=None):
    return cliente_http.post("/portal/login", data={"identificador": identificador or _email_ana()},
                             follow_redirects=True)


# ---------------------------------------------------------------- o módulo
def test_sem_as_duas_variaveis_nao_esta_configurado(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", CHAVE)
    monkeypatch.delenv("EMAIL_ACESSO_REMETENTE", raising=False)
    assert email_acesso.email_acesso_configurado() is False
    monkeypatch.setenv("EMAIL_ACESSO_REMETENTE", "a@b.com")
    monkeypatch.setenv("RESEND_API_KEY", "")
    assert email_acesso.email_acesso_configurado() is False


def test_pedido_ao_resend(resend):
    assert email_acesso.enviar_email_acesso(
        "ana@example.com", "Assunto", "Corpo", nome_remetente='Clube "Smith" <x>',
        responder_para="contato@example.com",
    ) == "abc"

    pedido = resend["chamadas"][0]
    assert pedido["url"] == "https://api.resend.com/emails"
    assert pedido["headers"]["Authorization"] == f"Bearer {CHAVE}"
    assert pedido["allow_redirects"] is False
    assert pedido["timeout"] > 0
    assert pedido["json"] == {
        "from": "Clube Smith x <acesso@envio.exemplo.com>", "to": ["ana@example.com"],
        "subject": "Assunto", "text": "Corpo", "reply_to": "contato@example.com",
    }


@pytest.mark.parametrize("nome", ["daily_quota_exceeded", "monthly_quota_exceeded"])
def test_cota_tem_excecao_propria(resend, nome):
    resend["saida"] = RespostaFalsa(429, {"name": nome})
    with pytest.raises(email_acesso.CotaEsgotada):
        email_acesso.enviar_email_acesso("a@b.com", "A", "C")


def test_excesso_por_segundo_nao_e_cota(resend):
    resend["saida"] = RespostaFalsa(429, {"name": "rate_limit_exceeded"})
    with pytest.raises(email_acesso.EnvioAcessoFalhou) as erro:
        email_acesso.enviar_email_acesso("a@b.com", "A", "C")
    assert not isinstance(erro.value, email_acesso.CotaEsgotada)


@pytest.mark.parametrize("saida", [
    RespostaFalsa(403, {"name": "validation_error"}),
    RespostaFalsa(500, None),
    requests.ConnectionError("https://api.resend.com ana@example.com " + CHAVE),
])
def test_erro_nao_leva_destinatario_chave_nem_corpo(resend, saida):
    resend["saida"] = saida
    with pytest.raises(email_acesso.EnvioAcessoFalhou) as erro:
        email_acesso.enviar_email_acesso("ana@example.com", "A", "LINK-SECRETO")
    texto = str(erro.value)
    assert "ana@example.com" not in texto
    assert CHAVE not in texto
    assert "LINK-SECRETO" not in texto
    assert erro.value.__cause__ is None


# ------------------------------------------------------------------ o Portal
def test_configurado_sai_pelo_resend_e_nao_pelo_gmail(banco, anonimo, resend, gmail):
    _pedir(anonimo)

    assert gmail == []
    assert len(resend["chamadas"]) == 1
    dados = resend["chamadas"][0]["json"]
    assert dados["to"] == [_email_ana()]
    assert "/portal/entrar/" in dados["text"]


def test_email_traz_o_codigo_no_assunto_e_antes_do_link(banco, anonimo, resend, gmail):
    _pedir(anonimo)

    dados = resend["chamadas"][0]["json"]
    codigo = dados["subject"].rsplit(" ", 1)[-1]
    assert len(codigo) == 6 and codigo.isdigit()
    assert dados["text"].index(codigo) < dados["text"].index("/portal/entrar/")
    assert "Use o link abaixo" not in dados["text"]


def test_tela_do_codigo_avisa_do_spam_e_diz_o_remetente(banco, anonimo, resend, gmail):
    html = _pedir(anonimo, "ninguem@example.com").get_data(as_text=True)
    assert "Olhe o Spam ou o Lixo eletrônico" in html
    assert "acesso@envio.exemplo.com" in html
    assert html.index("Olhe o Spam") < html.index("Pedir um novo código")


def test_sem_resend_a_tela_nao_cita_remetente(banco, anonimo, monkeypatch, gmail):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("EMAIL_ACESSO_REMETENTE", "acesso@envio.exemplo.com")
    html = _pedir(anonimo, "ninguem@example.com").get_data(as_text=True)
    assert "Olhe o Spam ou o Lixo eletrônico" in html
    assert "acesso@envio.exemplo.com" not in html


def test_sem_configurar_continua_pelo_gmail(banco, anonimo, monkeypatch, gmail):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    _pedir(anonimo)
    assert len(gmail) == 1
    assert "/portal/entrar/" in gmail[0]["corpo"]


def test_falha_nao_muda_a_tela_nem_vaza_o_link(banco, anonimo, resend, capsys):
    resend["saida"] = RespostaFalsa(500, {"name": "application_error"})
    com_falha = _pedir(anonimo).get_data(as_text=True)
    saida = capsys.readouterr()

    limitador_tentativas._tentativas.clear()
    outro = portal_app.app.test_client()
    sem_cadastro = _pedir(outro, "ninguem@example.com").get_data(as_text=True)

    assert com_falha == sem_cadastro
    assert "/portal/entrar/" not in saida.out + saida.err


def test_falha_do_gmail_nao_vaza_o_link(banco, anonimo, monkeypatch, capsys):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setattr(portal_app, "gmail_configurado", lambda: True)

    def explode(**_k):
        raise RuntimeError("token revogado")

    monkeypatch.setattr(portal_app, "enviar_email", explode)
    assert _pedir(anonimo).status_code == 200
    saida = capsys.readouterr()
    assert "/portal/entrar/" not in saida.out + saida.err


def test_cota_esgotada_liga_a_pausa_e_fica_na_auditoria(banco, anonimo, resend, monkeypatch):
    alertas = []
    import atendimento.alertas
    monkeypatch.setattr(atendimento.alertas, "alertar_falha", lambda t, d: alertas.append((t, d)))
    migrar()
    con = conectar_admin()
    con.execute("UPDATE configuracoes SET valor = 'Não' WHERE chave = ?", (CHAVE_PAUSA_ENVIO,))
    con.commit()
    con.close()
    assert envio_codigos_pausado(EMPRESA_A) is False

    resend["saida"] = RespostaFalsa(429, {"name": "daily_quota_exceeded"})
    _pedir(anonimo)

    assert envio_codigos_pausado(EMPRESA_A) is True
    assert len(alertas) == 1
    con = conectar_admin()
    autor = con.execute(
        "SELECT criado_por FROM log_administrativo WHERE tipo_evento = 'configuracao_alterada'"
    ).fetchone()[0]
    con.close()
    assert autor == "Sistema (cota de e-mail esgotada)"

    # O próximo pedido já não tenta e lê o aviso, com ou sem cadastro.
    limitador_tentativas._tentativas.clear()
    resend["chamadas"].clear()
    html = _pedir(portal_app.app.test_client()).get_data(as_text=True)
    assert "está pausado" in html
    assert resend["chamadas"] == []
