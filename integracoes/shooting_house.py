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
_PERFIS_HABITUALIDADE_TESTE = {
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

_EVENTOS_PADRAO = [
    {"data_participacao": "15/01/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
    {"data_participacao": "12/03/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
    {"data_participacao": "20/05/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
    {"data_participacao": "18/07/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília"},
]


def _habitualidade_simulada(cpf: str) -> dict:
    eventos = _PERFIS_HABITUALIDADE_TESTE.get(cpf, _EVENTOS_PADRAO)
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
