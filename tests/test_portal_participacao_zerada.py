"""Filiado sem participação não pode ler "consulta indisponível" (2026-11-04).

`consultar_cr` ainda não tem modo real e levanta sempre em produção. Quando
isso contava como falha da consulta, todo filiado sem participação no período
via o aviso de sistema fora do ar, com o Shooting House respondendo normalmente.

O outro lado guarda a regra antiga: se a HABITUALIDADE falha, o aviso continua,
porque "não consegui consultar" nunca pode virar "você não treinou".
"""
from datetime import date, timedelta

import pytest

import portal.app as portal_app
from integracoes.shooting_house import ShootingHouseIndisponivel

AVISOS_DE_FALHA = ("Consulta indisponível", "Não foi possível consultar")


def _falha(*_args, **_kwargs):
    raise ShootingHouseIndisponivel("fora do ar")


def _com_participacao_antiga(*_args, **_kwargs):
    dia = (date.today() - timedelta(days=500)).strftime("%d/%m/%Y")
    return {"habitualidades": {"ACLP": {"count": 1, "eventos": [
        {"data_participacao": dia, "modalidade": "Mod Antiga", "competicao": "TREINO"},
    ]}}}


@pytest.fixture
def como_em_producao(monkeypatch):
    """CR sempre falha; a habitualidade responde lista vazia."""
    monkeypatch.setattr(portal_app, "consultar_cr", _falha)
    monkeypatch.setattr(portal_app, "consultar_habitualidade", lambda *_a, **_k: {"habitualidades": {}})
    monkeypatch.setattr(portal_app, "consultar_ficha_completa", lambda _cpf: None)


@pytest.fixture
def filiado(portal):
    with portal.session_transaction() as sessao:
        sessao["e_filiado_ativo"] = True
    return portal


def test_inicio_de_filiado_sem_participacao_diz_que_nao_teve(banco, filiado, como_em_producao):
    html = filiado.get("/portal").get_data(as_text=True)

    assert "Nenhuma participação em 12 meses" in html
    assert "Sem registro de atirador" not in html
    for aviso in AVISOS_DE_FALHA:
        assert aviso not in html


def test_inicio_de_quem_nao_e_filiado_nao_leva_a_habitualidade(banco, portal, monkeypatch):
    """A rota responde 403 cru para quem não é filiado, então o Início não
    pode ter caminho até ela. E nem consulta o Shooting House à toa."""
    monkeypatch.setattr(portal_app, "consultar_ficha_completa", lambda _cpf: None)
    monkeypatch.setattr(portal_app, "_resumo_habitualidade", _falha)

    resposta = portal.get("/portal")
    html = resposta.get_data(as_text=True)

    assert resposta.status_code == 200
    assert 'href="/portal/habitualidade"' not in html
    assert "Sem registro de atirador" not in html
    assert "Nenhuma participação em 12 meses" not in html


def test_inicio_de_filiado_continua_levando_a_habitualidade(banco, filiado, como_em_producao):
    assert 'href="/portal/habitualidade"' in filiado.get("/portal").get_data(as_text=True)


def test_habitualidade_sem_participacao_mostra_zero_e_nao_falha(banco, filiado, como_em_producao):
    html = filiado.get("/portal/habitualidade").get_data(as_text=True)

    assert "Nenhuma participação registrada nos últimos 36 meses" in html
    assert "registro de atirador" not in html
    for aviso in AVISOS_DE_FALHA:
        assert aviso not in html


def test_participacao_antiga_oferece_periodo_maior(banco, filiado, monkeypatch):
    """Era o caso mais enganoso: quem treinou há 16 meses lia "falha" no
    filtro padrão de 12, sem o filtro na tela para achar o próprio treino."""
    monkeypatch.setattr(portal_app, "consultar_cr", _falha)
    monkeypatch.setattr(portal_app, "consultar_habitualidade", _com_participacao_antiga)

    html = filiado.get("/portal/habitualidade").get_data(as_text=True)

    assert "Escolha um período maior" in html
    assert "periodo=24" in html
    for aviso in AVISOS_DE_FALHA:
        assert aviso not in html


def test_folha_sai_quando_a_consulta_respondeu_vazio(banco, filiado, como_em_producao):
    html = filiado.get("/portal/habitualidade/imprimir").get_data(as_text=True)

    assert "Nenhuma participação registrada nos últimos 12 meses" in html
    assert 'id="botao-imprimir"' in html


@pytest.mark.parametrize("rota, aviso", [
    ("/portal", "Consulta indisponível"),
    ("/portal/habitualidade", "Não foi possível consultar"),
    ("/portal/habitualidade/imprimir", "Não foi possível consultar"),
])
def test_falha_de_verdade_na_habitualidade_continua_avisando(banco, filiado, monkeypatch, rota, aviso):
    monkeypatch.setattr(portal_app, "consultar_cr", _falha)
    monkeypatch.setattr(portal_app, "consultar_habitualidade", _falha)
    monkeypatch.setattr(portal_app, "consultar_ficha_completa", lambda _cpf: None)

    html = filiado.get(rota).get_data(as_text=True)

    assert aviso in html
    assert "Nenhuma participação" not in html
