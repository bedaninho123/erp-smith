"""Remetente de e-mail que ainda não é cliente (2026-10-07).

Antes disto, o e-mail de quem não estava cadastrado era lido, a IA
escrevia a resposta, e nada era guardado: não aparecia em Aprovações nem
em Atendimentos. Descoberto no primeiro teste da caixa nova -- que começou
do zero, então seria quase todo e-mail.

Dois blocos: a migração que tirou o NOT NULL de `cliente.cpf` (copia e
apaga a tabela de clientes -- a mesma classe de risco de
test_migracao_dossie.py) e o comportamento novo.
"""
import re
import sqlite3

import pytest

from core.conexao import CORE_DB, conectar, conectar_admin
from core.db.migrar_cliente_sem_cpf import migrar
from core.motor_clientes import (
    ClienteInvalido, ClienteJaExiste, informar_cpf, obter_ou_criar_contato_por_email,
    remetente_automatico,
)
from motor_ia.classificador import ResultadoClassificacao
from tests.conftest import EMPRESA_A, EMPRESA_B

CPF_VALIDO = "52998224725"


# --------------------------------------------------------------------
# 1. A migração
# --------------------------------------------------------------------

@pytest.fixture
def banco_antigo(banco):
    """Devolve `cliente` ao formato de antes (cpf NOT NULL), com os
    clientes, casos e views do fixture no lugar."""
    con = sqlite3.connect(CORE_DB)
    con.isolation_level = None
    con.execute("PRAGMA foreign_keys = OFF")
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name = 'cliente'").fetchone()[0]
    sql_antigo, trocas = re.subn(r"\bcpf(\s+)TEXT,", r"cpf\1TEXT NOT NULL,", sql, count=1)
    assert trocas == 1
    views = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'view' AND sql LIKE '%cliente%'"
    ).fetchall()
    con.execute("BEGIN")
    for nome, _ in views:
        con.execute(f'DROP VIEW "{nome}"')
    con.execute(sql_antigo.replace("CREATE TABLE cliente", "CREATE TABLE cliente_velha", 1))
    con.execute("INSERT INTO cliente_velha SELECT * FROM cliente")
    con.execute("DROP TABLE cliente")
    con.execute("ALTER TABLE cliente_velha RENAME TO cliente")
    con.execute("CREATE INDEX idx_cliente_empresa_id ON cliente(empresa_id)")
    for _, sql_view in views:
        con.execute(sql_view)
    con.execute("COMMIT")
    con.close()
    return banco


def _clientes():
    con = conectar_admin()
    linhas = {l["cliente_id"]: dict(l) for l in con.execute("SELECT * FROM cliente")}
    con.close()
    return linhas


def test_fixture_reproduz_o_formato_antigo(banco_antigo):
    """Controle: sem isto, o teste de baixo passaria migrando uma tabela
    que já estava migrada."""
    con = conectar_admin()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, status, "
            "atendimento_ia, data_cadastro) VALUES ('CLI-999999', ?, 'X', NULL, "
            "'Ativo', 'Sim', '2026-10-07T00:00:00Z')",
            (EMPRESA_A,),
        )
    con.close()


def test_migracao_preserva_cada_cliente_campo_a_campo(banco_antigo):
    antes = _clientes()

    saida = migrar()

    assert saida == {"migrada": True, "clientes": 3, "antes": 3}
    assert _clientes() == antes


def test_depois_da_migracao_cpf_vazio_entra_e_o_resto_continua_de_pe(banco_antigo):
    migrar()

    con = conectar_admin()
    con.execute(
        "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, status, "
        "atendimento_ia, data_cadastro) VALUES ('CLI-999999', ?, 'Sem CPF', NULL, "
        "'Ativo', 'Sim', '2026-10-07T00:00:00Z')",
        (EMPRESA_A,),
    )
    # Dois sem CPF na mesma empresa: NULL não colide com NULL no UNIQUE.
    con.execute(
        "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, status, "
        "atendimento_ia, data_cadastro) VALUES ('CLI-999998', ?, 'Outro', NULL, "
        "'Ativo', 'Sim', '2026-10-07T00:00:00Z')",
        (EMPRESA_A,),
    )
    # O UNIQUE de CPF preenchido continua valendo.
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, status, "
            "atendimento_ia, data_cadastro) VALUES ('CLI-999997', ?, 'Dup', '11111111111', "
            "'Ativo', 'Sim', '2026-10-07T00:00:00Z')",
            (EMPRESA_A,),
        )
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.commit()
    con.close()

    # As views foram recriadas e continuam filtrando por empresa.
    con = conectar(EMPRESA_A)
    ids = {l["cliente_id"] for l in con.execute("SELECT cliente_id FROM VW_CLIENTE")}
    con.close()
    assert "CLI-000003" not in ids
    assert {"CLI-000001", "CLI-000002", "CLI-999999"} <= ids


