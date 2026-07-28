"""Login sem senha do Portal -- o link mágico (core/motor_portal_auth.py).

O token é a única credencial do Portal: quem tem o link, entra. Por isso
as três garantias testadas aqui (uso único, expiração e rejeição do
inválido) são o que impede uma sessão de cliente ser aberta por quem não
deveria.
"""
from datetime import timedelta

import pytest

from core.motor_portal_auth import (
    TOKEN_VALIDADE_MINUTOS,
    _agora,
    _iso,
    criar_token,
    localizar_cliente_por_cpf_ou_email,
    validar_e_consumir_token,
)
from core.conexao import conectar


def test_token_valido_devolve_o_dono(banco):
    token = criar_token("CLI-000001")

    assert validar_e_consumir_token(token) == "CLI-000001"


def test_token_nao_serve_duas_vezes(banco):
    """Uso único de verdade: se o link vazar depois de usado (encaminhado
    sem querer, histórico do navegador), ele já não abre nada."""
    token = criar_token("CLI-000001")

    assert validar_e_consumir_token(token) == "CLI-000001"
    assert validar_e_consumir_token(token) is None


def test_token_expirado_nao_serve(banco):
    token = criar_token("CLI-000001")

    # Envelhece o token no banco em vez de esperar 15 minutos de verdade.
    expirado = _iso(_agora() - timedelta(minutes=1))
    con = conectar()
    con.execute("UPDATE portal_token SET expira_em = ? WHERE token = ?", (expirado, token))
    con.commit()
    con.close()

    assert validar_e_consumir_token(token) is None


def test_token_inexistente_nao_serve(banco):
    assert validar_e_consumir_token("token-que-nunca-existiu") is None


@pytest.mark.parametrize("valor", ["", None])
def test_token_vazio_nao_serve(banco, valor):
    assert validar_e_consumir_token(valor) is None


def test_token_de_um_cliente_nunca_abre_sessao_de_outro(banco):
    """Garantia central: o token carrega o dono, e é o dono do token que
    vira a sessão -- nunca o cliente que aparece na URL ou no formulário."""
    token_da_ana = criar_token("CLI-000001")

    assert validar_e_consumir_token(token_da_ana) != "CLI-000002"


def test_expiracao_configurada_bate_com_o_que_o_email_promete(banco):
    """O e-mail enviado ao cliente diz "válido por 15 minutos"
    (portal/app.py). Se alguém mudar a constante e esquecer o texto, o
    Portal passa a mentir pro cliente."""
    assert TOKEN_VALIDADE_MINUTOS == 15


# --------------------------------------------------------------------
# Busca do cliente no formulário de login
# --------------------------------------------------------------------

def test_encontra_cliente_por_cpf_com_pontuacao(banco):
    cliente = localizar_cliente_por_cpf_ou_email("111.111.111-11")

    assert cliente is not None
    assert cliente["cliente_id"] == "CLI-000001"


def test_encontra_cliente_por_email_ignorando_maiuscula(banco):
    cliente = localizar_cliente_por_cpf_ou_email("ANA@example.com")

    assert cliente is not None
    assert cliente["cliente_id"] == "CLI-000001"


def test_cpf_desconhecido_nao_encontra_ninguem(banco):
    assert localizar_cliente_por_cpf_ou_email("99999999999") is None
