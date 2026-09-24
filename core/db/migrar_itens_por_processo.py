"""Item de checklist que pertence a UM processo (2026-09-24).

Pedido do usuário: "Comprovante de capacidade técnica de arma de fogo pode
ter mais de 1 -- ele tem pistola, carabina, revólver." A lista de um
serviço é a mesma para todo processo; o item a mais é daquela pessoa só.

`documento_exigido.processo_id`:
    NULL  -> item do SERVIÇO (a ficha do clube), vale para todo processo
    valor -> item extra, só aparece no checklist deste processo

A view do Consultor (VW_CHECKLIST_SERVICO) passa a ignorar os extras:
"quais documentos para Renovação de CRAF?" responde com a ficha, não com
a carabina do cliente de ontem.

Idempotente, e roda SOZINHA na subida do servidor de produção
(webapp/servir.py): duas tabelas já chegaram atrasadas à produção porque
ninguém rodou a migração (configuracoes, template).

    .venv\\Scripts\\python.exe -m core.db.migrar_itens_por_processo
"""
from core.conexao import conectar_admin

VIEW_CHECKLIST = """
CREATE VIEW VW_CHECKLIST_SERVICO AS
SELECT
    de.servico_id,
    de.empresa_id,
    s.nome_servico,
    de.grupo,
    de.item,
    de.ordem
FROM documento_exigido de
JOIN servico s ON s.service_id = de.servico_id
WHERE de.ativo = 'Sim' AND s.ativo = 'Sim'
  AND de.processo_id IS NULL
  AND de.empresa_id = empresa_atual()
ORDER BY de.servico_id, de.ordem;
"""


def migrar() -> dict:
    con = conectar_admin()
    try:
        colunas = {c[1] for c in con.execute("PRAGMA table_info(documento_exigido)")}
        criou = "processo_id" not in colunas
        if criou:
            con.execute("ALTER TABLE documento_exigido ADD COLUMN processo_id TEXT")
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_documento_exigido_processo "
                "ON documento_exigido(processo_id)"
            )
        sql_view = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name='VW_CHECKLIST_SERVICO'"
        ).fetchone()
        refez_view = not sql_view or "processo_id IS NULL" not in (sql_view[0] or "")
        if refez_view:
            con.execute("DROP VIEW IF EXISTS VW_CHECKLIST_SERVICO")
            con.executescript(VIEW_CHECKLIST)
        con.commit()
        return {"coluna_criada": criou, "view_refeita": refez_view}
    finally:
        con.close()


if __name__ == "__main__":
    saida = migrar()
    print("Coluna documento_exigido.processo_id:", "criada" if saida["coluna_criada"] else "já existia")
    print("VW_CHECKLIST_SERVICO:", "refeita" if saida["view_refeita"] else "já estava certa")
