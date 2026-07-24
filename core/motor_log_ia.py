"""Registro de auditoria técnica de cada chamada à OpenAI feita pelo Motor
IA -- modelo usado, tokens de entrada/saída, tempo de processamento,
sucesso/erro. Estado do Core, sem IA (mesmo padrão de motor_sessoes/
motor_casos/motor_mensagens): só grava o que os módulos de IA já sabem
sobre a própria chamada, não decide nada sobre o conteúdo.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def registrar_log(
    prompt_key: str,
    modelo: str,
    resultado: str,
    tokens_entrada: Optional[int] = None,
    tokens_saida: Optional[int] = None,
    tempo_processamento_ms: Optional[int] = None,
    caso_id: Optional[str] = None,
    sessao_id: Optional[str] = None,
    erro: Optional[str] = None,
) -> str:
    if resultado not in ("Sucesso", "Erro"):
        raise ValueError(f"resultado inválido: {resultado} (use 'Sucesso' ou 'Erro')")

    con = conectar()
    try:
        log_id = _proximo_id(con, "log_ia", "log_id", "LOG")
        con.execute(
            "INSERT INTO log_ia VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                log_id, caso_id, sessao_id, prompt_key, modelo,
                tokens_entrada, tokens_saida, tempo_processamento_ms,
                resultado, erro, _agora_iso(),
            ),
        )
        con.commit()
        return log_id
    finally:
        con.close()
