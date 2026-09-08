"""Marketplace de classificados entre filiados ATIVOS do clube
(2026-09-02).

Três coisas que não podem falhar, na ordem do risco:

1. Só filiado ATIVO acessa -- um cliente que nunca foi filiado (ex.: só
   usou transferência de arma) não pode ver nem publicar.
2. Anúncio nasce Pendente e só aparece pra outros depois de aprovado --
   moderação é o único freio contra conteúdo impróprio num mural visto
   pelo clube inteiro.
3. Isolamento por empresa, mesmo espírito de test_isolamento_portal.py.
"""
import sqlite3

import pytest

from core import motor_marketplace
from motor_ia.conexao import DOMAIN_DB
from tests.conftest import AGORA, EMPRESA_A, EMPRESA_B


def _semear_filiado(empresa_id: str, cpf: str, nome: str, email: str = None, ativo: str = "Ativo") -> None:
    con = sqlite3.connect(DOMAIN_DB)
    con.execute(
        "INSERT INTO filiado (filiado_id, empresa_id, nome, cpf, email, status_filiacao, "
        "criado_em, atualizado_em) VALUES (?,?,?,?,?,?,?,?)",
        (f"FIL-{cpf}", empresa_id, nome, cpf, email, ativo, AGORA, AGORA),
    )
    con.commit()
    con.close()


def _tornar_filiado_ativo(portal_client) -> None:
    """Simula o que entrar() calcula no login de verdade -- os testes de
    rota não precisam refazer o fluxo de token pra isso, só o efeito."""
    with portal_client.session_transaction() as sessao:
        sessao["e_filiado_ativo"] = True


# --------------------------------------------------------------------
# Quem pode ver e publicar
# --------------------------------------------------------------------

def test_cliente_que_nao_e_filiado_nao_acessa_marketplace(banco, portal):
    """Ana (CLI-000001) é cliente, mas nenhum filiado foi semeado pra ela
    -- é o caso "só usou transferência de arma"."""
    resposta = portal.get("/portal/marketplace")
    assert resposta.status_code == 403


def test_filiado_inativo_nao_acessa_marketplace(banco, portal):
    _semear_filiado(EMPRESA_A, "11111111111", "Ana Teste", ativo="Inativo")
    with portal.session_transaction() as sessao:
        sessao["e_filiado_ativo"] = False  # mesmo cálculo que entrar() faria: inativo = False
    resposta = portal.get("/portal/marketplace")
    assert resposta.status_code == 403


def test_filiado_ativo_acessa_marketplace(banco, portal):
    _tornar_filiado_ativo(portal)
    resposta = portal.get("/portal/marketplace")
    assert resposta.status_code == 200


def test_habitualidade_tambem_e_exclusiva_de_filiado(banco, portal):
    """Mesma regra do Marketplace -- confirmando que não regredi a tela
    que já existia."""
    resposta = portal.get("/portal/habitualidade")
    assert resposta.status_code == 403


# --------------------------------------------------------------------
# Moderação: nasce Pendente, só aparece depois de aprovado
# --------------------------------------------------------------------

def test_anuncio_nasce_pendente_e_nao_aparece_na_vitrine(banco):
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Pistola 9mm",
        contato_telefone="14999990000",
    )
    guardado = motor_marketplace.obter_anuncio(EMPRESA_A, anuncio_id)
    assert guardado["status"] == "Pendente"

    vitrine = motor_marketplace.listar_anuncios(EMPRESA_A, status=motor_marketplace.STATUS_APROVADO)
    assert vitrine == []


def test_anuncio_aparece_na_vitrine_depois_de_aprovado(banco):
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Pistola 9mm",
        contato_telefone="14999990000",
    )
    motor_marketplace.aprovar(EMPRESA_A, anuncio_id, revisado_por="Gestor Teste")

    vitrine = motor_marketplace.listar_anuncios(EMPRESA_A, status=motor_marketplace.STATUS_APROVADO)
    assert [a["anuncio_id"] for a in vitrine] == [anuncio_id]


