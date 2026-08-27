"""A migração que permitiu documento pertencer ao CLIENTE, e não a um caso.

Migração que reconstrói tabela é a operação mais perigosa deste projeto:
ela COPIA e APAGA. Um erro aqui não dá erro na tela -- some com arquivo
de cliente. Por isso o teste monta a tabela no formato ANTIGO, põe dado
dentro e confere que sobreviveu.

A primeira versão do script tinha um bug exatamente desse tipo:
`executescript()` faz COMMIT implícito, então a transação era encerrada
antes da cópia e o resto rodava solto -- sem nada para desfazer se
falhasse no meio.
"""
import sqlite3

import pytest

from core.conexao import CORE_DB, conectar_admin
from core.db.migrar_dossie_cliente import migrar
from tests.conftest import EMPRESA_A

DOCUMENTO_ANTIGO = """
DROP TABLE documento;
CREATE TABLE documento (
    documento_id      TEXT PRIMARY KEY,
    empresa_id        TEXT NOT NULL REFERENCES empresa(empresa_id),
    cliente_id        TEXT NOT NULL REFERENCES cliente(cliente_id),
    caso_id           TEXT REFERENCES caso(caso_id),
    processo_id       TEXT REFERENCES processo(processo_id),
    tipo_documento    TEXT NOT NULL,
    nome_arquivo      TEXT,
    link_arquivo      TEXT,
    status            TEXT NOT NULL,
    data_envio        TEXT,
    data_validade     TEXT,
    revisado_por_id   TEXT REFERENCES usuario(usuario_id),
    observacoes       TEXT,
    mensagem_id       TEXT REFERENCES mensagem(mensagem_id),
    CHECK (caso_id IS NOT NULL OR processo_id IS NOT NULL)
);
"""


@pytest.fixture
def banco_antigo(banco):
    """Reverte `documento` ao formato de antes da migração, com dado."""
    con = sqlite3.connect(CORE_DB)
    con.execute("PRAGMA foreign_keys = OFF")
    con.executescript(DOCUMENTO_ANTIGO)
    con.executemany(
        "INSERT INTO documento (documento_id, empresa_id, cliente_id, caso_id, "
        "tipo_documento, nome_arquivo, link_arquivo, status, data_envio, observacoes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("DOC-900001", EMPRESA_A, "CLI-000001", "CAS-000001", "RG",
             "rg.pdf", "/tmp/rg.pdf", "Recebido", "2026-07-01T10:00:00Z", "veio por e-mail"),
            ("DOC-900002", EMPRESA_A, "CLI-000002", "CAS-000002", "Comprovante",
             "comp.jpg", "/tmp/comp.jpg", "Recebido", "2026-07-02T10:00:00Z", None),
        ],
    )
    con.commit()
    con.close()
    return banco


def test_migracao_preserva_todo_documento_existente(banco_antigo):
    saida = migrar()

    assert saida["migrada"] is True
    assert saida["antes"] == 2
    assert saida["documentos"] == 2

    con = conectar_admin()
    linhas = {l["documento_id"]: dict(l) for l in con.execute("SELECT * FROM documento")}
    con.close()

    assert set(linhas) == {"DOC-900001", "DOC-900002"}
    # Campo a campo: uma cópia que perde coluna some com informação sem
    # dar erro nenhum.
    primeiro = linhas["DOC-900001"]
    assert primeiro["cliente_id"] == "CLI-000001"
    assert primeiro["caso_id"] == "CAS-000001"
    assert primeiro["tipo_documento"] == "RG"
    assert primeiro["nome_arquivo"] == "rg.pdf"
    assert primeiro["link_arquivo"] == "/tmp/rg.pdf"
    assert primeiro["data_envio"] == "2026-07-01T10:00:00Z"
    assert primeiro["observacoes"] == "veio por e-mail"
    # Todo documento que já existia é de atendimento, por definição.
    assert primeiro["categoria"] == "Caso"


def test_migracao_e_idempotente(banco_antigo):
    migrar()
    segunda = migrar()

    assert segunda["migrada"] is False
    assert segunda["documentos"] == 2


def test_depois_da_migracao_o_dossie_dispensa_caso(banco_antigo):
    migrar()

    con = conectar_admin()
    con.execute(
        "INSERT INTO documento (documento_id, empresa_id, cliente_id, tipo_documento, "
        "status, categoria) VALUES ('DOC-900003', ?, 'CLI-000001', 'CR', 'Recebido', 'Dossiê')",
        (EMPRESA_A,),
    )
    con.commit()
    guardado = con.execute(
        "SELECT caso_id, categoria FROM documento WHERE documento_id = 'DOC-900003'"
    ).fetchone()
    con.close()

    assert guardado["caso_id"] is None
    assert guardado["categoria"] == "Dossiê"


def test_documento_de_caso_continua_exigindo_caso(banco_antigo):
    """A garantia velha não pode ter sido afrouxada junto: documento de
    atendimento solto continua sendo recusado pelo banco."""
    migrar()

    con = conectar_admin()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO documento (documento_id, empresa_id, cliente_id, tipo_documento, "
            "status, categoria) VALUES ('DOC-900004', ?, 'CLI-000001', 'RG', 'Recebido', 'Caso')",
            (EMPRESA_A,),
        )
    con.close()


def test_dossie_com_caso_preenchido_e_recusado(banco_antigo):
    """A outra ponta da mesma regra: dossiê é da pessoa, não de um caso.
    Sem isto haveria zona cinzenta -- documento que é as duas coisas."""
    migrar()

    con = conectar_admin()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO documento (documento_id, empresa_id, cliente_id, caso_id, "
            "tipo_documento, status, categoria) VALUES ('DOC-900005', ?, 'CLI-000001', "
            "'CAS-000001', 'CR', 'Recebido', 'Dossiê')",
            (EMPRESA_A,),
        )
    con.close()
