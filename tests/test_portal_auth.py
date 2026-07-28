"""Login sem senha do Portal -- o link mágico (core/motor_portal_auth.py).

O token é a única credencial do Portal: quem tem o link, entra. Por isso
as três garantias testadas aqui (uso único, expiração e rejeição do
inválido) são o que impede uma sessão de cliente ser aberta por quem não
deveria.

Com multi-tenant entra uma quarta: o token vale numa empresa só. Ele
continua sendo único globalmente (é segredo de autenticação), mas
apresentá-lo no Portal da empresa errada não abre sessão nenhuma.
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
from core.conexao import conectar_admin

from tests.conftest import EMPRESA_A, EMPRESA_B


def test_token_valido_devolve_o_dono(banco):
    token = criar_token(EMPRESA_A, "CLI-000001")

    assert validar_e_consumir_token(EMPRESA_A, token) == "CLI-000001"


def test_token_nao_serve_duas_vezes(banco):
    """Uso único de verdade: se o link vazar depois de usado (encaminhado
    sem querer, histórico do navegador), ele já não abre nada."""
    token = criar_token(EMPRESA_A, "CLI-000001")

    assert validar_e_consumir_token(EMPRESA_A, token) == "CLI-000001"
    assert validar_e_consumir_token(EMPRESA_A, token) is None


def test_token_expirado_nao_serve(banco):
    token = criar_token(EMPRESA_A, "CLI-000001")

    # Envelhece o token no banco em vez de esperar 15 minutos de verdade.
    expirado = _iso(_agora() - timedelta(minutes=1))
    con = conectar_admin()
    con.execute("UPDATE portal_token SET expira_em = ? WHERE token = ?", (expirado, token))
    con.commit()
    con.close()

    assert validar_e_consumir_token(EMPRESA_A, token) is None


def test_token_inexistente_nao_serve(banco):
    assert validar_e_consumir_token(EMPRESA_A, "token-que-nunca-existiu") is None


@pytest.mark.parametrize("valor", ["", None])
def test_token_vazio_nao_serve(banco, valor):
    assert validar_e_consumir_token(EMPRESA_A, valor) is None


def test_token_de_um_cliente_nunca_abre_sessao_de_outro(banco):
    """Garantia central: o token carrega o dono, e é o dono do token que
    vira a sessão -- nunca o cliente que aparece na URL ou no formulário."""
    token_da_ana = criar_token(EMPRESA_A, "CLI-000001")

    assert validar_e_consumir_token(EMPRESA_A, token_da_ana) != "CLI-000002"


def test_expiracao_configurada_bate_com_o_que_o_email_promete(banco):
    """O e-mail enviado ao cliente diz "válido por 15 minutos"
    (portal/app.py). Se alguém mudar a constante e esquecer o texto, o
    Portal passa a mentir pro cliente."""
    assert TOKEN_VALIDADE_MINUTOS == 15


# --------------------------------------------------------------------
# O token não atravessa a fronteira da empresa
# --------------------------------------------------------------------

def test_token_de_uma_empresa_nao_vale_na_outra(banco):
    """Se este teste falhar, um link de acesso legítimo apresentado no
    Portal do despachante errado abriria a sessão do cliente lá dentro."""
    token_da_ana = criar_token(EMPRESA_A, "CLI-000001")

    assert validar_e_consumir_token(EMPRESA_B, token_da_ana) is None


def test_token_recusado_na_empresa_errada_continua_valido_na_certa(banco):
    """Controle: a recusa acima não pode consumir o token de quem tinha
    direito a ele -- senão dava pra invalidar o acesso alheio de fora."""
    token_da_ana = criar_token(EMPRESA_A, "CLI-000001")

    validar_e_consumir_token(EMPRESA_B, token_da_ana)

    assert validar_e_consumir_token(EMPRESA_A, token_da_ana) == "CLI-000001"


def test_nao_cria_token_para_cliente_de_outra_empresa(banco):
    with pytest.raises(ValueError):
        criar_token(EMPRESA_B, "CLI-000001")


# --------------------------------------------------------------------
# Busca do cliente no formulário de login
# --------------------------------------------------------------------

def test_encontra_cliente_por_cpf_com_pontuacao(banco):
    cliente = localizar_cliente_por_cpf_ou_email(EMPRESA_A, "111.111.111-11")

    assert cliente is not None
    assert cliente["cliente_id"] == "CLI-000001"


def test_encontra_cliente_por_email_ignorando_maiuscula(banco):
    cliente = localizar_cliente_por_cpf_ou_email(EMPRESA_A, "ANA@example.com")

    assert cliente is not None
    assert cliente["cliente_id"] == "CLI-000001"


def test_cpf_desconhecido_nao_encontra_ninguem(banco):
    assert localizar_cliente_por_cpf_ou_email(EMPRESA_A, "99999999999") is None


def test_mesmo_cpf_em_duas_empresas_devolve_o_cliente_certo(banco):
    """Ana (EMP-000001) e Carla (EMP-000002) têm o mesmo CPF -- é o
    cenário que a UNIQUE composta passou a permitir de propósito. Cada
    Portal tem que encontrar a SUA cliente; devolver a outra mandaria o
    link de acesso ao cadastro errado."""
    na_empresa_a = localizar_cliente_por_cpf_ou_email(EMPRESA_A, "11111111111")
    na_empresa_b = localizar_cliente_por_cpf_ou_email(EMPRESA_B, "11111111111")

    assert na_empresa_a["cliente_id"] == "CLI-000001"
    assert na_empresa_b["cliente_id"] == "CLI-000003"
