"""Convite por e-mail para a própria pessoa criar a senha do painel.

Pedido de 2026-10-20: criar um Gestor e ele entrar sem ninguém abrir um
terminal no servidor. É a primeira rota do painel, além do login, que
mexe em senha SEM sessão -- então o que importa aqui é o que não pode
acontecer: link reaproveitado, vencido, de gente desativada, link guardado
em claro no banco, e a tela de "Esqueci minha senha" revelando quem tem
acesso.
"""
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import pytest

from core import limitador_tentativas, motor_convite_usuario
from core.conexao import conectar

from tests.conftest import EMPRESA_A, EMPRESA_B


@pytest.fixture(autouse=True)
def _limitador_zerado(monkeypatch):
    """O limitador de tentativas é global ao processo: sem zerar, os
    testes de cima gastariam as tentativas dos de baixo."""
    monkeypatch.setattr(limitador_tentativas, "_tentativas", defaultdict(deque))


@pytest.fixture
def anonimo(banco):
    """Navegador sem login nenhum -- é quem abre o link do e-mail."""
    from webapp.app import app

    app.config.update(TESTING=True)
    return app.test_client()


def _criar_usuario(painel, email="novo@example.com", papel="Gestor"):
    r = painel.post("/api/usuarios", json={"nome": "Pessoa Nova", "email": email, "papel": papel})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _token(dados):
    return dados["link"].rsplit("/", 1)[-1]


def _criar_senha(anonimo, token, senha="senha-boa-123", confirmacao=None):
    anonimo.get(f"/definir-senha/{token}")
    return anonimo.post("/definir-senha", data={
        "senha": senha, "confirmacao": senha if confirmacao is None else confirmacao,
    })


def _entrar(anonimo, email, senha):
    return anonimo.post("/login", data={"email": email, "senha": senha})


# --------------------------------------------------------------------
# 1. O fluxo
# --------------------------------------------------------------------

def test_gestor_criado_entra_com_a_senha_que_ele_mesmo_criou(painel, anonimo):
    dados = _criar_usuario(painel)
    # Sem Gmail nos testes, o link volta para a tela -- é o caminho
    # "copie e mande por WhatsApp".
    assert dados["convite_enviado"] is False

    resposta = _criar_senha(anonimo, _token(dados))
    assert resposta.status_code == 302
    assert "senha=criada" in resposta.headers["Location"]

    entrada = _entrar(anonimo, "novo@example.com", "senha-boa-123")
    assert entrada.status_code == 302
    with anonimo.session_transaction() as sessao:
        assert sessao["usuario_id"] == dados["usuario_id"]
        assert sessao["empresa_id"] == EMPRESA_A
        assert sessao["papel"] == "Gestor"


def test_link_sai_da_barra_de_endereco_na_chegada(painel, anonimo):
    """O link fica na sessão, não na URL: sem isso ele iria para o
    histórico do navegador e no Referer de tudo que a página carrega."""
    dados = _criar_usuario(painel)
    resposta = anonimo.get(f"/definir-senha/{_token(dados)}")
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/definir-senha")


def test_banco_guarda_so_o_hash_do_link(painel):
    dados = _criar_usuario(painel)
    con = conectar(EMPRESA_A)
    try:
        linha = con.execute("SELECT * FROM usuario_convite").fetchone()
    finally:
        con.close()
    assert _token(dados) not in dict(linha).values()


def test_criar_e_usar_ficam_no_registro_de_auditoria(painel, anonimo):
    dados = _criar_usuario(painel)
    _criar_senha(anonimo, _token(dados))
    con = conectar(EMPRESA_A)
    try:
        eventos = {l["tipo_evento"] for l in con.execute(
            "SELECT tipo_evento FROM log_administrativo WHERE alvo = ?", (dados["usuario_id"],))}
    finally:
        con.close()
    assert {"CONVITE_SENHA_ENVIADO", "SENHA_DEFINIDA_POR_LINK"} <= eventos


# --------------------------------------------------------------------
# 2. O que não pode acontecer
# --------------------------------------------------------------------

def test_link_so_funciona_uma_vez(painel, anonimo):
    token = _token(_criar_usuario(painel))
    _criar_senha(anonimo, token)

    segunda = _criar_senha(anonimo, token, senha="outra-senha-999")

    assert "Link vencido" in segunda.get_data(as_text=True)
    assert _entrar(anonimo, "novo@example.com", "outra-senha-999").status_code == 200