def test_recusar_exige_motivo(banco):
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Pistola 9mm",
        contato_telefone="14999990000",
    )
    with pytest.raises(motor_marketplace.AnuncioInvalido, match="motivo"):
        motor_marketplace.recusar(EMPRESA_A, anuncio_id, "   ", revisado_por="Gestor Teste")


def test_anuncio_sem_nenhum_contato_e_recusado(banco):
    with pytest.raises(motor_marketplace.AnuncioInvalido, match="contato"):
        motor_marketplace.criar_anuncio(
            EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Pistola 9mm",
        )


def test_criar_anuncio_nao_tem_campo_de_serie() -> None:
    """Estrutural: garante que ninguém acrescente um parâmetro `serie`
    a criar_anuncio() sem que este teste force uma decisão consciente --
    número de série nunca pode aparecer num anúncio visto pelo clube
    inteiro."""
    import inspect
    parametros = set(inspect.signature(motor_marketplace.criar_anuncio).parameters)
    assert "serie" not in parametros
    assert "numero_serie" not in parametros


def test_municao_nao_esta_no_catalogo_de_categorias() -> None:
    from domain.clube_tiro.categorias_marketplace import CATEGORIAS
    assert not any("muni" in c.lower() for c in CATEGORIAS)


# --------------------------------------------------------------------
# Isolamento entre empresas
# --------------------------------------------------------------------

def test_anuncio_nao_atravessa_empresa(banco):
    motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Pistola da empresa A",
        contato_telefone="14999990000",
    )
    motor_marketplace.criar_anuncio(
        EMPRESA_B, "CLI-000003", categoria="Arma", titulo="Pistola da empresa B",
        contato_telefone="14999990000",
    )

    da_a = motor_marketplace.listar_anuncios(EMPRESA_A)
    assert [a["titulo"] for a in da_a] == ["Pistola da empresa A"]


def test_painel_nao_lista_anuncio_de_outra_empresa(banco, painel):
    motor_marketplace.criar_anuncio(
        EMPRESA_B, "CLI-000003", categoria="Arma", titulo="Pistola da empresa B",
        contato_telefone="14999990000",
    )
    resposta = painel.get("/api/marketplace")
    assert resposta.get_json() == []


# --------------------------------------------------------------------
# Edição pelo painel (2026-09-02) -- corrige texto/preço, não mexe em status
# --------------------------------------------------------------------

def test_editar_anuncio_corrige_texto_sem_mudar_status(banco):
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Titulo com erro",
        contato_telefone="14999990000",
    )
    motor_marketplace.aprovar(EMPRESA_A, anuncio_id, revisado_por="Gestor Teste")

    motor_marketplace.editar_anuncio(
        EMPRESA_A, anuncio_id, categoria="Equipamento", titulo="Titulo corrigido",
        valor=1200.50, contato_telefone="14988887777",
    )

    guardado = motor_marketplace.obter_anuncio(EMPRESA_A, anuncio_id)
    assert guardado["titulo"] == "Titulo corrigido"
    assert guardado["categoria"] == "Equipamento"
    assert guardado["valor"] == 1200.50
    assert guardado["status"] == "Aprovado"  # edição de texto não mexe em moderação


def test_editar_anuncio_exige_titulo_e_contato(banco):
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Original",
        contato_telefone="14999990000",
    )
    with pytest.raises(motor_marketplace.AnuncioInvalido):
        motor_marketplace.editar_anuncio(EMPRESA_A, anuncio_id, categoria="Arma", titulo="")
    with pytest.raises(motor_marketplace.AnuncioInvalido):
        motor_marketplace.editar_anuncio(EMPRESA_A, anuncio_id, categoria="Arma", titulo="Novo titulo")


def test_painel_edita_anuncio_pela_rota(banco, painel):
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Original",
        contato_telefone="14999990000",
    )
    resposta = painel.post(
        f"/api/marketplace/{anuncio_id}/editar",
        json={"categoria": "Arma", "titulo": "Editado pelo painel",
              "contato_telefone": "14999990000", "valor": 900},
    )
    assert resposta.status_code == 200
    assert motor_marketplace.obter_anuncio(EMPRESA_A, anuncio_id)["titulo"] == "Editado pelo painel"


