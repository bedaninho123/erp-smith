"""Preenche `caso.encerrado_em` nos casos que já estão encerrados.

A coluna existe no schema desde o Core mínimo e nunca foi escrita:
`atualizar_status()` mudava o status e pronto. O efeito prático só
apareceu quando o Dashboard precisou responder "quantos casos você
concluiu em agosto?" -- não havia data de encerramento em lugar nenhum.

A partir de 2026-08-27 o motor carimba a data ao encerrar. Este script
cuida do passado, e a data não é inventada: sai do `historico`, que
registra toda mudança de status desde sempre (`tipo_evento =
'mudanca_status'`, `valor_novo = 'Encerrado'`). Usa o registro MAIS
RECENTE de encerramento -- um caso reaberto e encerrado de novo tem dois,
e o que vale é o último.

Caso encerrado sem rastro no histórico (importado da planilha, por
exemplo) fica com `encerrado_em` NULL de propósito: "não sei quando"
nunca vira uma data plausível chutada de `atualizado_em`, senão o
gráfico de conclusões por mês ganharia um pico falso no dia da migração.
O script relata quantos ficaram assim.

Idempotente: só toca em linha com `encerrado_em` NULL, então rodar duas
vezes não muda nada. Roda sobre banco em uso.

    .venv\\Scripts\\python.exe -m core.db.migrar_encerrado_em
"""
from core.conexao import conectar_admin


def migrar() -> dict:
    con = conectar_admin()
    try:
        encerrados = con.execute(
            "SELECT caso_id FROM caso WHERE status = 'Encerrado' AND encerrado_em IS NULL"
        ).fetchall()

        preenchidos, sem_rastro = 0, []
        for linha in encerrados:
            caso_id = linha["caso_id"]
            evento = con.execute(
                "SELECT criado_em FROM historico WHERE caso_id = ? "
                "AND tipo_evento = 'mudanca_status' AND valor_novo = 'Encerrado' "
                "ORDER BY criado_em DESC LIMIT 1",
                (caso_id,),
            ).fetchone()
            if not evento:
                sem_rastro.append(caso_id)
                continue
            con.execute(
                "UPDATE caso SET encerrado_em = ? WHERE caso_id = ?",
                (evento["criado_em"], caso_id),
            )
            preenchidos += 1

        # Caso que NÃO está encerrado não pode carregar data de
        # encerramento -- se alguém reabriu antes desta mudança existir, a
        # data ficou pendurada lá e contaria como conclusão de novo.
        limpos = con.execute(
            "UPDATE caso SET encerrado_em = NULL "
            "WHERE status != 'Encerrado' AND encerrado_em IS NOT NULL"
        ).rowcount

        con.commit()
        return {
            "encerrados_sem_data": len(encerrados),
            "preenchidos": preenchidos,
            "sem_rastro": sem_rastro,
            "limpos": limpos,
        }
    finally:
        con.close()


if __name__ == "__main__":
    saida = migrar()
    print(f"Casos encerrados sem data: {saida['encerrados_sem_data']}")
    print(f"  Preenchidos a partir do histórico: {saida['preenchidos']}")
    print(f"  Sem rastro no histórico (ficaram NULL): {len(saida['sem_rastro'])}")
    for caso_id in saida["sem_rastro"]:
        print(f"    {caso_id}")
    print(f"Casos não-encerrados com data pendurada, limpos: {saida['limpos']}")
