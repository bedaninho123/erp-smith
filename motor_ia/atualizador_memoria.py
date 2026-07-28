"""Atualiza a memória permanente do cliente (memoria_ia) depois de uma
interação respondida com sucesso. Nunca sobrescreve a linha antiga --
inativa ela (ativo='Não') e cria uma nova (versao+1), preservando
histórico, mesmo padrão já usado em caso.ativo. Não decide regra de
negócio: só resume o que já é sabido (memória anterior + interação atual).
"""
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from openai import BadRequestError, OpenAI
from pydantic import BaseModel

from core.configuracoes import obter_configuracoes
from core.motor_log_ia import registrar_log
from motor_ia.classificador import ResultadoClassificacao
from motor_ia.conexao import conectar
from motor_ia.config import OPENAI_API_KEY

PROMPT_PATH = Path(__file__).parent / "prompts" / "atualizador_memoria.md"


def _carregar_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


class ResumoMemoria(BaseModel):
    resumo_cliente: str
    assuntos_recentes: str
    informacoes_importantes: Optional[str] = None


def _gerar_resumo(
    memoria_antiga: Optional[dict],
    classificacao: ResultadoClassificacao,
    resposta_enviada: str,
    caso_id: Optional[str] = None,
    sessao_id: Optional[str] = None,
) -> ResumoMemoria:
    config = obter_configuracoes()
    modelo = config.get("modelo_openai", "gpt-5-mini")

    if memoria_antiga:
        bloco_antiga = (
            f"Resumo anterior: {memoria_antiga.get('resumo_cliente') or '(nenhum)'}\n"
            f"Assuntos recentes anteriores: {memoria_antiga.get('assuntos_recentes') or '(nenhum)'}\n"
            f"Informações importantes anteriores: {memoria_antiga.get('informacoes_importantes') or '(nenhuma)'}"
        )
    else:
        bloco_antiga = "Não existe memória anterior -- este é o primeiro registro para este cliente."

    entrada = (
        f"MEMÓRIA ANTERIOR:\n{bloco_antiga}\n\n"
        f"INTERAÇÃO MAIS RECENTE:\n"
        f"Intenção: {classificacao.intencao}\n"
        f"Resumo da mensagem do cliente: {classificacao.resumo}\n"
        f"Resposta enviada: {resposta_enviada}"
    )

    client = OpenAI(api_key=OPENAI_API_KEY)
    mensagens = [
        {"role": "system", "content": _carregar_prompt()},
        {"role": "user", "content": entrada},
    ]
    inicio = time.monotonic()
    try:
        try:
            resposta = client.chat.completions.parse(
                model=modelo, messages=mensagens, response_format=ResumoMemoria,
            )
        except BadRequestError as e:
            if "temperature" not in str(e):
                raise
            resposta = client.chat.completions.parse(
                model=modelo, messages=mensagens, response_format=ResumoMemoria,
            )
    except Exception as e:
        registrar_log(
            prompt_key="ATUALIZADOR_MEMORIA", modelo=modelo, resultado="Erro",
            tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
            caso_id=caso_id, sessao_id=sessao_id, erro=f"{type(e).__name__}: {e}",
        )
        raise

    uso = resposta.usage
    registrar_log(
        prompt_key="ATUALIZADOR_MEMORIA", modelo=modelo, resultado="Sucesso",
        tokens_entrada=uso.prompt_tokens if uso else None,
        tokens_saida=uso.completion_tokens if uso else None,
        tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
        caso_id=caso_id, sessao_id=sessao_id,
    )
    return resposta.choices[0].message.parsed


def _proximo_memoria_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(memoria_id, 5) AS INTEGER)) FROM memoria_ia"
    ).fetchone()[0] or 0
    return f"MEM-{maior + 1:06d}"


def atualizar_memoria(
    empresa_id: str,
    cliente_id: str,
    classificacao: ResultadoClassificacao,
    dados: dict,
    resposta_enviada: str,
    caso_id: Optional[str] = None,
    sessao_id: Optional[str] = None,
) -> str:
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT * FROM memoria_ia WHERE empresa_id = ? AND cliente_id = ? AND ativo = 'Sim'",
            (empresa_id, cliente_id),
        ).fetchone()
        memoria_antiga = dict(linha) if linha else None

        resumo = _gerar_resumo(memoria_antiga, classificacao, resposta_enviada, caso_id, sessao_id)

        servicos_recentes = "; ".join(
            f"{s['service_id']} - {s['nome_servico']}" for s in dados.get("servicos", [])
        ) or (memoria_antiga or {}).get("servicos_recentes")
        processos_recentes = "; ".join(
            f"{p['processo_id']} - {p['status']}" for p in dados.get("processos", [])
        ) or (memoria_antiga or {}).get("processos_recentes")

        novo_id = _proximo_memoria_id(con)
        agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        nova_versao = (memoria_antiga["versao"] + 1) if memoria_antiga else 1

        if memoria_antiga:
            con.execute(
                "UPDATE memoria_ia SET ativo = 'Não' WHERE memoria_id = ? AND empresa_id = ?",
                (memoria_antiga["memoria_id"], empresa_id),
            )

        con.execute(
            "INSERT INTO memoria_ia (memoria_id, empresa_id, cliente_id, resumo_cliente, "
            "assuntos_recentes, servicos_recentes, processos_recentes, ultima_intencao, "
            "preferencia_canal, tom_recomendado, informacoes_importantes, "
            "restricoes_atendimento, ultima_sessao_id, atualizada_em, atualizada_por, "
            "versao, ativo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, empresa_id, cliente_id, resumo.resumo_cliente,
                resumo.assuntos_recentes, servicos_recentes, processos_recentes,
                classificacao.intencao,
                (memoria_antiga or {}).get("preferencia_canal"),
                (memoria_antiga or {}).get("tom_recomendado"),
                resumo.informacoes_importantes or (memoria_antiga or {}).get("informacoes_importantes"),
                (memoria_antiga or {}).get("restricoes_atendimento"),
                (memoria_antiga or {}).get("ultima_sessao_id"),
                agora, "Motor IA", nova_versao, "Sim",
            ),
        )
        con.commit()
        return novo_id
    finally:
        con.close()


if __name__ == "__main__":
    from motor_ia.classificador import classificar
    from motor_ia.consultor import consultar
    from motor_ia.planejador import planejar
    from motor_ia.redator import redigir

    EMPRESA = "EMP-000001"
    texto = "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001"
    classificacao = classificar(EMPRESA, texto)
    plano = planejar(classificacao)
    dados = consultar(plano, empresa_id=EMPRESA, cliente_id="CLI-000001", classificacao=classificacao)
    resposta = redigir(EMPRESA, dados, cliente_nome=dados["cliente"]["nome"])

    novo_id = atualizar_memoria(EMPRESA, "CLI-000001", classificacao, dados, resposta)
    print(f"Memória atualizada: {novo_id}")

    con = conectar(EMPRESA)
    for row in con.execute("SELECT memoria_id, versao, ativo, resumo_cliente FROM memoria_ia WHERE cliente_id = 'CLI-000001' ORDER BY versao"):
        print(dict(row))
    con.close()
