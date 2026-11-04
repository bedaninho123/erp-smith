"""Configuração que pausa o envio de códigos do Portal (2026-11-04), ver
core/motor_portal_auth.py::envio_codigos_pausado.

Nasce LIGADA na empresa do Portal, porque entrou no ar durante o bloqueio do
Gmail de 04/11. Só cria a linha que falta: depois de o Gestor desligar pela
tela de Configurações, subir de novo não religa. Idempotente, e roda sozinha
na subida do servidor de produção (webapp/servir.py).

    .venv\\Scripts\\python.exe -m core.db.migrar_pausa_envio_portal
"""
import os

from core.conexao import conectar_admin
from core.motor_portal_auth import CHAVE_PAUSA_ENVIO

DESCRICAO = (
    "Ligado, o Portal para de enviar códigos por e-mail e mostra um aviso na tela "
    "de login. Desligue quando o envio de e-mail voltar ao normal."
)


def migrar() -> dict:
    empresa_portal = os.environ.get("PORTAL_EMPRESA_ID", "EMP-000001")
    con = conectar_admin()
    try:
        criadas = 0
        for (empresa_id,) in con.execute("SELECT empresa_id FROM empresa").fetchall():
            existe = con.execute(
                "SELECT 1 FROM configuracoes WHERE empresa_id = ? AND chave = ?",
                (empresa_id, CHAVE_PAUSA_ENVIO),
            ).fetchone()
            if existe:
                continue
            maior = con.execute(
                "SELECT MAX(CAST(SUBSTR(config_id, 5) AS INTEGER)) FROM configuracoes"
            ).fetchone()[0] or 0
            con.execute(
                "INSERT INTO configuracoes (config_id, empresa_id, chave, valor, categoria, "
                "descricao, ativo) VALUES (?,?,?,?,?,?,?)",
                (f"CFG-{maior + 1:06d}", empresa_id, CHAVE_PAUSA_ENVIO,
                 "Sim" if empresa_id == empresa_portal else "Não", "portal", DESCRICAO, "Sim"),
            )
            criadas += 1
        con.commit()
        return {"linhas_criadas": criadas}
    finally:
        con.close()


if __name__ == "__main__":
    print(migrar())
