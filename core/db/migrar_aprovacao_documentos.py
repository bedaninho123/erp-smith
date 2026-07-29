"""Acrescenta o estado de aprovação em documento_checklist, no banco que
já está em uso -- sem recriar nada.

Até aqui, um documento ligado a um item do checklist era, por definição,
um documento conferido: só um funcionário conseguia criar essa ligação,
pelo painel. Agora o cliente também cria, enviando o arquivo pelo Portal
e dizendo a que item ele corresponde -- e nesse caso ninguém da equipe
olhou ainda. Daí as quatro colunas novas.

Por que as linhas antigas viram 'Aprovado': todas foram criadas por um
funcionário no painel, o que já era a aprovação. Marcar como pendente
agora inventaria uma fila de trabalho que nunca existiu.

Idempotente -- rodar de novo não faz nada. Usa conectar_admin() porque
mexe na estrutura do banco, que é de todas as empresas ao mesmo tempo
(CLAUDE.md: admin só em script de setup).

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_aprovacao_documentos`
"""
from core.conexao import conectar_admin

COLUNAS = {
    "status": (
        "TEXT NOT NULL DEFAULT 'Aprovado' "
        "CHECK (status IN ('Aguardando aprovação', 'Aprovado', 'Recusado'))"
    ),
    "revisado_em": "TEXT",
    "revisado_por": "TEXT",
    "motivo_recusa": "TEXT",
}


def main() -> None:
    con = conectar_admin()
    try:
        existentes = {
            linha[1] for linha in con.execute("PRAGMA table_info(documento_checklist)")
        }
        if not existentes:
            raise SystemExit(
                "Tabela documento_checklist não existe -- rode core.db.criar_banco antes."
            )

        novas = [nome for nome in COLUNAS if nome not in existentes]
        if not novas:
            print("Nada a fazer: as 4 colunas já existem.")
            return

        for nome in novas:
            con.execute(
                f"ALTER TABLE documento_checklist ADD COLUMN {nome} {COLUNAS[nome]}"
            )
            print(f"  + coluna {nome}")
        con.commit()

        total = con.execute("SELECT COUNT(*) FROM documento_checklist").fetchone()[0]
        print(f"\nPronto. {total} marcação(ões) existente(s) ficaram como 'Aprovado'.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
