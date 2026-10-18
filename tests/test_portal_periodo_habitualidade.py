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
    monkeypatch.setattr(portal_app, "consultar_habitualidade", lambda cpf: dados)
    monkeypatch.setattr(portal_app, "consultar_cr", lambda cpf: None)


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


def test_sem_periodo_ou_periodo_invalido_mostra_12_meses(banco, portal_filiado, habitualidade_falsa):
    for url in ("/portal/habitualidade", "/portal/habitualidade?periodo=999"):
        html = portal_filiado.get(url).get_data(as_text=True)
        assert "participações nos últimos 12 meses" in html
        assert "Mod Oito Meses" in html
        assert "Mod Dezesseis Meses" not in html
