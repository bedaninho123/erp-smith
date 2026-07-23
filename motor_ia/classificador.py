"""Classifica a intenção de uma mensagem recebida do cliente. Não decide
regra de negócio nenhuma -- só interpreta o texto e extrai o que já está
explícito nele. O prompt de instrução vive em motor_ia/prompts/classificador.md
(versionado como arquivo, não hardcoded); modelo e temperatura vêm da
tabela configuracoes do Core, não fixos no código.
"""
import sqlite3
from pathlib import Path
from typing import Literal, Optional

from openai import BadRequestError, OpenAI
from pydantic import BaseModel

from core.configuracoes import obter_configuracoes
from motor_ia.config import OPENAI_API_KEY
from motor_ia.conexao import CORE_DB

PROMPT_PATH = Path(__file__).parent / "prompts" / "classificador.md"

Intencao = Literal[
    "CONSULTA_DOCUMENTOS",
    "CONSULTA_PROCESSO",
    "CONSULTA_CLIENTE",
    "CONSULTA_HABITUALIDADE",
    "ATENDIMENTO_GERAL",
    "ATENDIMENTO_HUMANO",
]


class ResultadoClassificacao(BaseModel):
    intencao: Intencao
    resumo: str
    cpf_mencionado: Optional[str] = None
    protocolo_mencionado: Optional[str] = None
    servico_mencionado: Optional[str] = None
    precisa_humano: bool


def _carregar_servicos_ativos() -> list[str]:
    con = sqlite3.connect(CORE_DB)
    try:
        return [
            r[0] for r in con.execute(
                "SELECT nome_servico FROM VW_SERVICO WHERE ativo = 'Sim'"
            ).fetchall()
        ]
    finally:
        con.close()


def _carregar_prompt(servicos: list[str]) -> str:
    texto = PROMPT_PATH.read_text(encoding="utf-8")
    lista = "\n".join(f"- {s}" for s in servicos)
    return texto.replace("{lista_servicos}", lista)


def classificar(mensagem: str) -> ResultadoClassificacao:
    config = obter_configuracoes()
    modelo = config.get("modelo_openai", "gpt-5-mini")
    temperatura = float(config.get("temperatura_ia", 0.2))
    servicos = _carregar_servicos_ativos()

    client = OpenAI(api_key=OPENAI_API_KEY)
    mensagens = [
        {"role": "system", "content": _carregar_prompt(servicos)},
        {"role": "user", "content": mensagem},
    ]
    try:
        resposta = client.chat.completions.parse(
            model=modelo, temperature=temperatura, messages=mensagens,
            response_format=ResultadoClassificacao,
        )
    except BadRequestError as e:
        # Modelos da família "raciocínio" (ex.: gpt-5-mini) só aceitam a
        # temperatura padrão -- tenta de novo sem o parâmetro.
        if "temperature" not in str(e):
            raise
        resposta = client.chat.completions.parse(
            model=modelo, messages=mensagens,
            response_format=ResultadoClassificacao,
        )
    return resposta.choices[0].message.parsed


if __name__ == "__main__":
    exemplos = [
        "Quais documentos preciso para renovar meu CR?",
        "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001",
        "Isso é um absurdo, ninguém me responde há uma semana, quero falar com uma pessoa AGORA",
    ]
    for texto in exemplos:
        resultado = classificar(texto)
        print(f"Mensagem: {texto}")
        print(f"  -> {resultado.model_dump()}")
        print()
