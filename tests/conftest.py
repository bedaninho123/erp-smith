"""Infraestrutura compartilhada da suíte de testes.

Regra número um deste arquivo: **nenhum teste toca o banco real.** A
variável ERP_CORE_DB é definida logo abaixo, ANTES de qualquer import do
projeto, porque core/conexao.py lê o caminho do banco uma única vez na
importação (ver o comentário lá). Se este bloco descer para depois dos
imports, a suíte inteira passa a rodar contra core/db/erp_smith.db.

O banco de teste é recriado do zero a cada teste a partir do schema real
(core/db/schema.sql + views.sql) -- nunca de uma cópia desatualizada do
schema escrita à mão aqui, que sairia de sincronia sem ninguém perceber.
"""
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_PASTA_TEMP = Path(tempfile.mkdtemp(prefix="erp_smith_testes_"))

# --- precisa vir antes dos imports do projeto (ver docstring) ---
os.environ["ERP_CORE_DB"] = str(_PASTA_TEMP / "erp_smith_teste.db")
# Evita que portal/app.py e webapp/app.py gerem uma chave nova e a
# gravem no .env de verdade durante os testes.
os.environ.setdefault("PORTAL_SECRET_KEY", "chave-de-teste-portal")
os.environ.setdefault("WEBAPP_SECRET_KEY", "chave-de-teste-webapp")

import pytest  # noqa: E402

from core.conexao import CORE_DB  # noqa: E402

AGORA = "2026-07-28T12:00:00Z"


def _criar_schema(con: sqlite3.Connection) -> None:
    con.executescript((BASE_DIR / "core" / "db" / "schema.sql").read_text(encoding="utf-8"))
    con.executescript((BASE_DIR / "core" / "db" / "views.sql").read_text(encoding="utf-8"))


def _inserir_cliente(con: sqlite3.Connection, cliente_id: str, nome: str, cpf: str, email: str) -> None:
    con.execute(
        "INSERT INTO cliente (cliente_id, nome, cpf, email, telefone, cidade, status, "
        "atendimento_ia, data_cadastro) VALUES (?,?,?,?,?,?,?,?,?)",
        (cliente_id, nome, cpf, email, "14999990000", "Marília", "Ativo", "Sim", AGORA),
    )


def _inserir_caso(con: sqlite3.Connection, caso_id: str, cliente_id: str, titulo: str) -> None:
    con.execute(
        "INSERT INTO caso (caso_id, cliente_id, titulo, descricao, categoria, tipo_caso, "
        "origem, canal_origem, status, prioridade, criado_em, atualizado_em, criado_por, "
        "alterado_por, versao, ativo) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (caso_id, cliente_id, titulo, "Caso de teste", "Transferência", "Solicitação",
         "Atendimento", "Email", "Aberto", "Normal", AGORA, AGORA, "testes", "testes", 1, "Sim"),
    )


def _inserir_processo(con: sqlite3.Connection, processo_id: str, caso_id: str, cliente_id: str) -> None:
    con.execute(
        "INSERT INTO processo (processo_id, caso_id, cliente_id, servico_id, protocolo, "
        "status, data_abertura, ultima_atualizacao) VALUES (?,?,?,?,?,?,?,?)",
        (processo_id, caso_id, cliente_id, "SER-000001", f"PROTO-{processo_id}",
         "Em andamento", AGORA, AGORA),
    )


def _inserir_documento(
    con: sqlite3.Connection, documento_id: str, cliente_id: str, caso_id: str, caminho: Path
) -> None:
    con.execute(
        "INSERT INTO documento (documento_id, cliente_id, caso_id, tipo_documento, "
        "nome_arquivo, link_arquivo, status, data_envio) VALUES (?,?,?,?,?,?,?,?)",
        (documento_id, cliente_id, caso_id, "RG", f"{documento_id}.pdf",
         str(caminho), "Recebido", AGORA),
    )


@pytest.fixture(autouse=True)
def _pasta_de_documentos_isolada(tmp_path, monkeypatch):
    """Redireciona a pasta de anexos pro tmp do teste, sempre.

    autouse de propósito: descobrimos na prática que um teste de
    isolamento *falhando* (código quebrado deixando o upload passar)
    gravava arquivo de verdade em atendimento/documentos_recebidos/.
    Deixar isso na mão de cada teste lembrar não é garantia nenhuma.
    """
    from core import motor_documentos

    monkeypatch.setattr(motor_documentos, "PASTA_DOCUMENTOS", tmp_path / "documentos_recebidos")


@pytest.fixture
def banco(tmp_path):
    """Banco limpo com dois clientes que não têm nada em comum -- é essa
    separação que os testes de isolamento tentam furar.

    Cliente A: CLI-000001 / CAS-000001 / PRO-000001 / DOC-000001
    Cliente B: CLI-000002 / CAS-000002 / PRO-000002 / DOC-000002
    """
    caminho = Path(CORE_DB)
    caminho.unlink(missing_ok=True)

    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    _criar_schema(con)

    con.execute(
        "INSERT INTO servico (service_id, service_key, nome_servico, categoria, "
        "documentos_obrigatorios, ativo) VALUES (?,?,?,?,?,?)",
        ("SER-000001", "transferencia_arma", "Transferência de Arma", "Transferência",
         "RG, CPF, CR", "Sim"),
    )
    con.execute(
        "INSERT INTO usuario (usuario_id, nome, email, papel, ativo, criado_em) "
        "VALUES (?,?,?,?,?,?)",
        ("USR-000001", "Atendente Teste", "atendente@example.com", "Atendimento", "Sim", AGORA),
    )

    arquivo_a = tmp_path / "documento_do_cliente_a.pdf"
    arquivo_a.write_bytes(b"%PDF-1.4 conteudo secreto do cliente A")
    arquivo_b = tmp_path / "documento_do_cliente_b.pdf"
    arquivo_b.write_bytes(b"%PDF-1.4 conteudo secreto do cliente B")

    _inserir_cliente(con, "CLI-000001", "Ana Teste", "11111111111", "ana@example.com")
    _inserir_caso(con, "CAS-000001", "CLI-000001", "Caso da Ana")
    _inserir_processo(con, "PRO-000001", "CAS-000001", "CLI-000001")
    _inserir_documento(con, "DOC-000001", "CLI-000001", "CAS-000001", arquivo_a)

    _inserir_cliente(con, "CLI-000002", "Bruno Teste", "22222222222", "bruno@example.com")
    _inserir_caso(con, "CAS-000002", "CLI-000002", "Caso do Bruno")
    _inserir_processo(con, "PRO-000002", "CAS-000002", "CLI-000002")
    _inserir_documento(con, "DOC-000002", "CLI-000002", "CAS-000002", arquivo_b)

    con.commit()
    con.close()

    yield {"arquivo_a": arquivo_a, "arquivo_b": arquivo_b}

    Path(CORE_DB).unlink(missing_ok=True)


@pytest.fixture
def portal(banco):
    """Cliente HTTP do Portal já logado como Ana (CLI-000001).

    Logar direto na sessão (em vez de passar pelo link mágico) é
    proposital: o alvo destes testes é o isolamento das rotas, não o
    fluxo de login -- esse tem testes próprios em test_portal_auth.py.
    """
    from portal.app import app

    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    cliente_http = app.test_client()
    with cliente_http.session_transaction() as sessao:
        sessao["cliente_id"] = "CLI-000001"
        sessao["cliente_nome"] = "Ana Teste"
    return cliente_http


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_PASTA_TEMP, ignore_errors=True)
