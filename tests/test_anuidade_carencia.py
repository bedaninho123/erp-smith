"""Anuidade vencida: um mês de carência, depois o sócio perde Habitualidade
e Marketplace (decisão do usuário, 2026-11-10).

O que não pode falhar, na ordem do risco:

1. NA DÚVIDA, NÃO CORTA. Só bloqueia quando a data venceu há mais de 30
   dias E o Shooting House marca atraso. Data que não veio, ou data
   vencida com o status dizendo "em dia", nunca tira acesso de ninguém --
   é desse lado que sai o erro que acusa quem pagou.
2. O despachante não depende de anuidade: cliente com caso continua
   entrando no que é dele.
3. A sessão se confere sozinha: o login dura 30 dias, e quem passou do
   prazo (ou renovou) não pode esperar a sessão acabar.
4. Anúncio de quem passou do prazo some da vitrine, sem ser apagado.

Datas do Portal ficam longe das bordas (dias inteiros de folga): o Portal
conta o dia em Brasília, e o teste roda no relógio da máquina.
"""
import sqlite3
import time
from datetime import date, timedelta

import pytest

from core import motor_marketplace
from core.conexao import CORE_DB
from domain.clube_tiro.regra_anuidade import (
    BLOQUEADA,
    CARENCIA,
    CARENCIA_DIAS,
    EM_DIA,
    SEM_DATA,
    VENCIDA_SEM_CONFIRMACAO,
    situacao_anuidade,
)
from tests.conftest import EMPRESA_A, _inserir_cliente, semear_filiado

HOJE = date(2026, 11, 10)
CPF_ANA = "11111111111"
CPF_BRUNO = "22222222222"


def _dias(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


# --------------------------------------------------------------------
# A regra, sem tela nenhuma
# --------------------------------------------------------------------

def test_no_proprio_dia_da_validade_ainda_esta_em_dia():
    assert situacao_anuidade("Sim", "2026-11-10", HOJE)["estado"] == EM_DIA


def test_carencia_vai_do_dia_seguinte_ao_ultimo_dia_do_prazo():
    vencida_ontem = situacao_anuidade("Não", "2026-11-09", HOJE)
    assert vencida_ontem["estado"] == CARENCIA
    assert vencida_ontem["prazo"] == date(2026, 11, 9) + timedelta(days=CARENCIA_DIAS)
    assert not vencida_ontem["bloqueia"]

    ultimo_dia = HOJE - timedelta(days=CARENCIA_DIAS)
    assert situacao_anuidade("Não", ultimo_dia.isoformat(), HOJE)["estado"] == CARENCIA


def test_um_dia_depois_do_prazo_bloqueia():
    passou = HOJE - timedelta(days=CARENCIA_DIAS + 1)
    situacao = situacao_anuidade("Não", passou.isoformat(), HOJE)
    assert situacao["estado"] == BLOQUEADA
    assert situacao["bloqueia"]


def test_aceita_a_data_com_hora_como_o_retrato_guarda():
    assert situacao_anuidade("Não", "2025-01-01T00:00:00Z", HOJE)["bloqueia"]


@pytest.mark.parametrize("em_dia", ["Sim", None])
def test_data_vencida_sem_o_status_de_atraso_nunca_bloqueia(em_dia):
    """Os dois campos discordam para parte dos filiados reais. Cortar só
    pela data tiraria o acesso de quem o Shooting House diz que pagou."""
    situacao = situacao_anuidade(em_dia, "2025-01-01", HOJE)
    assert situacao["estado"] == VENCIDA_SEM_CONFIRMACAO
    assert not situacao["bloqueia"]


@pytest.mark.parametrize("validade", [None, "", "sem data", "31/12/2025"])
def test_sem_data_que_se_leia_nunca_bloqueia(validade):
    situacao = situacao_anuidade("Não", validade, HOJE)
    assert situacao["estado"] == SEM_DATA
    assert not situacao["bloqueia"]


# --------------------------------------------------------------------
# Quem é sócio e passou do prazo
# --------------------------------------------------------------------

@pytest.fixture
def ana_fora_do_prazo(banco):
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste", anuidade_em_dia="Não",
                   anuidade_validade=_dias(-60))


TELAS_DE_SOCIO = ["/portal/habitualidade", "/portal/acervo", "/portal/marketplace"]


