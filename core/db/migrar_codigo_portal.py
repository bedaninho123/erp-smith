"""Código de 6 dígitos no login do Portal (2026-10-14).

O app instalado no iPhone vive separado do Safari: o link mágico do
e-mail abre no Safari, a pessoa entra LÁ, e o app continua deslogado.
O e-mail passou a levar também um código, digitado dentro do app. As três
colunas novas ficam na mesma linha de `portal_token` -- link e código são
duas portas do mesmo acesso, e usar uma fecha a outra.

Idempotente, e roda sozinha na subida do servidor de produção
(webapp/servir.py), como migrar_itens_por_processo.

    .venv\\Scripts\\python.exe -m core.db.migrar_codigo_portal
"""
from core.conexao import conectar_admin

COLUNAS = {
    "codigo_hash": "TEXT",
    "desafio": "TEXT",
    "tentativas_codigo": "INTEGER NOT NULL DEFAULT 0",
}


def migrar() -> dict:
    con = conectar_admin()
    try:
        existentes = {c[1] for c in con.execute("PRAGMA table_info(portal_token)")}
        criadas = []
        for nome, tipo in COLUNAS.items():
            if nome not in existentes:
                con.execute(f"ALTER TABLE portal_token ADD COLUMN {nome} {tipo}")
                criadas.append(nome)
        con.execute(
            "CREATE INDEX IF NOT EXISTS idx_portal_token_desafio ON portal_token(desafio)"
        )
        con.commit()
        return {"colunas_criadas": criadas}
    finally:
        con.close()


if __name__ == "__main__":
    print(migrar())
