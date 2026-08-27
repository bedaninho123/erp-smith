"""Cria as colunas de vínculo e situação financeira em `filiado`.

Descoberta de 2026-08-27: `GET /registers/shooters/paginate` -- a mesma
chamada que já espelha a lista de filiados -- devolve, de graça, a
situação de anuidade, a situação financeira, a validade do CR, se há
comanda em aberto e a **data real de filiação**. Nada disso estava sendo
lido: o mapeamento pegava só nome, CPF, e-mail, matrícula e status.

O ganho não é só de campo. A situação financeira do clube inteiro passa a
sair em ~40 chamadas paginadas, e não numa consulta por CPF como a
habitualidade -- por isso o Financeiro pode ser sincronizado várias vezes
ao dia sem pesar na API do fornecedor.

`data_filiacao` conserta de vez a ressalva do gráfico de novos filiados:
até aqui o sistema só sabia quando NÓS vimos a pessoa pela primeira vez.

As colunas nascem NULL e se preenchem na próxima sincronização da lista,
que é rápida (a lista inteira, sem habitualidade):

    .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_habitualidade --somente-lista

Idempotente: confere cada coluna antes de criar.

    .venv\\Scripts\\python.exe -m domain.clube_tiro.db.migrar_financeiro_filiado
"""
from domain.clube_tiro.motor_filiados import conectar

COLUNAS = (
    ("data_filiacao", "TEXT"),
    ("tipo_filiado", "TEXT"),
    ("anuidade_em_dia", "TEXT"),
    ("anuidade_validade", "TEXT"),
    ("financeiro_em_dia", "TEXT"),
    ("cr_numero", "TEXT"),
    ("cr_validade", "TEXT"),
    ("cr_em_dia", "TEXT"),
    ("tem_pedido_aberto", "TEXT"),
)


def migrar() -> dict:
    con = conectar()
    try:
        existentes = {c[1] for c in con.execute("PRAGMA table_info(filiado)")}
        criadas = []
        for nome, tipo in COLUNAS:
            if nome in existentes:
                continue
            con.execute(f"ALTER TABLE filiado ADD COLUMN {nome} {tipo}")
            criadas.append(nome)
        con.commit()
        total = con.execute("SELECT COUNT(*) FROM filiado").fetchone()[0]
        return {"criadas": criadas, "ja_existiam": len(COLUNAS) - len(criadas), "filiados": total}
    finally:
        con.close()


if __name__ == "__main__":
    saida = migrar()
    if not saida["criadas"]:
        print("Todas as colunas já existiam -- nada a fazer.")
    else:
        print(f"Colunas criadas: {', '.join(saida['criadas'])}")
        print(f"Filiados no banco: {saida['filiados']} (todos com as colunas em NULL por enquanto)")
    print()
    print("Para preencher, rode a sincronização da lista (rápida, não consulta habitualidade):")
    print("  .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_habitualidade --somente-lista")
