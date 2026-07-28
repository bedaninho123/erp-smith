"""Identifica um cliente a partir de nome, CPF ou e-mail -- o passo
'Identificar cliente' que, no fluxo real (PROJETO_1.md, seção 6), acontece
antes da classificação da mensagem. Prioridade de busca: CPF > e-mail >
nome, do identificador mais confiável pro menos confiável (nome não é
único; CPF e e-mail são).
"""
import re
from typing import Optional

from motor_ia.conexao import conectar


def _limpar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf)


def identificar_cliente(
    empresa_id: str,
    nome: Optional[str] = None,
    cpf: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[dict]:
    """A busca é sempre DENTRO de uma empresa.

    Este é um dos pontos mais sensíveis do multi-tenant: o poller entrega
    aqui o e-mail de quem escreveu, e sem o filtro por empresa um
    remetente que é cliente de outro despachante seria identificado como
    cliente desta -- e receberia de volta o dado dele. A busca por nome
    (aproximada, com LIKE) é a mais arriscada das três, justamente por
    não ser exata."""
    con = conectar(empresa_id)
    try:
        if cpf:
            linha = con.execute(
                "SELECT * FROM cliente WHERE empresa_id = ? AND cpf = ?",
                (empresa_id, _limpar_cpf(cpf)),
            ).fetchone()
            if linha:
                return dict(linha)

        if email:
            linha = con.execute(
                "SELECT * FROM cliente WHERE empresa_id = ? AND LOWER(email) = LOWER(?)",
                (empresa_id, email),
            ).fetchone()
            if linha:
                return dict(linha)

        if nome:
            linha = con.execute(
                "SELECT * FROM cliente WHERE empresa_id = ? AND LOWER(nome) = LOWER(?)",
                (empresa_id, nome),
            ).fetchone()
            if linha:
                return dict(linha)
            # Não achou exato -- tenta por aproximação (nome contém o texto).
            linha = con.execute(
                "SELECT * FROM cliente WHERE empresa_id = ? AND LOWER(nome) LIKE LOWER(?)",
                (empresa_id, f"%{nome}%"),
            ).fetchone()
            if linha:
                return dict(linha)

        return None
    finally:
        con.close()


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    testes = [
        {"cpf": "123.456.789-00"},
        {"email": "joao.teste@example.com"},
        {"nome": "Maria Oliveira"},
        {"nome": "Oliveira"},
        {"cpf": "000.000.000-00"},
    ]
    for entrada in testes:
        resultado = identificar_cliente(EMPRESA, **entrada)
        achado = f"{resultado['cliente_id']} - {resultado['nome']}" if resultado else "não encontrado"
        print(f"{entrada} -> {achado}")
