"""Cadastro de cliente pelo painel, com busca por CPF no Shooting House.

O cadastro nasceu em 2026-08-25 porque ficou claro que **não existe base
para migrar**: o despachante atendia por pasta de papel e WhatsApp, sem
cadastro nenhum. Então o cliente entra um a um, e `cliente.cpf` é a chave
de tudo que vem depois -- consulta de habitualidade, de CR, de arma, e o
portão de identidade que confere quem está pedindo dado sensível.
"""
import pytest

from core.motor_clientes import (
    ClienteInvalido,
    ClienteJaExiste,
    cpf_valido,
    criar_cliente,
)
from integracoes import shooting_house
from integracoes.shooting_house import ShootingHouseIndisponivel, consultar_cadastro

from tests.conftest import EMPRESA_A, EMPRESA_B

CPF_VALIDO = "52998224725"
CPF_DIGITO_ERRADO = "12345678900"


# --------------------------------------------------------------------
# Validação de CPF
# --------------------------------------------------------------------

@pytest.mark.parametrize(
    "cpf, esperado",
    [
        ("529.982.247-25", True),
        ("52998224725", True),
        ("12345678900", False),   # dígito verificador não fecha
        ("111.111.111-11", False),  # dígito repetido
        ("5299822472", False),      # curto demais
        ("", False),
        (None, False),
    ],
)
def test_validacao_de_cpf(cpf, esperado):
    assert cpf_valido(cpf) is esperado


def test_cpf_invalido_nao_vira_cliente(banco):
    """Um dígito trocado aqui não é erro de digitação qualquer: esse CPF
    vira a chave usada pra consultar habitualidade e arma no Shooting
    House, e passaria a buscar a pessoa errada -- ou pessoa nenhuma,
    para sempre."""
    with pytest.raises(ClienteInvalido):
        criar_cliente(EMPRESA_A, nome="Fulano", cpf=CPF_DIGITO_ERRADO)


def test_nome_vazio_nao_vira_cliente(banco):
    with pytest.raises(ClienteInvalido):
        criar_cliente(EMPRESA_A, nome="   ", cpf=CPF_VALIDO)


# --------------------------------------------------------------------
# Criação
# --------------------------------------------------------------------

def test_cria_cliente_guardando_cpf_so_com_digitos(banco):
    cliente = criar_cliente(
        EMPRESA_A, nome="Novo Cliente", cpf="529.982.247-25",
        email="novo@example.com", telefone="(14) 99999-1234", cidade="Marília",
    )

    assert cliente["cliente_id"].startswith("CLI-")
    # O banco guarda só dígitos -- a busca por CPF depende disso.
    assert cliente["cpf"] == CPF_VALIDO


def test_cpf_repetido_na_mesma_empresa_e_recusado(banco):
    criar_cliente(EMPRESA_A, nome="Primeiro", cpf=CPF_VALIDO)

    with pytest.raises(ClienteJaExiste) as erro:
        criar_cliente(EMPRESA_A, nome="Segundo", cpf=CPF_VALIDO)

    # Devolve o cliente_id existente pra tela poder oferecer "abrir a
    # ficha" em vez de só reclamar.
    assert erro.value.cliente_id.startswith("CLI-")


def test_mesmo_cpf_em_outra_empresa_e_permitido(banco):
    """A UNIQUE é (empresa_id, cpf) de propósito: a mesma pessoa pode ser
    cliente de dois despachantes."""
    criar_cliente(EMPRESA_A, nome="Pessoa", cpf=CPF_VALIDO)
    outro = criar_cliente(EMPRESA_B, nome="Pessoa", cpf=CPF_VALIDO)

    assert outro["cliente_id"].startswith("CLI-")


# --------------------------------------------------------------------
# Busca no Shooting House: os três estados
# --------------------------------------------------------------------

def test_busca_simulada_traz_o_cadastro():
    cadastro = consultar_cadastro(CPF_VALIDO)

    assert cadastro["simulado"] is True
    assert cadastro["nome"]
    assert cadastro["cpf"] == CPF_VALIDO


def test_cpf_desconhecido_devolve_none_e_nao_pessoa_inventada():
    """Nem todo cliente do despachante passou pelo clube -- "não é
    filiado" é resposta normal, não erro."""
    assert consultar_cadastro("11144477735") is None


