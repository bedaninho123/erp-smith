"""Filtro de período da tela Habitualidade do Portal (2026-10-17).

O atirador escolhe 6, 12, 24 ou 36 meses. O que estes testes guardam:
os cartões e a lista usam o MESMO corte de data (senão o cartão diria
"1 em 6 meses" em cima de uma lista de 4 linhas), e um período fora da
lista volta para 12 em vez de virar uma janela qualquer.
"""
from datetime import date, timedelta

import pytest

import portal.app as portal_app


def _dia(dias_atras: int) -> str:
    return (date.today() - timedelta(days=dias_atras)).strftime("%d/%m/%Y")


@pytest.fixture
def habitualidade_falsa(monkeypatch):
    """Quatro participações espalhadas em 3 anos, sem chamar a API."""
    dados = {"habitualidades": {"ACLP": {"count": 4, "eventos": [
        {"data_participacao": _dia(10), "modalidade": "Mod Recente", "competicao": "TREINO"},
        {"data_participacao": _dia(300), "modalidade": "Mod Oito Meses", "competicao": "TREINO"},
        {"data_participacao": _dia(500), "modalidade": "Mod Dezesseis Meses", "competicao": "Copa X"},
        {"data_participacao": _dia(1000), "modalidade": "Mod Trinta Meses", "competicao": "TREINO"},
    ]}}}
    chamadas = []

    def consultar(cpf, data_inicio=None, data_fim=None):
        chamadas.append({"data_inicio": data_inicio, "data_fim": data_fim})
        return dados

    monkeypatch.setattr(portal_app, "consultar_habitualidade", consultar)
    monkeypatch.setattr(portal_app, "consultar_cr", lambda cpf: None)
    return chamadas


@pytest.fixture
def portal_filiado(portal):
    with portal.session_transaction() as sessao:
        sessao["e_filiado_ativo"] = True
    return portal


@pytest.mark.parametrize("periodo, visiveis", [
    ("6", ["Mod Recente"]),
    ("12", ["Mod Recente", "Mod Oito Meses"]),
    ("24", ["Mod Recente", "Mod Oito Meses", "Mod Dezesseis Meses"]),
    ("36", ["Mod Recente", "Mod Oito Meses", "Mod Dezesseis Meses", "Mod Trinta Meses"]),
])
def test_lista_e_cartao_seguem_o_periodo(banco, portal_filiado, habitualidade_falsa, periodo, visiveis):
    html = portal_filiado.get(f"/portal/habitualidade?periodo={periodo}").get_data(as_text=True)

    todas = ["Mod Recente", "Mod Oito Meses", "Mod Dezesseis Meses", "Mod Trinta Meses"]
    for modalidade in todas:
        assert (modalidade in html) == (modalidade in visiveis), modalidade
    assert f"participações nos últimos {periodo} meses" in html
    assert f"{len(visiveis)} de 4 no total" in html


@pytest.mark.parametrize("periodo", ["6", "12", "36"])
def test_consulta_sempre_pede_36_meses_em_formato_iso(banco, portal_filiado, habitualidade_falsa, periodo):
    """Sem startDate a API real devolve só 12 meses -- e aí os filtros de
    24 e 36 mostrariam o mesmo número do de 12, como se não houvesse nada
    antes. DD/MM/AAAA dá HTTP 500 lá; só AAAA-MM-DD funciona."""
    portal_filiado.get(f"/portal/habitualidade?periodo={periodo}")

    assert habitualidade_falsa[-1]["data_inicio"] == (date.today() - timedelta(days=1095)).isoformat()
    assert habitualidade_falsa[-1]["data_fim"] is None


def test_sem_periodo_ou_periodo_invalido_mostra_12_meses(banco, portal_filiado, habitualidade_falsa):
    for url in ("/portal/habitualidade", "/portal/habitualidade?periodo=999"):
        html = portal_filiado.get(url).get_data(as_text=True)
        assert "participações nos últimos 12 meses" in html
        assert "Mod Oito Meses" in html
        assert "Mod Dezesseis Meses" not in html