def test_cliente_so_do_despachante_nunca_ve_as_telas_de_socio(banco, portal):
    """Ana tem caso e nunca foi filiada. Habitualidade, Acervo e
    Marketplace não aparecem nem abrem; Campeonatos fica aberto a todos
    (decisão do usuário, 2026-11-10)."""
    html = portal.get("/portal").get_data(as_text=True)
    for tela in TELAS_DE_SOCIO:
        assert f'href="{tela}"' not in html, tela
        assert portal.get(tela).status_code == 403, tela
    assert 'href="/portal/campeonatos"' in html
    assert portal.get("/portal/campeonatos").status_code == 200


@pytest.mark.parametrize("tela", TELAS_DE_SOCIO)
def test_fora_do_prazo_perde_as_telas_de_socio(ana_fora_do_prazo, portal, tela):
    resposta = portal.get(tela)
    assert resposta.status_code == 403
    html = resposta.get_data(as_text=True)
    assert "Sua anuidade venceu em" in html
    # Ana tem caso: a tela diz que o despachante continua.
    assert "O que você tem com o despachante continua" in html


def test_fora_do_prazo_nao_pode_publicar_anuncio(ana_fora_do_prazo, portal):
    resposta = portal.post("/portal/marketplace/publicar", data={"titulo": "x"})
    assert resposta.status_code == 403


def test_cliente_do_despachante_fora_do_prazo_continua_no_que_e_dele(ana_fora_do_prazo, portal):
    inicio = portal.get("/portal")
    assert inicio.status_code == 200
    html = inicio.get_data(as_text=True)
    assert "Anuidade venceu em" in html
    assert "voltam assim que você renovar" in html
    # Menu sem as telas de sócio; Campeonatos continua.
    for tela in TELAS_DE_SOCIO:
        assert f'href="{tela}"' not in html, tela
    assert 'href="/portal/campeonatos"' in html

    assert portal.get("/portal/casos").status_code == 200
    assert portal.get("/portal/casos/CAS-000001").status_code == 200
    assert portal.get("/portal/minha-conta").status_code == 200


def test_quem_so_era_socio_fica_so_com_o_aviso(banco, portal):
    """Cadastro criado só por ser filiado (sem caso, sem documento): o app
    inteiro era benefício de sócio, então sobra a tela de renovação, e
    qualquer outra tela volta para ela."""
    con = sqlite3.connect(CORE_DB)
    try:
        _inserir_cliente(con, EMPRESA_A, "CLI-000050", "Davi Socio", "33333333333", "davi@example.com")
        con.commit()
    finally:
        con.close()
    semear_filiado(EMPRESA_A, "33333333333", "Davi Socio", anuidade_em_dia="Não",
                   anuidade_validade=_dias(-60))
    with portal.session_transaction() as sessao:
        sessao["cliente_id"] = "CLI-000050"
        sessao["cliente_nome"] = "Davi Socio"

    html = portal.get("/portal").get_data(as_text=True)
    assert "o app fica fora do ar para você" in html
    assert "/portal/casos" not in html  # menu some

    for tela in ("/portal/casos", "/portal/minha-conta", "/portal/campeonatos", "/portal/acervo"):
        resposta = portal.get(tela)
        assert resposta.status_code == 302, tela
        assert resposta.headers["Location"].endswith("/portal")

    # Sair continua funcionando.
    assert portal.get("/portal/sair").status_code == 302


# --------------------------------------------------------------------
# Na dúvida, não corta
# --------------------------------------------------------------------

@pytest.mark.parametrize("em_dia, validade", [
    ("Não", None),        # data não veio
    ("Sim", "VENCIDA"),   # data passou, mas o clube diz em dia
    (None, "VENCIDA"),    # data passou, status não veio
    ("Não", "CARENCIA"),  # no mês de carência
    ("Sim", "EM_DIA"),
])
def test_quem_nao_passou_do_prazo_confirmado_continua_com_tudo(banco, portal, em_dia, validade):
    datas = {"VENCIDA": _dias(-60), "CARENCIA": _dias(-10), "EM_DIA": _dias(60), None: None}
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste", anuidade_em_dia=em_dia,
                   anuidade_validade=datas[validade])
    for tela in TELAS_DE_SOCIO:
        assert portal.get(tela).status_code == 200, tela