def test_a_busca_nao_traz_arma_nem_cr(monkeypatch):
    """A resposta real de /registers/shooters/{id} vem com armas,
    situação do CR e pendência financeira. Nada disso pode entrar no
    cadastro: seria criar cópia de dado regulatório no nosso banco, que é
    o que "consultar, não copiar" proíbe -- e o Shooting House é quem
    reporta à PF e ao Exército."""
    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(
        shooting_house, "_chamar_api",
        lambda caminho, params=None: {
            "id": 101, "name": "FULANO DE TAL", "cpf": CPF_VALIDO,
            "email": "FULANO@EMAIL.COM", "status": "A",
            "registratitionCode": "F101",
            "address": {"city": "Marília"},
            "phones": {"ddd": "14", "number": "999998888"},
            # Tudo abaixo tem que ser descartado.
            "documents": {"cr": {"number": "CR123", "expirationDate": "2030-01-01"}},
            "rg": "000000000", "birthDate": "1990-01-01",
            "financial": {"status": False},
        },
    )

    cadastro = consultar_cadastro(CPF_VALIDO)

    assert cadastro["nome"] == "FULANO DE TAL"
    assert cadastro["email"] == "fulano@email.com"
    assert cadastro["telefone"] == "(14) 99999-8888"
    assert cadastro["status_filiacao"] == "Ativo"
    for proibido in ("documents", "cr", "rg", "birthDate", "financial", "armas"):
        assert proibido not in cadastro


def test_api_fora_do_ar_nao_vira_pessoa_nao_encontrada(monkeypatch):
    """O erro que mais importa desta tela. Se "não consegui consultar"
    aparecer como "não é filiado", o funcionário redigita tudo à mão
    achando que a pessoa não existe no clube -- e o cadastro nasce com
    dado digitado em vez do dado oficial."""
    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)

    def _fora_do_ar(caminho, params=None):
        raise ShootingHouseIndisponivel("Shooting House respondeu HTTP 503.")

    monkeypatch.setattr(shooting_house, "_chamar_api", _fora_do_ar)

    with pytest.raises(ShootingHouseIndisponivel):
        consultar_cadastro(CPF_VALIDO)


# --------------------------------------------------------------------
# As rotas do painel
# --------------------------------------------------------------------

def test_rota_de_busca_separa_indisponivel_de_nao_encontrado(painel, monkeypatch):
    monkeypatch.setattr(
        "webapp.app.consultar_cadastro",
        lambda cpf: (_ for _ in ()).throw(ShootingHouseIndisponivel("fora do ar")),
    )

    resposta = painel.get(f"/api/clientes/shooting-house/{CPF_VALIDO}")

    assert resposta.status_code == 200
    assert resposta.get_json()["indisponivel"] is True
    assert "encontrado" not in resposta.get_json()


def test_rota_de_busca_devolve_o_cadastro(painel):
    resposta = painel.get(f"/api/clientes/shooting-house/{CPF_VALIDO}")

    dados = resposta.get_json()
    assert dados["encontrado"] is True
    assert dados["simulado"] is True


def test_rota_cria_cliente_na_empresa_da_sessao(painel):
    resposta = painel.post("/api/clientes", json={
        "nome": "Cliente Pela Tela", "cpf": CPF_VALIDO, "email": "tela@example.com",
    })

    assert resposta.status_code == 201
    cliente_id = resposta.get_json()["cliente_id"]

    # E aparece na lista DESTA empresa (o painel está logado na EMPRESA_A).
    lista = painel.get("/api/clientes").get_json()
    assert any(c["cliente_id"] == cliente_id for c in lista)


def test_rota_recusa_cpf_invalido(painel):
    resposta = painel.post("/api/clientes", json={
        "nome": "Fulano", "cpf": CPF_DIGITO_ERRADO,
    })

    assert resposta.status_code == 400
    assert "CPF" in resposta.get_json()["erro"]


def test_rota_devolve_409_com_o_cliente_existente(painel):
    painel.post("/api/clientes", json={"nome": "Primeiro", "cpf": CPF_VALIDO})

    resposta = painel.post("/api/clientes", json={"nome": "Segundo", "cpf": CPF_VALIDO})

    assert resposta.status_code == 409
    assert resposta.get_json()["cliente_id"].startswith("CLI-")
