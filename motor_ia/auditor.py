"""Audita a resposta do Redator antes de enviar: confere se só usa dado
oficial (sem inventar/alterar prazo, valor, documento, status) e se o
atendimento deveria ter sido encaminhado a humano em vez de respondido
automaticamente. Não decide regra de negócio -- só valida o que já foi
produzido pelos outros módulos.
"""
from pathlib import Path
from typing import Literal, Optional

from openai import OpenAI
from pydantic import BaseModel

from core.configuracoes import obter_configuracoes
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


def _auditar_consistencia_factual(resposta: str, bloco_dados: str) -> ResultadoAuditoriaFactual:
    config = obter_configuracoes()
    modelo = config.get("modelo_openai", "gpt-5-mini")
    client = OpenAI(api_key=OPENAI_API_KEY)
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
    return completude.choices[0].message.parsed


def auditar(resposta: str, dados: dict, cliente_nome: str, plano: Plano) -> ResultadoAuditoria:
    # Regra determinística primeiro, sem gastar chamada de IA: se o
    # Planejador já sinalizou que precisa de humano, a resposta gerada
    # nunca deve ser enviada automaticamente, não importa o que diga.
    if plano.encaminhar_humano:
        return ResultadoAuditoria(
            aprovado=False,
            acao="encaminhar_humano",
            motivo=plano.motivo_humano or "Sinalizado para atendimento humano.",
        )

    config = obter_configuracoes()
    bloco_dados = montar_bloco_dados(dados, cliente_nome, config)
    resultado_factual = _auditar_consistencia_factual(resposta, bloco_dados)

    if not resultado_factual.consistente:
        return ResultadoAuditoria(
            aprovado=False,
            acao="revisar",
            motivo="; ".join(resultado_factual.problemas) or "Inconsistência factual encontrada.",
        )

    return ResultadoAuditoria(aprovado=True, acao="enviar", motivo=None)
