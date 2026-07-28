"""Revisão interativa das perguntas/respostas da base de conhecimento
que ainda não foram aprovadas. Rode com `python -m
domain.clube_tiro.db.aprovar_conhecimento` e responda s/n/p (pular)
para cada uma -- só entradas aprovadas (aprovado='Sim') são usadas pelo
Consultor com clientes reais.

Sem empresa_id: conhecimento é compartilhado entre todas as empresas do
domínio (docs/schema_multi_tenant.md, 7.1). Aprovar uma entrada aqui
vale para todo mundo -- o que é justamente o ponto, já que a fonte é
legislação federal.
"""
import os
import sqlite3

DB_PATH = os.environ.get(
    "ERP_DOMAIN_DB", "domain/clube_tiro/db/dominio_clube_tiro.db"
)


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        pendentes = con.execute(
            "SELECT conhecimento_id, categoria, pergunta, resposta "
            "FROM conhecimento WHERE aprovado = 'Não' AND ativo = 'Sim'"
        ).fetchall()

        if not pendentes:
            print("Nenhuma entrada pendente de revisão.")
            return

        print(f"{len(pendentes)} entrada(s) pendente(s) de revisão.\n")
        for conhecimento_id, categoria, pergunta, resposta in pendentes:
            print(f"--- [{categoria}] {conhecimento_id} ---")
            print(f"Pergunta: {pergunta}")
            print(f"Resposta: {resposta}")
            resp = input("Aprovar? (s = sim / n = não usar / p = pular por agora): ").strip().lower()

            if resp == "s":
                con.execute(
                    "UPDATE conhecimento SET aprovado = 'Sim' WHERE conhecimento_id = ?",
                    (conhecimento_id,),
                )
                con.commit()
                print("Aprovado.\n")
            elif resp == "n":
                con.execute(
                    "UPDATE conhecimento SET ativo = 'Não' WHERE conhecimento_id = ?",
                    (conhecimento_id,),
                )
                con.commit()
                print("Desativado (não será usado nem aparecerá de novo aqui).\n")
            else:
                print("Deixado pendente.\n")
    finally:
        con.close()


if __name__ == "__main__":
    main()
