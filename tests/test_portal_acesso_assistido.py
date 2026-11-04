"""Quando o e-mail de acesso não chega (2026-11-04).

No bloqueio do Gmail, o Portal seguia dizendo "enviamos" para e-mails que
voltavam. O que estes testes guardam:

- pausado, o login não envia nem cria nada, e responde igual para todo mundo;
- abrir o link da secretaria NÃO gasta o uso único (a prévia do WhatsApp abre);
- o link fica na Auditoria, e cliente de outra empresa não é alcançável;
- corrigir o e-mail mata os acessos enviados ao endereço antigo.
"""
import pytest

import portal.app as portal_app
from core.conexao import conectar_admin
from core.db.migrar_pausa_envio_portal import migrar
from core.motor_portal_auth import CHAVE_PAUSA_ENVIO
from tests.conftest import EMPRESA_A


def _token_do_link(resposta) -> str:
    return resposta.get_json()["link"].rsplit("/", 1)[-1]


def _log(tipo):
    con = conectar_admin()
    try:
        return [dict(l) for l in con.execute(
            "SELECT * FROM log_administrativo WHERE tipo_evento = ?", (tipo,))]
    finally:
        con.close()


def _pausar(valor="Sim"):
    con = conectar_admin()
    try:
        con.execute(
            "INSERT INTO configuracoes (config_id, empresa_id, chave, valor, categoria, descricao, ativo) "
            "VALUES ('CFG-009999', ?, ?, ?, 'portal', '', 'Sim')",
            (EMPRESA_A, CHAVE_PAUSA_ENVIO, valor),
        )
        con.commit()
    finally:
        con.close()


@pytest.fixture
def anonimo(banco):
    portal_app.app.config.update(TESTING=True)
    return portal_app.app.test_client()


@pytest.fixture
def envios(monkeypatch):
    lista = []
    monkeypatch.setattr(portal_app, "gmail_configurado", lambda: True)
    monkeypatch.setattr(portal_app, "enviar_email", lambda **k: lista.append(k))
    monkeypatch.setattr(portal_app, "PORTAL_EMPRESA_ID", EMPRESA_A)
    return lista


def _email_da_ana():
    con = conectar_admin()
    try:
        return con.execute("SELECT email, cpf FROM cliente WHERE cliente_id = 'CLI-000001'").fetchone()
    finally:
        con.close()


def _tokens():
    con = conectar_admin()
    try:
        return con.execute("SELECT COUNT(*) FROM portal_token").fetchone()[0]
    finally:
        con.close()


# ------------------------------------------------------------------- pausa
def test_sem_pausa_o_login_envia_como_sempre(banco, anonimo, envios):
    anonimo.post("/portal/login", data={"identificador": _email_da_ana()["email"]})
    assert len(envios) == 1


def test_pausado_nao_envia_nem_cria_acesso(banco, anonimo, envios):
    _pausar()
    antes = _tokens()
    html = anonimo.post("/portal/login", data={"identificador": _email_da_ana()["email"]}).get_data(as_text=True)

    assert envios == []
    assert _tokens() == antes
    assert "está pausado" in html


def test_pausado_responde_igual_com_ou_sem_cadastro(banco, anonimo, envios):
    _pausar()
    com = anonimo.post("/portal/login", data={"identificador": _email_da_ana()["email"]}).get_data(as_text=True)
    sem = anonimo.post("/portal/login", data={"identificador": "ninguem@example.com"}).get_data(as_text=True)
    assert com == sem


def test_pausado_a_tela_troca_o_formulario_pelo_aviso(banco, anonimo, envios):
    _pausar()
    html = anonimo.get("/portal/login").get_data(as_text=True)
    assert "está pausado" in html
    assert 'name="identificador"' not in html


def test_pausa_desligada_mostra_o_formulario(banco, anonimo, envios):
    _pausar("Não")
    html = anonimo.get("/portal/login").get_data(as_text=True)
    assert 'name="identificador"' in html
    assert "está pausado" not in html


def test_migracao_nasce_ligada_e_nao_religa(banco):
    migrar()
    con = conectar_admin()
    valor = "SELECT valor FROM configuracoes WHERE empresa_id = ? AND chave = ?"
    assert con.execute(valor, (EMPRESA_A, CHAVE_PAUSA_ENVIO)).fetchone()[0] == "Sim"
    assert con.execute(valor, ("EMP-000002", CHAVE_PAUSA_ENVIO)).fetchone()[0] == "Não"
    con.execute("UPDATE configuracoes SET valor = 'Não' WHERE chave = ?", (CHAVE_PAUSA_ENVIO,))
    con.commit()
    con.close()

    assert migrar() == {"linhas_criadas": 0}

    con = conectar_admin()
    assert con.execute(valor, (EMPRESA_A, CHAVE_PAUSA_ENVIO)).fetchone()[0] == "Não"
    con.close()


# ------------------------------------------------------- link da secretaria
def test_abrir_o_link_nao_gasta_o_uso_unico(banco, painel, anonimo, envios):
    """É o que a prévia do WhatsApp faz, várias vezes, antes da pessoa tocar."""
    token = _token_do_link(painel.post("/api/clientes/CLI-000001/acesso-portal/link"))

    for _ in range(3):
        resposta = anonimo.get(f"/portal/acesso/{token}")
        assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"] == "no-store"
    with anonimo.session_transaction() as sessao:
        assert "cliente_id" not in sessao

    assert anonimo.post(f"/portal/acesso/{token}").status_code == 302
    with anonimo.session_transaction() as sessao:
        assert sessao["cliente_id"] == "CLI-000001"