def test_painel_nao_edita_anuncio_de_outra_empresa(banco, painel):
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_B, "CLI-000003", categoria="Arma", titulo="Da empresa B",
        contato_telefone="14999990000",
    )
    resposta = painel.post(
        f"/api/marketplace/{anuncio_id}/editar",
        json={"categoria": "Arma", "titulo": "Tentativa de editar", "contato_telefone": "0"},
    )
    assert resposta.status_code == 400
    assert motor_marketplace.obter_anuncio(EMPRESA_B, anuncio_id)["titulo"] == "Da empresa B"


def test_painel_remove_anuncio_pendente_direto(banco, painel):
    """Remover não exige passar por aprovar/recusar primeiro -- staff
    pode tirar um anúncio impróprio da fila sem precisar aprová-lo antes."""
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Impróprio",
        contato_telefone="14999990000",
    )
    resposta = painel.post(f"/api/marketplace/{anuncio_id}/remover")
    assert resposta.status_code == 200
    assert motor_marketplace.obter_anuncio(EMPRESA_A, anuncio_id)["status"] == "Removido"


# --------------------------------------------------------------------
# Login cria cliente pro filiado que nunca usou o despachante
# --------------------------------------------------------------------

def test_login_cria_cliente_para_filiado_sem_cadastro_previo(banco):
    """William nunca foi cliente do despachante, só filiado do clube --
    pedir o link de acesso precisa criar o cadastro mínimo na hora."""
    _semear_filiado(EMPRESA_A, "52998224725", "William Filiado", email="william@example.com")

    from portal.app import app
    app.config.update(TESTING=True)
    cliente_http = app.test_client()

    resposta = cliente_http.post("/portal/login", data={"identificador": "william@example.com"})
    assert resposta.status_code == 200

    from core.conexao import conectar
    con = conectar(EMPRESA_A)
    linha = con.execute(
        "SELECT nome FROM cliente WHERE empresa_id = ? AND cpf = ?",
        (EMPRESA_A, "52998224725"),
    ).fetchone()
    con.close()
    assert linha is not None
    assert linha["nome"] == "William Filiado"


def test_login_nao_duplica_cliente_ja_existente(banco):
    """Ana já é cliente -- mesmo sendo filiada também, o login não pode
    tentar criar um segundo cadastro pra ela."""
    _semear_filiado(EMPRESA_A, "11111111111", "Ana Teste", email="ana@example.com")

    from portal.app import app
    app.config.update(TESTING=True)
    cliente_http = app.test_client()
    cliente_http.post("/portal/login", data={"identificador": "ana@example.com"})

    from core.conexao import conectar
    con = conectar(EMPRESA_A)
    total = con.execute(
        "SELECT COUNT(*) FROM cliente WHERE empresa_id = ? AND cpf = ?",
        (EMPRESA_A, "11111111111"),
    ).fetchone()[0]
    con.close()
    assert total == 1


# --------------------------------------------------------------------
# CTA "Preciso de ajuda com a documentação"
# --------------------------------------------------------------------

def test_botao_documentacao_cria_caso_de_transferencia(banco, portal):
    """O fixture `banco` já cadastra o serviço "Transferência de Arma"
    pra toda empresa -- ver tests/conftest.py."""
    _tornar_filiado_ativo(portal)
    anuncio_id = motor_marketplace.criar_anuncio(
        EMPRESA_A, "CLI-000001", categoria="Arma", titulo="Pistola 9mm",
        contato_telefone="14999990000",
    )

    resposta = portal.post(f"/portal/marketplace/{anuncio_id}/documentacao")
    assert resposta.status_code in (200, 302)

    from core.conexao import conectar
    con = conectar(EMPRESA_A)
    titulos = [
        l["titulo"] for l in con.execute(
            "SELECT titulo FROM caso WHERE empresa_id = ? AND cliente_id = ?",
            (EMPRESA_A, "CLI-000001"),
        ).fetchall()
    ]
    con.close()
    assert any("Transferência" in t for t in titulos)
