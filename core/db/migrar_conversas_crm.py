"""Liga as mensagens já existentes a conversas -- migração idempotente,
feita para rodar sobre o banco em uso, sem recriar nada.

Por que é preciso: `core/motor_mensagens.py` grava em `mensagem` desde
que o modo de revisão humana foi construído (2026-07-23), mas nunca
preencheu `conversa_id` -- a tabela `conversa` existia desde o Core
mínimo e só tinha linha de migração de teste. Resultado: todo histórico
acumulado até agora está solto, sem envelope, e a tela de Atendimentos
(CRM) não teria o que mostrar dele.

Como agrupa: uma conversa por (cliente, canal). Não tenta reconstruir
"fios" separados dentro do mesmo canal por proximidade de data -- seria
adivinhação sobre dado velho, e o custo de errar (juntar dois assuntos
que não tinham relação) é maior que o de deixar tudo num fio só. Daqui
pra frente, `motor_conversas.localizar_ou_criar_conversa` decide isso na
hora, com a informação certa.

    .venv\\Scripts\\python.exe -m core.db.migrar_conversas_crm
"""
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

CORE_DB = Path(__file__).resolve().parent / "erp_smith.db"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_numero(con) -> int:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(conversa_id, 5) AS INTEGER)) FROM conversa"
    ).fetchone()[0] or 0
    return maior + 1


# Rótulos de canal herdados da planilha/Make que não são canal de
# atendimento de verdade -- "Webhook" era como o cenário do Make
# chamava "e-mail que entrou por webhook", ou seja, o MEIO de chegada,
# não por onde o cliente falou. Como o catálogo novo
# (motor_conversas.CANAIS_VALIDOS) só conhece Email e WhatsApp, uma
# linha assim ficaria invisível no filtro por canal da tela.
_CANAIS_LEGADOS = {"Webhook": "Email", "webhook": "Email", "E-mail": "Email"}


def _normalizar_canais(con) -> list[tuple[str, str, int]]:
    """Converte rótulo de canal legado para o do catálogo atual.

    Devolve o que mudou em vez de só fazer -- reescrever dado histórico
    em silêncio é justamente o que não se faz neste projeto; quem roda a
    migração precisa ver na tela qual linha foi tocada e por quê.
    """
    mudancas: list[tuple[str, str, int]] = []
    for antigo, novo in _CANAIS_LEGADOS.items():
        for tabela in ("conversa", "mensagem", "sessao"):
            afetadas = con.execute(
                f"UPDATE {tabela} SET canal = ? WHERE canal = ?", (novo, antigo)
            ).rowcount
            if afetadas:
                mudancas.append((f"{tabela}.{antigo}", novo, afetadas))
    return mudancas


