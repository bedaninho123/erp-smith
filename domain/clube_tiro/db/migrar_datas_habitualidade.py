"""Cria a coluna `filiado.participacoes_datas` num banco de Domínio já em
uso.

Ela é o que faz o gráfico de participações por dia existir: até agora a
linha do filiado guardava só QUANTAS participações (`participacoes_12m`) e
a data da ÚLTIMA -- com isso não dá para desenhar dia nenhum.

A coluna nasce NULL para todo mundo, e isso é o certo: NULL significa
"ainda não sei as datas dessa pessoa", que é a verdade até ela passar
pelo rodízio de sincronização de novo. Preencher com `[]` diria
"consultei e ela não treinou", e aí o gráfico começaria a vida inteiro
zerado, parecendo um clube vazio.

A série se preenche sozinha conforme o rodízio roda (4x ao dia, ~150
pessoas por rodada -- o clube inteiro em pouco mais de um dia). O
Dashboard mostra a cobertura ao lado do gráfico justamente para esse
período de encher não ser lido como queda de movimento.

Idempotente: confere se a coluna já existe antes de criar.

    .venv\\Scripts\\python.exe -m domain.clube_tiro.db.migrar_datas_habitualidade
"""
from domain.clube_tiro.motor_filiados import conectar


def migrar() -> dict:
    con = conectar()
    try:
        colunas = [c[1] for c in con.execute("PRAGMA table_info(filiado)")]
        if "participacoes_datas" in colunas:
            return {"criada": False, "filiados": 0, "com_datas": 0}

        con.execute("ALTER TABLE filiado ADD COLUMN participacoes_datas TEXT")
        con.commit()

        total = con.execute("SELECT COUNT(*) FROM filiado").fetchone()[0]
        com_retrato = con.execute(
            "SELECT COUNT(*) FROM filiado WHERE participacoes_12m IS NOT NULL"
        ).fetchone()[0]
        return {"criada": True, "filiados": total, "com_datas": com_retrato}
    finally:
        con.close()


if __name__ == "__main__":
    saida = migrar()
    if not saida["criada"]:
        print("Coluna participacoes_datas já existe -- nada a fazer.")
    else:
        print("Coluna participacoes_datas criada.")
        print(f"  Filiados no banco: {saida['filiados']}")
        print(f"  Com retrato de contagem (mas ainda sem datas): {saida['com_datas']}")
        print()
        print("As datas entram na próxima sincronização de cada pessoa.")
        print("Para adiantar o clube inteiro de uma vez:")
        print("  .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_habitualidade --limite 1000")
