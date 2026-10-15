"""Cor do cartão de Filiação no Início do Portal (2026-10-15): verde
quando ativa, vermelho quando inativa. O que não pode falhar é o terceiro
caso: sem o dado, o cartão fica neutro -- verde por padrão afirmaria uma
situação que ninguém conferiu."""
import pytest

import portal.app as portal_app


def _resumo(status):
    return {
        "tem_registro": True, "indisponivel": False,
        "anuidade_em_dia": "Sim", "anuidade_validade": "08/02/2031",
        "status_filiacao": status,
    }


@pytest.mark.parametrize("status, classe, rotulo", [
    ("Ativo", "destaque-mini--ativo", "Filiação ativa"),
    ("Inativo", "destaque-mini--inativo", "Filiação inativa"),
])
def test_cartao_pinta_conforme_a_situacao(portal, monkeypatch, status, classe, rotulo):
    monkeypatch.setattr(portal_app, "_resumo_filiacao", lambda cpf: _resumo(status))
    html = portal.get("/portal").get_data(as_text=True)
    # O nome da classe também aparece no <style> da página; o que conta é
    # o cartão carregar ela.
    assert f'class="ficha destaque-mini {classe}"' in html
    assert rotulo in html


def test_sem_situacao_fica_neutro(portal, monkeypatch):
    monkeypatch.setattr(portal_app, "_resumo_filiacao", lambda cpf: _resumo(None))
    html = portal.get("/portal").get_data(as_text=True)
    assert "Válida até 08/02/2031" in html
    assert 'class="ficha destaque-mini destaque-mini--' not in html
    assert "Filiação ativa" not in html
