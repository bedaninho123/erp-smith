"""Permite cliente SEM CPF: o contato que chegou por e-mail e ainda não
informou o documento.

O problema (2026-10-07, ao trocar a caixa do atendimento por uma nova):
`cliente.cpf` nasceu NOT NULL, e `mensagem`, `conversa`, `sessao` e
`caso` exigem um `cliente_id`. Então e-mail de quem ainda não era cliente
era lido, a IA até escrevia a resposta -- e nada era guardado: não
aparecia em Aprovações nem em Atendimentos, e a resposta era descartada.
Com a caixa começando do zero, isso seria quase todo e-mail.

Agora o remetente desconhecido vira um cadastro com e-mail e nome, e CPF
vazio até alguém da equipe completar (ver
core/motor_clientes.py::obter_ou_criar_contato_por_email). O
`UNIQUE (empresa_id, cpf)` continua valendo: no SQLite, NULL não colide
com NULL, então vários contatos sem CPF convivem.

POR QUE RECONSTRUIR A TABELA: o SQLite não sabe tirar um NOT NULL. Mesmo
caminho de core/db/migrar_dossie_cliente.py -- tabela nova, copiar,
apagar a velha, renomear -- com dois cuidados a mais:

- A tabela nova é feita a partir do SQL ATUAL de `cliente` (lido do
  próprio banco), trocando só o `cpf TEXT NOT NULL`. Assim nenhuma coluna
  acrescentada por migração depois do schema.sql se perde na cópia.
- As views que leem `cliente` (VW_CLIENTE, VW_PROCESSO) são guardadas,
  apagadas e recriadas iguais: o RENAME do SQLite recusa a troca se
  existir view apontando para uma tabela que, naquele instante, não
  existe.

Idempotente: se `cpf` já aceita vazio, não faz nada.

    .venv\\Scripts\\python.exe -m core.db.migrar_cliente_sem_cpf
"""
import re

from core.conexao import conectar_admin

_CPF_OBRIGATORIO = re.compile(r"\bcpf(\s+)TEXT\s+NOT\s+NULL", re.IGNORECASE)


def _cpf_ja_opcional(con) -> bool:
    for coluna in con.execute("PRAGMA table_info(cliente)"):
        if coluna[1] == "cpf":
            return coluna[3] == 0  # notnull
    raise RuntimeError("Tabela cliente sem coluna cpf -- banco inesperado.")


def migrar() -> dict:
    con = conectar_admin()
    try:
        if _cpf_ja_opcional(con):
            total = con.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
            return {"migrada": False, "clientes": total}

        sql_atual = con.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cliente'"
        ).fetchone()[0]
        sql_novo, trocas = _CPF_OBRIGATORIO.subn(r"cpf\1TEXT", sql_atual)
        if trocas != 1:
            return {"migrada": False, "erro": f"esperava 1 'cpf TEXT NOT NULL', achei {trocas}"}
        sql_novo = re.sub(
            r"^\s*CREATE\s+TABLE\s+\"?cliente\"?", "CREATE TABLE cliente_nova", sql_novo,
            count=1, flags=re.IGNORECASE,
        )

        # Índices criados à mão (os automáticos do UNIQUE/PK vêm junto com
        # a tabela) e views que dependem dela -- recriados depois, iguais.
        indices = [
            linha[0] for linha in con.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = 'cliente' AND sql IS NOT NULL"
            )
        ]
        views = con.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'view' "
            "AND sql LIKE '%cliente%'"
        ).fetchall()

        colunas = [c[1] for c in con.execute("PRAGMA table_info(cliente)")]
        lista = ", ".join(colunas)
        antes = con.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]

        con.isolation_level = None
        # Desligado só durante a troca: com ele ligado, as FKs de caso,
        # mensagem, conversa etc. impediriam apagar a tabela antiga.
        con.execute("PRAGMA foreign_keys = OFF")
        con.execute("BEGIN")
        try:
            # execute(), nunca executescript() -- ver migrar_dossie_cliente.
            for nome, _ in views:
                con.execute(f'DROP VIEW "{nome}"')
            con.execute(sql_novo)
            con.execute(f"INSERT INTO cliente_nova ({lista}) SELECT {lista} FROM cliente")
            con.execute("DROP TABLE cliente")
            con.execute("ALTER TABLE cliente_nova RENAME TO cliente")
            for sql in indices:
                con.execute(sql)
            for _, sql in views:
                con.execute(sql)

            depois = con.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
            quebradas = con.execute("PRAGMA foreign_key_check").fetchall()
            if quebradas or depois != antes:
                con.execute("ROLLBACK")
                return {
                    "migrada": False,
                    "erro": f"{len(quebradas)} referência(s) quebrada(s), "
                            f"clientes {antes} -> {depois}",
                }
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.execute("PRAGMA foreign_keys = ON")

        return {"migrada": True, "clientes": depois, "antes": antes}
    finally:
        con.close()


if __name__ == "__main__":
    saida = migrar()
    if saida.get("erro"):
        print(f"FALHOU: {saida['erro']}. Nada foi alterado.")
        raise SystemExit(1)
    if not saida["migrada"]:
        print(f"cliente.cpf já aceita vazio -- nada a fazer. "
              f"({saida['clientes']} cliente(s) na tabela.)")
    else:
        print("Tabela cliente reconstruída: CPF passou a ser opcional.")
        print(f"  Clientes preservados: {saida['antes']} -> {saida['clientes']}")
