"""Identifica um cliente a partir de nome, CPF ou e-mail -- o passo
'Identificar cliente' que, no fluxo real (PROJETO_1.md, seção 6), acontece
antes da classificação da mensagem. Prioridade de busca: CPF > e-mail >
nome, do identificador mais confiável pro menos confiável (nome não é
único; CPF e e-mail são).
"""
import re
import sqlite3
from typing import Optional

from motor_ia.conexao import CORE_DB


def _limpar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf)


def identificar_cliente(
    nome: Optional[str] = None,
    cpf: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[dict]:
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    try:
        if cpf:
            linha = con.execute(
                "SELECT * FROM cliente WHERE cpf = ?", (_limpar_cpf(cpf),)
            ).fetchone()
            if linha:
                return dict(linha)

        if email:
            linha = con.execute(
                "SELECT * FROM cliente WHERE LOWER(email) = LOWER(?)", (email,)
            ).fetchone()
            if linha:
                return dict(linha)

        if nome:
            linha = con.execute(
                "SELECT * FROM cliente WHERE LOWER(nome) = LOWER(?)", (nome,)
            ).fetchone()
            if linha:
                return dict(linha)
            # Não achou exato -- tenta por aproximação (nome contém o texto).
            linha = con.execute(
                "SELECT * FROM cliente WHERE LOWER(nome) LIKE LOWER(?)",
                (f"%{nome}%",),
            ).fetchone()
            if linha:
                return dict(linha)

        return None
    finally:
        con.close()


if __name__ == "__main__":
    testes = [
        {"cpf": "123.456.789-00"},
        {"email": "joao.teste@example.com"},
        {"nome": "Maria Oliveira"},
        {"nome": "Oliveira"},
        {"cpf": "000.000.000-00"},
    ]
    for entrada in testes:
        resultado = identificar_cliente(**entrada)
        achado = f"{resultado['cliente_id']} - {resultado['nome']}" if resultado else "não encontrado"
        print(f"{entrada} -> {achado}")
