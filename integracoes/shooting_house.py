"""Cliente da API de Parceiros do Shooting House
(https://app.swaggerhub.com/apis/shootinghouse/Parceiros/1.0.1) -- o
sistema de gestão do clube de tiro que já guarda atirador, arma,
habitualidade e campeonatos. O ERP Smith não duplica esse dado; consulta
ao vivo quando precisa responder sobre ele (mesmo princípio das views do
Core: consultar, não copiar).

Enquanto a credencial (Basic Auth) não está configurada em .env
(SHOOTING_HOUSE_USER / SHOOTING_HOUSE_PASSWORD), as funções devolvem
dado simulado com "simulado": True -- permite testar o resto do
pipeline sem depender do suporte do Shooting House liberar acesso.
"""
import re
from datetime import date, datetime
from typing import Optional

import requests

from integracoes.config import (
    SHOOTING_HOUSE_BASE_URL,
    SHOOTING_HOUSE_PASSWORD,
    SHOOTING_HOUSE_USER,
    shooting_house_configurado,
)


def _limpar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf)


# Perfis variados para teste (ver core/db/gerar_clientes_ficticios.py) --
# CPF -> lista de eventos. Sem credencial de verdade, não dá pra saber o
# histórico real de ninguém, então cada CPF conhecido aqui simula um
# comportamento diferente (em dia / irregular / sem registro), para o
# pipeline poder ser testado contra respostas variadas, não sempre a mesma.
#
# Importante: nem todo cliente do despachante é atirador ativo do clube --
# transferência de arma, por exemplo, é serviço que o despachante presta
# mesmo para quem nunca pisou no clube (RCA de negócio confirmada com o
# usuário em 2026-07-23). Por isso o padrão para qualquer CPF NÃO listado
# aqui é "sem nenhum registro", não um perfil "em dia" inventado -- seria
# enganoso presumir habitualidade de quem nunca foi cadastrado como atirador.
_PERFIS_HABITUALIDADE_TESTE = {
    "12345678900": [  # Felipe Bedani (CLI-000001) -- em dia, caso de Renovação de CR
        {"data_participacao": "15/01/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
        {"data_participacao": "12/03/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
        {"data_participacao": "20/05/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
        {"data_participacao": "18/07/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
    ],
    "10000000006": [  # Helena Costa -- em dia
        {"data_participacao": "10/02/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
        {"data_participacao": "14/04/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
        {"data_participacao": "09/06/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
    ],
    "10000000014": [  # Vanessa Teixeira -- em dia
        {"data_participacao": "05/01/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília"},
        {"data_participacao": "03/03/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília"},
        {"data_participacao": "07/05/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília"},
        {"data_participacao": "12/07/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília"},
    ],
    "10000000015": [  # William Cardoso -- irregular, só 1 participação
        {"data_participacao": "22/06/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
    ],
    "10000000020": [],  # Larissa Barbosa -- sem nenhum registro
}


def _habitualidade_simulada(cpf: str) -> dict:
    # Default = sem registro, não um perfil "em dia" -- ver comentário acima.
    eventos = _PERFIS_HABITUALIDADE_TESTE.get(cpf, [])
    return {
        "simulado": True,
        "idatirador": 0,
        "atirador": "(dado simulado -- credencial do Shooting House ainda não configurada)",
        "cpf": cpf,
        "cr": None,
        "habitualidades": (
            {"ACLP": {"count": len(eventos), "eventos": eventos}} if eventos else {}
        ),
    }


# Perfis de CR pra teste -- só o Felipe (atirador de verdade nos testes,
# ver _PERFIS_HABITUALIDADE_TESTE acima) tem CR simulado; qualquer outro
# CPF não cadastrado aqui não tem CR nenhum (mesmo princípio "cliente não
# é necessariamente atirador" da habitualidade).
#
# categoria/data_ultima_confirmacao são o dado bruto; próxima_confirmacao
# e dias_restantes são CALCULADOS aqui em Python (nunca pela IA -- data é
# aritmética, não interpretação de texto, e LLM erra conta com facilidade).
_PERFIS_CR_TESTE = {
    "12345678900": {  # Felipe Bedani -- Atirador Desportivo
        "categoria_cr": "Atirador Desportivo",
        "data_ultima_confirmacao": "01/09/2025",
    },
}


def _cr_simulado(cpf: str) -> Optional[dict]:
    perfil = _PERFIS_CR_TESTE.get(cpf)
    if not perfil:
        return None

    data_confirmacao = datetime.strptime(perfil["data_ultima_confirmacao"], "%d/%m/%Y").date()
    proxima_confirmacao = data_confirmacao.replace(year=data_confirmacao.year + 1)
    dias_restantes = (proxima_confirmacao - date.today()).days

    return {
        "simulado": True,
        "cpf": cpf,
        "categoria_cr": perfil["categoria_cr"],
        "data_ultima_confirmacao": perfil["data_ultima_confirmacao"],
        "proxima_confirmacao": proxima_confirmacao.strftime("%d/%m/%Y"),
        "dias_restantes": dias_restantes,
    }


def consultar_cr(cpf: str) -> Optional[dict]:
    """Status de confirmação cadastral do CR do atirador desportivo --
    diferente de habitualidade (frequência de treino/competição). Pelo
    Decreto nº 11.615/2023, o CR do atirador desportivo não tem prazo
    fixo de vencimento: continua válido enquanto a confirmação cadastral
    anual + a habitualidade mínima estiverem em dia (ver domain/clube_
    tiro/db/popular_conhecimento.py). Devolve None se o CPF não tem CR
    registrado (nem todo cliente é atirador -- mesma regra já aplicada em
    consultar_habitualidade).

    Endpoint real do Shooting House para isso ainda não foi documentado/
    testado -- por enquanto sempre devolve dado simulado, mesmo com
    credencial configurada.
    """
    return _cr_simulado(_limpar_cpf(cpf))


def consultar_habitualidade(
    cpf: str,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> dict:
    cpf_limpo = _limpar_cpf(cpf)

    if not shooting_house_configurado():
        return _habitualidade_simulada(cpf_limpo)

    params = {}
    if data_inicio:
        params["startDate"] = data_inicio
    if data_fim:
        params["endDate"] = data_fim

    resposta = requests.get(
        f"{SHOOTING_HOUSE_BASE_URL}/registers/habitualities/{cpf_limpo}",
        params=params,
        auth=(SHOOTING_HOUSE_USER, SHOOTING_HOUSE_PASSWORD),
        timeout=10,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    return dados[0] if isinstance(dados, list) and dados else dados


if __name__ == "__main__":
    resultado = consultar_habitualidade("12345678900")
    print(f"Modo simulado: {resultado.get('simulado', False)}")
    print(resultado)
