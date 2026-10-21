"""Coluna `processo.documento_final_id` (2026-10-20): o documento que o
processo produziu (o CRAF renovado, a guia emitida), entregue ao cliente
no Portal junto do "Concluído" -- ver
core/motor_processos.py::concluir_com_documento.

Idempotente, e roda sozinha na subida do servidor de produção
(webapp/servir.py), como migrar_codigo_portal.

    .venv\\Scripts\\python.exe -m core.db.migrar_documento_final
"""
from core.conexao import conectar_admin


def migrar() -> dict:
    con = conectar_admin()
    try:
        existentes = {c[1] for c in con.execute("PRAGMA table_info(processo)")}
        criada = "documento_final_id" not in existentes
        if criada:
            con.execute(
                "ALTER TABLE processo ADD COLUMN documento_final_id TEXT "
                "REFERENCES documento(documento_id)"
            )
        con.commit()
        return {"coluna_criada": criada}
    finally:
        con.close()


if __name__ == "__main__":
    print(migrar())