def migrar() -> dict:
    con = sqlite3.connect(CORE_DB)
    con.row_factory = sqlite3.Row
    # Mesma dupla de PRAGMAs de core/conexao.py -- este script pode rodar
    # com o painel e o poller de pé, e sem busy_timeout um "database is
    # locked" aqui abortaria a migração pela metade.
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")

    try:
        canais_normalizados = _normalizar_canais(con)

        orfas = con.execute(
            "SELECT empresa_id, cliente_id, canal, "
            "MIN(data_hora) AS primeira, MAX(data_hora) AS ultima, "
            "COUNT(*) AS total, MIN(caso_id) AS caso_id "
            "FROM mensagem WHERE conversa_id IS NULL "
            "GROUP BY empresa_id, cliente_id, canal "
            "ORDER BY empresa_id, cliente_id, canal"
        ).fetchall()

        if not orfas:
            con.commit()  # a normalização de canal pode ter mudado algo
            return {
                "conversas_criadas": 0, "mensagens_ligadas": 0, "ja_ok": True,
                "canais_normalizados": canais_normalizados,
            }

        proximo = _proximo_numero(con)
        criadas = ligadas = 0

        for grupo in orfas:
            empresa_id = grupo["empresa_id"]
            cliente_id = grupo["cliente_id"]
            canal = grupo["canal"] or "Email"

            # Reaproveita uma conversa aberta que já exista para esse
            # par (pode ter sido criada pelo pipeline novo antes desta
            # migração rodar) em vez de criar uma segunda em paralelo.
            existente = con.execute(
                "SELECT conversa_id FROM conversa WHERE empresa_id = ? AND cliente_id = ? "
                "AND canal = ? AND ativo = 'Sim' ORDER BY ultima_mensagem_em DESC LIMIT 1",
                (empresa_id, cliente_id, canal),
            ).fetchone()

            if existente:
                conversa_id = existente["conversa_id"]
            else:
                conversa_id = f"CON-{proximo:06d}"
                proximo += 1
                # O assunto da conversa vem do assunto da primeira
                # mensagem dela, quando existe (e-mail tem, WhatsApp não).
                assunto = con.execute(
                    "SELECT assunto FROM mensagem WHERE empresa_id = ? AND cliente_id = ? "
                    "AND canal = ? AND conversa_id IS NULL AND assunto IS NOT NULL "
                    "ORDER BY data_hora LIMIT 1",
                    (empresa_id, cliente_id, canal),
                ).fetchone()
                con.execute(
                    "INSERT INTO conversa (conversa_id, empresa_id, cliente_id, caso_id, "
                    "canal, origem, status, assunto_principal, iniciada_em, "
                    "ultima_mensagem_em, total_mensagens, criado_por, atualizado_por, "
                    "observacoes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        conversa_id, empresa_id, cliente_id, grupo["caso_id"], canal,
                        "Cliente", "Encerrada", assunto["assunto"] if assunto else None,
                        grupo["primeira"], grupo["ultima"], 0,
                        "Migração", "Migração",
                        "Conversa reconstruída a partir de mensagens anteriores ao CRM "
                        f"(migrar_conversas_crm, {_agora_iso()}).",
                    ),
                )
                criadas += 1

            afetadas = con.execute(
                "UPDATE mensagem SET conversa_id = ? WHERE empresa_id = ? AND cliente_id = ? "
                "AND canal = ? AND conversa_id IS NULL",
                (conversa_id, empresa_id, cliente_id, canal),
            ).rowcount
            ligadas += afetadas

            con.execute(
                "UPDATE conversa SET total_mensagens = "
                "(SELECT COUNT(*) FROM mensagem WHERE conversa_id = ? AND empresa_id = ?) "
                "WHERE conversa_id = ? AND empresa_id = ?",
                (conversa_id, empresa_id, conversa_id, empresa_id),
            )

        con.commit()
        return {
            "conversas_criadas": criadas, "mensagens_ligadas": ligadas, "ja_ok": False,
            "canais_normalizados": canais_normalizados,
        }
    finally:
        con.close()


if __name__ == "__main__":
    if not CORE_DB.exists():
        print(f"ERRO: banco não encontrado em {CORE_DB}", file=sys.stderr)
        sys.exit(1)

    resultado = migrar()
    for origem, novo, quantas in resultado.get("canais_normalizados", []):
        print(f"Canal legado normalizado: {origem} -> '{novo}' ({quantas} linha(s)).")
    if resultado["ja_ok"]:
        print("Nada a fazer: toda mensagem já está ligada a uma conversa.")
    else:
        print(
            f"OK: {resultado['conversas_criadas']} conversa(s) criada(s), "
            f"{resultado['mensagens_ligadas']} mensagem(ns) ligada(s)."
        )
    # As conversas reconstruídas nascem "Encerrada" de propósito: são
    # histórico, não fila de trabalho. Se nascessem "Aberta", a caixa de
    # entrada do CRM apareceria no primeiro acesso com uma pilha de
    # atendimentos antigos parecendo pendentes.
    print("Conversas reconstruídas nascem como 'Encerrada' (histórico, não fila).")
