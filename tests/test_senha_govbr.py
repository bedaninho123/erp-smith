"""Senha do gov.br do cliente (2026-09-24).

É a chave da vida digital de uma pessoa. O que estes testes guardam:

- o valor puro NUNCA toca o banco;
- sem a chave de criptografia configurada, nada é guardado (falha
  fechado, nunca "texto puro por enquanto");
- a senha só sai por /revelar, e todo revelar fica na Auditoria;
- cliente de outra empresa não é alcançável;
- nenhum módulo da IA ou do Portal importa o motor.
"""
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from core.conexao import conectar_admin
from motor_ia.conexao import DOMAIN_DB
from tests.conftest import AGORA, EMPRESA_A

SENHA = "Minha$enhaGov123"
CPF_FILIADO = "52998224725"


@pytest.fixture
def com_chave(monkeypatch):
    monkeypatch.setenv("ERP_CHAVE_SENHAS", Fernet.generate_key().decode())


def _linhas_credencial():
    con = conectar_admin()
    try:
        return [dict(l) for l in con.execute("SELECT * FROM credencial_cliente")]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def test_sem_chave_nao_guarda_nada(banco, painel, monkeypatch):
    monkeypatch.delenv("ERP_CHAVE_SENHAS", raising=False)
    resposta = painel.post("/api/clientes/CLI-000001/senha-govbr", json={"senha": SENHA})
    assert resposta.status_code == 503
    assert _linhas_credencial() == []


def test_senha_fica_cifrada_no_banco(banco, painel, com_chave):
    assert painel.post("/api/clientes/CLI-000001/senha-govbr", json={"senha": SENHA}).status_code == 200
    linhas = _linhas_credencial()
    assert len(linhas) == 1
    assert SENHA not in str(linhas[0])


def test_situacao_nunca_traz_o_valor(banco, painel, com_chave):
    painel.post("/api/clientes/CLI-000001/senha-govbr", json={"senha": SENHA})
    resposta = painel.get("/api/clientes/CLI-000001/senha-govbr")
    assert resposta.get_json()["cadastrada"] is True
    assert SENHA not in resposta.get_data(as_text=True)


def test_revelar_devolve_e_deixa_rastro(banco, painel, com_chave):
    painel.post("/api/clientes/CLI-000001/senha-govbr", json={"senha": SENHA})
    resposta = painel.post("/api/clientes/CLI-000001/senha-govbr/revelar")

    assert resposta.get_json()["senha"] == SENHA
    assert resposta.headers["Cache-Control"] == "no-store"

    con = conectar_admin()
    eventos = con.execute(
        "SELECT tipo_evento, alvo, criado_por, descricao, valor_novo FROM log_administrativo "
        "WHERE tipo_evento LIKE 'SENHA_GOVBR_%' ORDER BY log_administrativo_id"
    ).fetchall()
    con.close()
    assert [e["tipo_evento"] for e in eventos] == ["SENHA_GOVBR_CADASTRADA", "SENHA_GOVBR_REVELADA"]
    assert eventos[1]["alvo"] == "CLI-000001"
    assert eventos[1]["criado_por"] == "Gestor Teste"
    # O valor nunca vai para o registro.
    assert all(SENHA not in str(dict(e)) for e in eventos)


def test_cliente_de_outra_empresa_nao_e_alcancavel(banco, painel, com_chave):
    """CLI-000003 é da EMPRESA_B."""
    assert painel.post("/api/clientes/CLI-000003/senha-govbr", json={"senha": SENHA}).status_code == 400
    assert _linhas_credencial() == []


def test_filiado_que_nao_e_cliente_ganha_cadastro_ao_guardar_senha(banco, painel, com_chave):
    con = sqlite3.connect(DOMAIN_DB)
    con.execute(
        "INSERT INTO filiado (filiado_id, empresa_id, nome, cpf, status_filiacao, criado_em, "
        "atualizado_em) VALUES ('FIL-000001', ?, 'Filiado Teste', ?, 'Ativo', ?, ?)",
        (EMPRESA_A, CPF_FILIADO, AGORA, AGORA),
    )
    con.commit()
    con.close()

    resposta = painel.post(f"/api/filiados/{CPF_FILIADO}/senha-govbr", json={"senha": SENHA})
    assert resposta.get_json()["cadastro_criado"] is True
    revelada = painel.post(f"/api/filiados/{CPF_FILIADO}/senha-govbr/revelar").get_json()
    assert revelada["senha"] == SENHA


def test_ia_e_portal_nao_importam_o_motor():
    """Leitura do código, não execução: a garantia é de AUSÊNCIA, e
    nenhum teste de comportamento prova que um import não existe."""
    raiz = Path(__file__).resolve().parents[1]
    for pasta in ("motor_ia", "portal", "atendimento"):
        for arquivo in (raiz / pasta).rglob("*.py"):
            assert "motor_credenciais" not in arquivo.read_text(encoding="utf-8"), arquivo