def test_carencia_avisa_ate_quando_renovar(banco, portal):
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste", anuidade_em_dia="Não",
                   anuidade_validade=_dias(-10))
    html = portal.get("/portal").get_data(as_text=True)
    prazo = (date.today() + timedelta(days=-10 + CARENCIA_DIAS)).strftime("%d/%m/%Y")
    assert f"Renove até {prazo}" in html
    assert 'class="ficha destaque-mini destaque-mini--alerta"' in html


def test_data_vencida_que_o_clube_marca_em_dia_nao_vira_verde_nem_vermelho(banco, portal):
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste", anuidade_em_dia="Sim",
                   anuidade_validade=_dias(-60))
    html = portal.get("/portal").get_data(as_text=True)
    assert "Validade registrada até" in html
    # A classe aplicada ao cartão, não o texto do CSS (que vem na página).
    assert 'class="ficha destaque-mini destaque-mini--' not in html


# --------------------------------------------------------------------
# A sessão se confere sozinha
# --------------------------------------------------------------------

def _sessao_conferida_ha(portal, segundos: int, liberado: bool, bloqueada: bool) -> None:
    with portal.session_transaction() as sessao:
        sessao["e_filiado_ativo"] = liberado
        sessao["anuidade_bloqueada"] = bloqueada
        sessao["socio_conferido_em"] = time.time() - segundos


def test_sessao_antiga_de_quem_passou_do_prazo_perde_o_acesso(ana_fora_do_prazo, portal):
    """O login dizia "liberado" e valia 30 dias. Depois de 10 minutos a
    sessão confere de novo e descobre."""
    _sessao_conferida_ha(portal, 11 * 60, liberado=True, bloqueada=False)
    assert portal.get("/portal/marketplace").status_code == 403


def test_quem_renovou_volta_sem_precisar_sair_e_entrar(banco, portal):
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste", anuidade_em_dia="Sim",
                   anuidade_validade=_dias(300))
    _sessao_conferida_ha(portal, 11 * 60, liberado=False, bloqueada=True)
    assert portal.get("/portal/marketplace").status_code == 200


def test_o_inicio_sempre_confere_na_hora(banco, portal):
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste", anuidade_em_dia="Sim",
                   anuidade_validade=_dias(300))
    _sessao_conferida_ha(portal, 5, liberado=False, bloqueada=True)
    html = portal.get("/portal").get_data(as_text=True)
    assert "/portal/marketplace" in html


# --------------------------------------------------------------------
# Vitrine: anúncio pausado, não apagado
# --------------------------------------------------------------------

def _anuncio_aprovado_do_bruno() -> str:
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000002", categoria="Arma", titulo="Pistola do Bruno",
        contato_telefone="14999990000", fotos=[(b"\x89PNG foto", "foto.png")],
    )
    motor_marketplace.aprovar(EMPRESA_A, anuncio_id, revisado_por="Gestor Teste")
    return anuncio_id


def test_anuncio_de_quem_passou_do_prazo_some_da_vitrine_sem_ser_apagado(banco, portal):
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste", anuidade_em_dia="Sim",
                   anuidade_validade=_dias(300))
    semear_filiado(EMPRESA_A, CPF_BRUNO, "Bruno Teste", anuidade_em_dia="Não",
                   anuidade_validade=_dias(-60))
    anuncio_id = _anuncio_aprovado_do_bruno()

    vitrine = portal.get("/portal/marketplace").get_data(as_text=True)
    assert "Pistola do Bruno" not in vitrine
    assert portal.get(f"/portal/marketplace/{anuncio_id}/foto/0").status_code == 404

    # Continua no banco, aprovado -- é pausa, não remoção.
    assert motor_marketplace.obter_anuncio(EMPRESA_A, anuncio_id)["status"] == motor_marketplace.STATUS_APROVADO


def test_anuncio_volta_quando_o_dono_renova(banco, portal):
    semear_filiado(EMPRESA_A, CPF_ANA, "Ana Teste")
    semear_filiado(EMPRESA_A, CPF_BRUNO, "Bruno Teste", anuidade_em_dia="Não",
                   anuidade_validade=_dias(-10))  # ainda na carência
    anuncio_id = _anuncio_aprovado_do_bruno()

    assert "Pistola do Bruno" in portal.get("/portal/marketplace").get_data(as_text=True)
    assert portal.get(f"/portal/marketplace/{anuncio_id}/foto/0").status_code == 200
