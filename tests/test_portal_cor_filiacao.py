"""Cor do cartão de Filiação no Início do Portal (2026-10-15): verde
quando ativa, vermelho quando inativa. O que não pode falhar é o terceiro
caso: sem o dado, o cartão fica neutro -- verde por padrão afirmaria uma
situação que ninguém conferiu.

Desde 2026-11-10 a cor sai de `_resumo_filiacao(situacao)`, a mesma conta
que decide o menu (ver tests/test_anuidade_carencia.py para as cores da
anuidade). Estes testes passam pelo caminho de verdade, com a filiada no
retrato, em vez de trocar a função por uma cópia do formato antigo."""
import pytest

from tests.conftest import EMPRESA_A, semear_filiado


def _ana(status):
    semear_filiado(EMPRESA_A, "11111111111", "Ana Teste", status=status,
                   anuidade_em_dia="Sim", anuidade_validade="2031-02-08")


@pytest.mark.parametrize("status, classe, rotulo", [
    ("Ativo", "destaque-mini--ativo", "Filiação ativa"),
    ("Inativo", "destaque-mini--inativo", "Filiação inativa"),
])
def test_cartao_pinta_conforme_a_situacao(portal, status, classe, rotulo):
    _ana(status)
    html = portal.get("/portal").get_data(as_text=True)
    # O nome da classe também aparece no <style> da página; o que conta é
    # o cartão carregar ela.
    assert f'class="ficha destaque-mini {classe}"' in html
    assert rotulo in html


def test_sem_situacao_fica_neutro(portal):
    _ana(None)
    html = portal.get("/portal").get_data(as_text=True)
    assert "Válida até 08/02/2031" in html
    assert 'class="ficha destaque-mini destaque-mini--' not in html
    assert "Filiação ativa" not in html


ICONE_CERTO = "M5 10.5l3.2 3.2L15 7"


@pytest.mark.parametrize("status, tem_certo", [("Ativo", True), ("Inativo", False), (None, False)])
def test_icone_de_certo_so_quando_ativa(portal, status, tem_certo):
    _ana(status)
    assert (ICONE_CERTO in portal.get("/portal").get_data(as_text=True)) is tem_certo
