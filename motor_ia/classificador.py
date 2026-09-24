"""Classifica a intenção de uma mensagem recebida do cliente. Não decide
regra de negócio nenhuma -- só interpreta o texto e extrai o que já está
explícito nele. O prompt de instrução vive em motor_ia/prompts/classificador.md
(versionado como arquivo, não hardcoded); modelo e temperatura vêm da
tabela configuracoes do Core, não fixos no código.
"""
import sqlite3
import time
from pathlib import Path
from typing import Literal, Optional

from openai import BadRequestError, OpenAI
from pydantic import BaseModel

from core.configuracoes import obter_configuracoes
from core.motor_log_ia import registrar_log
from motor_ia.config import OPENAI_API_KEY
from motor_ia.conexao import DOMAIN_DB, conectar

PROMPT_PATH = Path(__file__).parent / "prompts" / "classificador.md"

Intencao = Literal[
    "CONSULTA_DOCUMENTOS",
    "CONSULTA_PROCESSO",
    "CONSULTA_CLIENTE",
    "CONSULTA_HABITUALIDADE",
    "CONSULTA_CR",
    "CONSULTA_DOCUMENTOS_VENCIMENTO",
    "CONSULTA_CAMPEONATOS",
    "ATENDIMENTO_GERAL",
    "ATENDIMENTO_HUMANO",
]


class ResultadoClassificacao(BaseModel):
    intencao: Intencao
    resumo: str
    # ATENÇÃO: não use este campo para decidir acesso a nada. Desde
    # 2026-08-25 o orquestrador manda o texto com os CPFs já mascarados,
    # então o que vier aqui é o número mascarado, não o real. E mesmo se
    # não fosse: é um valor produzido pela IA a partir da mensagem que o
    # remetente escreveu, então não serve de prova de identidade. Quem
    # extrai CPF pra valer é core/motor_identidade.py::extrair_cpfs, em
    # Python. Mantido só porque o prompt do Classificador ainda o pede.
    cpf_mencionado: Optional[str] = None
    protocolo_mencionado: Optional[str] = None
    servico_mencionado: Optional[str] = None
    categoria_conhecimento: Optional[str] = None
    # Mesmo espírito de categoria_conhecimento: filtra o que o Consultor
    # busca em vez de despejar todo fato institucional (endereço,
    # anuidade, estrutura...) numa pergunta que só queria o horário.
    # Achado em 2026-09-23: sem isso, toda pergunta ATENDIMENTO_GERAL
    # recebia a lista inteira de informacoes_empresa e a IA respondia com
    # um catálogo completo em vez do único fato perguntado.
    topico_institucional: Optional[str] = None
    precisa_humano: bool


def _carregar_servicos_ativos(empresa_id: str) -> list[str]:
    # Via conectar() e não sqlite3.connect direto: VW_SERVICO agora
    # filtra por empresa_atual(), que só existe numa conexão do Core.
    con = conectar(empresa_id)
    try:
        return [
            r[0] for r in con.execute(
                "SELECT nome_servico FROM VW_SERVICO WHERE ativo = 'Sim'"
            ).fetchall()
        ]
    finally:
        con.close()


def _carregar_categorias_conhecimento() -> list[str]:
    # Sem empresa_id de propósito: conhecimento é legislação federal,
    # compartilhada entre todas as empresas do domínio.
    con = sqlite3.connect(DOMAIN_DB)
    try:
        return [
            r[0] for r in con.execute(
                "SELECT DISTINCT categoria FROM conhecimento "
                "WHERE aprovado = 'Sim' AND ativo = 'Sim' ORDER BY categoria"
            ).fetchall()
        ]
    finally:
        con.close()


def _carregar_prompt(servicos: list[str], categorias_conhecimento: list[str]) -> str:
    texto = PROMPT_PATH.read_text(encoding="utf-8")
    lista_servicos = "\n".join(f"- {s}" for s in servicos)
    lista_categorias = "\n".join(f"- {c}" for c in categorias_conhecimento)
    texto = texto.replace("{lista_servicos}", lista_servicos)
    texto = texto.replace("{lista_categorias_conhecimento}", lista_categorias)
    return texto


def classificar(empresa_id: str, mensagem: str) -> ResultadoClassificacao:
    config = obter_configuracoes(empresa_id)
    modelo = config.get("modelo_openai", "gpt-5-mini")
    temperatura = float(config.get("temperatura_ia", 0.2))
    servicos = _carregar_servicos_ativos(empresa_id)
    categorias_conhecimento = _carregar_categorias_conhecimento()

    client = OpenAI(api_key=OPENAI_API_KEY)
    mensagens = [
        {"role": "system", "content": _carregar_prompt(servicos, categorias_conhecimento)},
        {"role": "user", "content": mensagem},
    ]
    inicio = time.monotonic()
    try:
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
    except Exception as e:
        registrar_log(
            empresa_id, prompt_key="CLASSIFICADOR", modelo=modelo, resultado="Erro",
            tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
            erro=f"{type(e).__name__}: {e}",
        )
        raise

    uso = resposta.usage
    # caso_id/sessao_id ainda não existem neste ponto do fluxo -- a
    # classificação acontece antes de qualquer um dos dois ser
    # localizado/criado no orquestrador.
    registrar_log(
        empresa_id, prompt_key="CLASSIFICADOR", modelo=modelo, resultado="Sucesso",
        tokens_entrada=uso.prompt_tokens if uso else None,
        tokens_saida=uso.completion_tokens if uso else None,
        tempo_processamento_ms=int((time.monotonic() - inicio) * 1000),
    )
    return resposta.choices[0].message.parsed


if __name__ == "__main__":
    exemplos = [
        "Quais documentos preciso para renovar meu CR?",
        "Meu CPF é 123.456.789-00, quero saber como está o processo PROTO-2026-001",
        "Isso é um absurdo, ninguém me responde há uma semana, quero falar com uma pessoa AGORA",
    ]
    for texto in exemplos:
        resultado = classificar("EMP-000001", texto)
        print(f"Mensagem: {texto}")
        print(f"  -> {resultado.model_dump()}")
        print()