def test_link_vencido_nao_serve(painel, anonimo):
    token = _token(_criar_usuario(painel))
    ontem = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = conectar(EMPRESA_A)
    con.execute("UPDATE usuario_convite SET expira_em = ?", (ontem,))
    con.commit()
    con.close()

    resposta = _criar_senha(anonimo, token)

    assert "Link vencido" in resposta.get_data(as_text=True)


def test_reenviar_mata_o_link_anterior(painel, anonimo):
    dados = _criar_usuario(painel)
    antigo = _token(dados)
    novo = _token(painel.post(f"/api/usuarios/{dados['usuario_id']}/convite").get_json())

    assert "Link vencido" in _criar_senha(anonimo, antigo).get_data(as_text=True)
    assert _criar_senha(anonimo, novo).status_code == 302


def test_usuario_desativado_nao_usa_o_link(painel, anonimo):
    dados = _criar_usuario(painel)
    painel.post(f"/api/usuarios/{dados['usuario_id']}", json={"ativo": "Não"})

    resposta = _criar_senha(anonimo, _token(dados))

    assert "Link vencido" in resposta.get_data(as_text=True)


def test_senha_curta_ou_diferente_e_recusada_e_o_link_continua_valendo(painel, anonimo):
    token = _token(_criar_usuario(painel))

    curta = _criar_senha(anonimo, token, senha="123")
    diferente = _criar_senha(anonimo, token, senha="senha-boa-123", confirmacao="senha-boa-124")

    assert "pelo menos 8" in curta.get_data(as_text=True)
    assert "não são iguais" in diferente.get_data(as_text=True)
    assert _criar_senha(anonimo, token).status_code == 302


def test_atendente_nao_manda_convite(painel_atendente):
    assert painel_atendente.post("/api/usuarios/USR-000001/convite").status_code == 403


def test_gestor_nao_manda_convite_para_usuario_de_outra_empresa(painel):
    """USR-000002 é da EMPRESA_B. Um link para ele, pedido pela A, daria
    à empresa A um jeito de criar a senha de alguém da B."""
    resposta = painel.post("/api/usuarios/USR-000002/convite")

    assert resposta.status_code == 400
    con = conectar(EMPRESA_B)
    try:
        assert con.execute("SELECT COUNT(*) FROM usuario_convite").fetchone()[0] == 0
    finally:
        con.close()


# --------------------------------------------------------------------
# 3. Esqueci minha senha
# --------------------------------------------------------------------

def test_esqueci_senha_responde_igual_com_e_sem_cadastro(anonimo, monkeypatch):
    """Diferença de resposta transformaria a tela num verificador de quem
    tem acesso ao painel."""
    from webapp import app as modulo_app

    enviados = []
    monkeypatch.setattr(modulo_app, "_enviar_link_senha", lambda empresa_id, link: enviados.append(link) or True)

    com = anonimo.post("/esqueci-senha", data={"email": "gestor@example.com"})
    sem = anonimo.post("/esqueci-senha", data={"email": "ninguem@example.com"})

    assert com.status_code == sem.status_code == 200
    assert com.get_data(as_text=True) == sem.get_data(as_text=True)
    assert [l["email"] for l in enviados] == ["gestor@example.com"]


def test_link_do_esqueci_senha_vale_pouco_e_troca_a_senha(anonimo, monkeypatch):
    from webapp import app as modulo_app

    enviados = []
    monkeypatch.setattr(modulo_app, "_enviar_link_senha", lambda empresa_id, link: enviados.append(link) or True)
    anonimo.post("/esqueci-senha", data={"email": "gestor@example.com"})
    link = enviados[0]

    expira = datetime.strptime(link["expira_em"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert expira - datetime.now(timezone.utc) <= timedelta(minutes=motor_convite_usuario.VALIDADE_REDEFINICAO_MINUTOS)

    assert _criar_senha(anonimo, link["token"], senha="nova-senha-456").status_code == 302
    assert _entrar(anonimo, "gestor@example.com", "nova-senha-456").status_code == 302


def test_esqueci_senha_nao_manda_link_para_usuario_desativado(painel, anonimo, monkeypatch):
    from webapp import app as modulo_app

    enviados = []
    monkeypatch.setattr(modulo_app, "_enviar_link_senha", lambda empresa_id, link: enviados.append(link) or True)
    painel.post("/api/usuarios/USR-000003", json={"ativo": "Não"})

    anonimo.post("/esqueci-senha", data={"email": "atendente@example.com"})

    # atendente@example.com existe nas duas empresas; só a da B está ativa.
    assert all(l["email"] == "atendente@example.com" for l in enviados)
    con = conectar(EMPRESA_A)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM usuario_convite WHERE usuario_id = 'USR-000003'"
        ).fetchone()[0] == 0
    finally:
        con.close()