def test_migracao_e_idempotente(banco_antigo):
    migrar()
    assert migrar() == {"migrada": False, "clientes": 3}


# --------------------------------------------------------------------
# 2. O contato automático
# --------------------------------------------------------------------

@pytest.mark.parametrize("email", [
    "no-reply@accounts.google.com", "noreply@google.com", "NoReply@x.com",
    "do-not-reply@banco.com", "mailer-daemon@googlemail.com", "postmaster@x.com",
    "no-reply+abc@x.com",
])
def test_remetente_automatico_e_reconhecido(email):
    assert remetente_automatico(email)


@pytest.mark.parametrize("email", [
    "joao@gmail.com", "noreplyjoao@x.com", "atendimento@clube.com", "replyto@x.com",
])
def test_pessoa_de_verdade_nao_e_confundida_com_robo(email):
    assert not remetente_automatico(email)


def test_remetente_novo_vira_cadastro_sem_cpf(banco):
    contato = obter_ou_criar_contato_por_email(EMPRESA_A, "novo@example.com", "Pedro Novo")

    assert contato["cpf"] is None
    con = conectar_admin()
    linha = con.execute(
        "SELECT * FROM cliente WHERE cliente_id = ?", (contato["cliente_id"],)
    ).fetchone()
    con.close()
    assert linha["empresa_id"] == EMPRESA_A
    assert linha["nome"] == "Pedro Novo"
    assert linha["cpf"] is None
    assert "Falta informar o CPF" in linha["observacoes"]


def test_segundo_email_do_mesmo_remetente_nao_duplica(banco):
    primeiro = obter_ou_criar_contato_por_email(EMPRESA_A, "novo@example.com", "Pedro")
    segundo = obter_ou_criar_contato_por_email(EMPRESA_A, "NOVO@example.com", "Pedro")
    assert primeiro["cliente_id"] == segundo["cliente_id"]


def test_sem_nome_usa_o_comeco_do_email(banco):
    contato = obter_ou_criar_contato_por_email(EMPRESA_A, "pedro.novo@example.com")
    assert contato["nome"] == "pedro.novo"


def test_robo_e_email_ambiguo_nao_viram_cadastro(banco):
    assert obter_ou_criar_contato_por_email(EMPRESA_A, "no-reply@google.com") is None
    assert obter_ou_criar_contato_por_email(EMPRESA_A, "") is None

    con = conectar_admin()
    con.execute("UPDATE cliente SET email = 'casal@example.com' WHERE cliente_id IN ('CLI-000001', 'CLI-000002')")
    con.commit()
    total_antes = con.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    con.close()

    assert obter_ou_criar_contato_por_email(EMPRESA_A, "casal@example.com") is None
    con = conectar_admin()
    assert con.execute("SELECT COUNT(*) FROM cliente").fetchone()[0] == total_antes
    con.close()


def test_contato_da_outra_empresa_nao_e_reaproveitado(banco):
    """carla@example.com é cliente da empresa B. Escrevendo para a A, ela
    vira contato NOVO da A -- nunca o cadastro da B."""
    contato = obter_ou_criar_contato_por_email(EMPRESA_A, "carla@example.com", "Carla")
    assert contato["cliente_id"] != "CLI-000003"
    assert contato["empresa_id"] == EMPRESA_A


# --------------------------------------------------------------------
# 3. Completar o CPF depois
# --------------------------------------------------------------------

def test_informar_cpf_completa_o_cadastro(banco):
    contato = obter_ou_criar_contato_por_email(EMPRESA_A, "novo@example.com", "Pedro")
    informar_cpf(EMPRESA_A, contato["cliente_id"], "529.982.247-25")
    assert _clientes()[contato["cliente_id"]]["cpf"] == CPF_VALIDO


def test_informar_cpf_recusa_cpf_invalido_e_cadastro_que_ja_tem(banco):
    contato = obter_ou_criar_contato_por_email(EMPRESA_A, "novo@example.com", "Pedro")
    with pytest.raises(ClienteInvalido):
        informar_cpf(EMPRESA_A, contato["cliente_id"], "123.456.789-00")
    # Nunca troca um CPF existente -- corrigir CPF é outra operação.
    with pytest.raises(ClienteInvalido):
        informar_cpf(EMPRESA_A, "CLI-000001", CPF_VALIDO)