def test_link_so_funciona_uma_vez(banco, painel, anonimo, envios):
    token = _token_do_link(painel.post("/api/clientes/CLI-000001/acesso-portal/link"))
    anonimo.post(f"/portal/acesso/{token}")

    outro = portal_app.app.test_client()
    html = outro.post(f"/portal/acesso/{token}").get_data(as_text=True)
    assert "Peça um novo à secretaria" in html
    with outro.session_transaction() as sessao:
        assert "cliente_id" not in sessao


def test_gerar_outro_cancela_o_anterior(banco, painel, anonimo, envios):
    velho = _token_do_link(painel.post("/api/clientes/CLI-000001/acesso-portal/link"))
    novo = _token_do_link(painel.post("/api/clientes/CLI-000001/acesso-portal/link"))

    assert "Peça um novo" in anonimo.post(f"/portal/acesso/{velho}").get_data(as_text=True)
    assert anonimo.post(f"/portal/acesso/{novo}").status_code == 302


def test_link_vale_vinte_e_quatro_horas(banco, painel):
    token = _token_do_link(painel.post("/api/clientes/CLI-000001/acesso-portal/link"))
    con = conectar_admin()
    criado, expira = con.execute(
        "SELECT criado_em, expira_em FROM portal_token WHERE token = ?", (token,)
    ).fetchone()
    con.close()
    from datetime import datetime
    formato = "%Y-%m-%dT%H:%M:%SZ"
    horas = (datetime.strptime(expira, formato) - datetime.strptime(criado, formato)).total_seconds() / 3600
    assert horas == 24


def test_link_fica_na_auditoria_sem_o_token(banco, painel):
    token = _token_do_link(painel.post("/api/clientes/CLI-000001/acesso-portal/link"))
    linhas = _log("LINK_PORTAL_GERADO")
    assert len(linhas) == 1
    assert linhas[0]["alvo"] == "CLI-000001"
    assert linhas[0]["criado_por"] == "Gestor Teste"
    assert token not in str(linhas[0])


def test_resposta_do_link_nao_fica_em_cache(banco, painel):
    resposta = painel.post("/api/clientes/CLI-000001/acesso-portal/link")
    assert resposta.headers["Cache-Control"] == "no-store"


def test_cliente_de_outra_empresa_nao_ganha_link(banco, painel):
    """CLI-000003 é da EMPRESA_B; o painel está logado na EMPRESA_A."""
    assert painel.post("/api/clientes/CLI-000003/acesso-portal/link").status_code == 404
    assert painel.get("/api/clientes/CLI-000003/acesso-portal").status_code == 404
    assert painel.post("/api/clientes/CLI-000003/acesso-portal/email",
                       json={"email": "novo@example.com"}).status_code == 404
    assert _log("LINK_PORTAL_GERADO") == []


def test_quem_nao_tem_a_funcao_clientes_nao_gera_link(banco, painel_atendente):
    con = conectar_admin()
    con.execute(
        "INSERT INTO usuario_permissao (usuario_id, empresa_id, funcao, ativo) "
        "VALUES ('USR-000003', ?, 'clientes', 'Não')", (EMPRESA_A,),
    )
    con.commit()
    con.close()
    assert painel_atendente.post("/api/clientes/CLI-000001/acesso-portal/link").status_code == 403


# -------------------------------------------------------- corrigir o e-mail
def test_corrigir_email_grava_e_fica_na_auditoria(banco, painel):
    anterior = _email_da_ana()["email"]
    resposta = painel.post("/api/clientes/CLI-000001/acesso-portal/email", json={"email": " Novo@Example.com "})

    assert resposta.status_code == 200
    assert _email_da_ana()["email"] == "novo@example.com"
    linha = _log("EMAIL_CLIENTE_ALTERADO")[0]
    assert (linha["valor_anterior"], linha["valor_novo"]) == (anterior, "novo@example.com")


@pytest.mark.parametrize("ruim", ["", "sem-arroba", "a@b", "a b@c.com"])
def test_email_malformado_e_recusado(banco, painel, ruim):
    anterior = _email_da_ana()["email"]
    resposta = painel.post("/api/clientes/CLI-000001/acesso-portal/email", json={"email": ruim})
    assert resposta.status_code == 400
    assert _email_da_ana()["email"] == anterior
    assert _log("EMAIL_CLIENTE_ALTERADO") == []


def test_mesmo_email_nao_gera_registro(banco, painel):
    painel.post("/api/clientes/CLI-000001/acesso-portal/email", json={"email": _email_da_ana()["email"]})
    assert _log("EMAIL_CLIENTE_ALTERADO") == []


def test_corrigir_email_mata_os_acessos_do_endereco_antigo(banco, painel, anonimo, envios):
    token = _token_do_link(painel.post("/api/clientes/CLI-000001/acesso-portal/link"))
    painel.post("/api/clientes/CLI-000001/acesso-portal/email", json={"email": "novo@example.com"})

    assert "Peça um novo" in anonimo.post(f"/portal/acesso/{token}").get_data(as_text=True)


def test_depois_de_corrigir_o_codigo_vai_para_o_endereco_novo(banco, painel, anonimo, envios):
    painel.post("/api/clientes/CLI-000001/acesso-portal/email", json={"email": "novo@example.com"})
    anonimo.post("/portal/login", data={"identificador": "novo@example.com"})
    assert envios[-1]["destinatario"] == "novo@example.com"
