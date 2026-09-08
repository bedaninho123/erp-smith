"""Acrescenta `documento.finalidade` no banco que já está em uso -- sem
recriar nada.

Guarda a que acervo a arma do documento pertence -- 'Tiro' / 'Caça' /
'Coleção' -- ao lado de `observacoes` (o "de qual arma", ver
core/motor_documentos.py::salvar_no_dossie). É vocabulário de CAC, então
mora como SELECT na tela e a lista de valores vive no Domínio
(domain/clube_tiro/documentos_cac.py) -- o Core só guarda o texto, sem
CHECK, mesmo padrão de tipo_documento e categoria.

Coluna nasce NULL para todo documento existente: não há como inferir a
finalidade de um documento já guardado sem reabrir o arquivo, e chutar
'Tiro' por ser o mais comum inventaria um fato que ninguém conferiu.

Idempotente -- rodar de novo não faz nada. Usa conectar_admin() porque
mexe na estrutura do banco, que é de todas as empresas ao mesmo tempo
(CLAUDE.md: admin só em script de setup).

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_finalidade_documento`
"""
from core.conexao import conectar_admin


def main() -> None:
    con = conectar_admin()
    try:
        existentes = {
            linha[1] for linha in con.execute("PRAGMA table_info(documento)")
        }
        if not existentes:
            raise SystemExit("Tabela documento não existe -- rode core.db.criar_banco antes.")

        if "finalidade" in existentes:
            print("Nada a fazer: a coluna finalidade já existe.")
            return

        con.execute("ALTER TABLE documento ADD COLUMN finalidade TEXT")
        con.commit()

        total = con.execute("SELECT COUNT(*) FROM documento").fetchone()[0]
        print(f"Coluna finalidade criada. {total} documento(s) existente(s) ficaram com finalidade NULL.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
