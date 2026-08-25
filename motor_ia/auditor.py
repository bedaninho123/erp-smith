"""Audita a resposta do Redator antes de enviar: confere se só usa dado
oficial (sem inventar/alterar prazo, valor, documento, status) e se o
atendimento deveria ter sido encaminhado a humano em vez de respondido
automaticamente. Não decide regra de negócio -- só valida o que já foi
produzido pelos outros módulos.
"""
import time
from pathlib import Path
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel

from core.configuracoes import obter_configuracoes
from core.motor_log_ia import registrar_log
from motor_ia.config import OPENAI_API_KEY
from motor_ia.planejador import Plano
from motor_ia.redator import montar_bloco_dados

PROMPT_PATH = Path(__file__).parent / "prompts" / "auditor.md"


def _carregar_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


class ResultadoAuditoriaFactual(BaseModel):
    consistente: bool
    problemas: list[str]


class ResultadoAuditoria(BaseModel):
    aprovado: bool
    acao: Literal["enviar", "encaminhar_humano", "revisar"]
    motivo: Optional[str] = None


def _auditar_consistencia_factual(
    empresa_id: str, resposta: str, bloco_dados: str, modelo: str,
    caso_id: Optional[str], sessao_id: Optional[str],
) -> ResultadoAuditoriaFactual:
    client = OpenAI(api_key=OPENAI_API_KEY)
    inicio = time.monotonic()
    try:
        completude = client.chat.completions.parse(
            model=modelo,
            messages=[
                {"role": "system", "content": _carregar_prompt()},
                {"role": "user", "content": (
                    f"DADOS DISPONÍVEIS:\n{bloco_dados}\n\n"
                    f"RESPOSTA GERADA:\n{resposta}"
                )},
            ],
            response_format=ResultadoAuditoriaFactual,
        )
    except Exception as e:
        registrar_log(
            empresa_id, prompt_key="AUDITOR", modelo=modelo, resultado="Erro",
            tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
            caso_id=caso_id, sessao_id=sessao_id, erro=f"{type(e).__name__}: {e}",
        )
        raise

    uso = completude.usage
    registrar_log(
        empresa_id, prompt_key="AUDITOR", modelo=modelo, resultado="Sucesso",
        tokens_entrada=uso.prompt_tokens if uso else None,
        tokens_saida=uso.completion_tokens if uso else None,
        tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
        caso_id=caso_id, sessao_id=sessao_id,
    )
    return completude.choices[0].message.parsed


def auditar(
    empresa_id: str, resposta: str, dados: dict, cliente_nome: str, plano: Plano,
    caso_id: Optional[str] = None, sessao_id: Optional[str] = None,
) -> ResultadoAuditoria:
    # Regra determinística primeiro, sem gastar chamada de IA: se o
    # Planejador já sinalizou que precisa de humano, a resposta gerada
    # nunca deve ser enviada automaticamente, não importa o que diga.
    # Sem chamada à OpenAI aqui, então não há nada pra registrar em log_ia.
    # (Também é por isso que este bloco não toca o banco: o freio precisa
    # funcionar mesmo que a configuração da empresa esteja indisponível.)
    if plano.encaminhar_humano:
        return ResultadoAuditoria(
            aprovado=False,
            acao="encaminhar_humano",
            motivo=plano.motivo_humano or "Sinalizado para atendimento humano.",
        )

    # Segundo freio determinístico, também sem gastar chamada de IA: uma
    # fonte externa que não pôde ser consultada (Shooting House fora do
    # ar, credencial recusada, consulta ainda sem implementação real --
    # ver motor_ia/consultor.py::_buscar_externo). Não dá pra pedir à IA
    # que "tome cuidado" com o que ela não sabe: sem o dado no bloco, o
    # comportamento natural dela é responder com o que sobrou e soar
    # completa. Num assunto de arma de fogo, uma resposta incompleta que
    # PARECE completa é pior que nenhuma, então isso vai para um humano.
    indisponiveis = dados.get("fontes_indisponiveis") or []
    if indisponiveis:
        detalhe = "; ".join(
            f"{f['fonte']}: {f['motivo']}" for f in indisponiveis
        )
        return ResultadoAuditoria(
            aprovado=False,
            acao="encaminhar_humano",
            motivo=f"Consulta externa indisponível -- {detalhe}",
        )

    config = obter_configuracoes(empresa_id)
    modelo = config.get("modelo_openai", "gpt-5-mini")
    bloco_dados = montar_bloco_dados(dados, cliente_nome, config)
    resultado_factual = _auditar_consistencia_factual(
        empresa_id, resposta, bloco_dados, modelo, caso_id, sessao_id
    )

    if not resultado_factual.consistente:
        return ResultadoAuditoria(
            aprovado=False,
            acao="revisar",
            motivo="; ".join(resultado_factual.problemas) or "Inconsistência factual encontrada.",
        )

    return ResultadoAuditoria(aprovado=True, acao="enviar", motivo=None)