def test_informar_cpf_de_outro_cliente_aponta_quem_e(banco):
    """O cliente antigo que escreveu de um e-mail novo. (O CPF do fixture
    não passa no dígito verificador, então a Ana ganha um válido aqui.)"""
    con = conectar_admin()
    con.execute("UPDATE cliente SET cpf = ? WHERE cliente_id = 'CLI-000001'", (CPF_VALIDO,))
    con.commit()
    con.close()
    contato = obter_ou_criar_contato_por_email(EMPRESA_A, "ana.nova@example.com", "Ana")
    with pytest.raises(ClienteJaExiste) as erro:
        informar_cpf(EMPRESA_A, contato["cliente_id"], CPF_VALIDO)
    assert erro.value.cliente_id == "CLI-000001"


def test_informar_cpf_nao_alcanca_cliente_de_outra_empresa(banco):
    con = conectar_admin()
    con.execute(
        "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, status, "
        "atendimento_ia, data_cadastro) VALUES ('CLI-000099', ?, 'Da B', NULL, "
        "'Ativo', 'Sim', '2026-10-07T00:00:00Z')",
        (EMPRESA_B,),
    )
    con.commit()
    con.close()
    with pytest.raises(ClienteInvalido):
        informar_cpf(EMPRESA_A, "CLI-000099", CPF_VALIDO)


def test_rota_do_painel_informa_cpf(painel):
    contato = obter_ou_criar_contato_por_email(EMPRESA_A, "novo@example.com", "Pedro")
    r = painel.post(f"/api/clientes/{contato['cliente_id']}/cpf", json={"cpf": CPF_VALIDO})
    assert r.status_code == 200
    r = painel.post(f"/api/clientes/{contato['cliente_id']}/cpf", json={"cpf": CPF_VALIDO})
    assert r.status_code == 400


# --------------------------------------------------------------------
# 4. De ponta a ponta: o e-mail de quem não é cliente agora é guardado
# --------------------------------------------------------------------

def test_email_de_desconhecido_e_guardado_em_vez_de_sumir(banco, monkeypatch):
    """O defeito original. A pergunta exige cadastro, então a resposta é
    o pedido de CPF -- sem OpenAI nenhuma no caminho."""
    from atendimento.processar import processar_mensagem
    from motor_ia import orquestrador

    monkeypatch.setattr(
        orquestrador, "classificar",
        lambda *a, **k: ResultadoClassificacao(
            intencao="CONSULTA_HABITUALIDADE", resumo="quer saber dos treinos",
            precisa_humano=False,
        ),
    )
    monkeypatch.setattr(
        orquestrador, "consultar",
        lambda *a, **k: pytest.fail("consultou dado de alguém sem CPF no cadastro"),
    )

    resultado = processar_mensagem(
        EMPRESA_A, texto="Quantos treinos eu tenho?", canal="Email",
        assunto="Treinos", remetente_email="novo@example.com", remetente_nome="Pedro Novo",
    )

    assert resultado["cliente_id"]
    assert resultado["mensagem_id"]
    assert "CPF" in resultado["resposta"]
    con = conectar_admin()
    msg = con.execute(
        "SELECT cliente_id, empresa_id FROM mensagem WHERE mensagem_id = ?",
        (resultado["mensagem_id"],),
    ).fetchone()
    cliente = con.execute(
        "SELECT cpf, email FROM cliente WHERE cliente_id = ?", (resultado["cliente_id"],)
    ).fetchone()
    con.close()
    assert msg["cliente_id"] == resultado["cliente_id"]
    assert msg["empresa_id"] == EMPRESA_A
    assert cliente["cpf"] is None
    assert cliente["email"] == "novo@example.com"


def test_sem_a_chave_o_orquestrador_nao_cria_cadastro(banco, monkeypatch):
    """Demonstração e testes chamam o orquestrador direto e não podem
    encher a lista de clientes."""
    from motor_ia import orquestrador

    monkeypatch.setattr(
        orquestrador, "classificar",
        lambda *a, **k: ResultadoClassificacao(
            intencao="CONSULTA_PROCESSO", resumo="x", precisa_humano=False,
        ),
    )
    antes = len(_clientes())
    resultado = orquestrador.atender_mensagem(
        EMPRESA_A, "Como está meu processo?", canal="Email", email="novo@example.com",
    )
    assert resultado["cliente_id"] is None
    assert len(_clientes()) == antes
