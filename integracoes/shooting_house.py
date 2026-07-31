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
from datetime import datetime
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
#
# "arma" e "competicao" foram acrescentados em 2026-07-30, depois de ler a
# especificação real da API (SwaggerHub) -- lá, cada evento vem com o nome
# da arma usada (arma_formatada) e, quando o evento é uma competição (não
# um treino), o nome dela (competicao). Só esses dois campos foram
# adicionados -- a API real tem ~30 campos por evento (nr_sumula, cidade_uf,
# calibre, sigma etc.), mas sem ter visto uma resposta de verdade ainda,
# modelar tudo seria inventar detalhe que ninguém confirmou que o resto do
# projeto precisa. "modalidade" e "local" continuam com o mesmo sentido de
# antes: modalidade praticada e nome do clube/local do evento.
_PERFIS_HABITUALIDADE_TESTE = {
    "12345678900": [  # Felipe Bedani (CLI-000001) -- em dia, caso de Renovação de CR
        {"data_participacao": "15/01/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": None},
        {"data_participacao": "12/03/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": None},
        {"data_participacao": "20/05/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": "Copa Regional de Tiro Prático"},
        {"data_participacao": "18/07/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G3", "competicao": None},
    ],
    "10000000006": [  # Helena Costa -- em dia
        {"data_participacao": "10/02/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola 9mm Glock G3", "competicao": None},
        {"data_participacao": "14/04/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola 9mm Glock G3", "competicao": None},
        {"data_participacao": "09/06/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola 9mm Glock G3", "competicao": None},
    ],
    "10000000014": [  # Vanessa Teixeira -- em dia
        {"data_participacao": "05/01/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": None},
        {"data_participacao": "03/03/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": None},
        {"data_participacao": "07/05/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": None},
        {"data_participacao": "12/07/2026", "modalidade": "Tiro Esportivo", "local": "Clube de Tiro Marília", "arma": "Revólver .38 Taurus", "competicao": "Campeonato Estadual de Tiro Esportivo"},
    ],
    "10000000015": [  # William Cardoso -- irregular, só 1 participação
        {"data_participacao": "22/06/2026", "modalidade": "Tiro Prático", "local": "Clube de Tiro Marília", "arma": "Pistola .40 Taurus G2C", "competicao": None},
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
# categoria/data_ultima_confirmacao/nivel_cr são o dado bruto -- nivel_cr
# (1 a 3) ainda não tem endpoint conhecido no Shooting House, então por
# enquanto é cadastrado manualmente aqui mesmo (mesmo padrão de
# categoria_cr): pedido do usuário 2026-07-25, sem regra automática de
# cálculo por enquanto (não fabricar um critério que não foi confirmado
# com o cliente/órgão regulador). proxima_confirmacao é CALCULADA aqui em
# Python (nunca pela IA -- data é aritmética, não interpretação de texto,
# e LLM erra conta com facilidade). Só datas de referência, sem contagem
# de dias restantes -- decisão do usuário pra não soar como uma contagem
# regressiva de "vencimento" (o CR não vence).
#
# data_expiracao_bruta (2026-07-30): a especificação real da API tem um
# campo `documents.cr.expirationDate` em GET /registers/shooters/{id} --
# ao contrário do que este módulo assumia até agora ("endpoint real ainda
# não documentado"). Existe, então, mas com uma ressalva: pelo Decreto nº
# 11.615/2023, já confirmado com o usuário, o CR do atirador desportivo
# NÃO tem prazo fixo de vencimento -- então esse campo bruto da API não
# necessariamente significa "quando o CR vence" para efeito de resposta ao
# cliente. Por isso ele é mantido aqui separado de proxima_confirmacao,
# só para o pipeline já ter o campo disponível e testável -- nenhuma
# lógica de negócio lê data_expiracao_bruta ainda. Decidir o que fazer com
# ele (ignorar, ou é a data de emissão do CRAF do porte, algo diferente do
# CR desportivo) só quando a credencial real existir e der pra confirmar
# o que o campo de fato representa.
_PERFIS_CR_TESTE = {
    "12345678900": {  # Felipe Bedani -- Atirador Desportivo
        "categoria_cr": "Atirador Desportivo",
        "data_ultima_confirmacao": "01/09/2025",
        "nivel_cr": 2,
        "data_expiracao_bruta": "01/09/2026",
    },
}


def _cr_simulado(cpf: str) -> Optional[dict]:
    perfil = _PERFIS_CR_TESTE.get(cpf)
    if not perfil:
        return None

    data_confirmacao = datetime.strptime(perfil["data_ultima_confirmacao"], "%d/%m/%Y").date()
    proxima_confirmacao = data_confirmacao.replace(year=data_confirmacao.year + 1)

    return {
        "simulado": True,
        "cpf": cpf,
        "categoria_cr": perfil["categoria_cr"],
        "data_ultima_confirmacao": perfil["data_ultima_confirmacao"],
        "proxima_confirmacao": proxima_confirmacao.strftime("%d/%m/%Y"),
        "nivel_cr": perfil.get("nivel_cr"),
        "data_expiracao_bruta": perfil.get("data_expiracao_bruta"),
    }


# Perfis de armas pra teste -- espelha GET /registers/shooters/weapon/
# {shooterId} da API real. Esse endpoint real pede o ID interno do
# Shooting House (idatirador), não CPF -- este módulo não sabe converter
# um pro outro ainda (precisaria de um GET /registers/shooters/paginate
# ou busca equivalente por CPF, que não foi confirmado que existe com
# filtro direto). Por isso, mesmo padrão de consultar_cr: sempre simulado,
# até essa resolução CPF -> idatirador existir de verdade.
_PERFIS_ARMAS_TESTE = {
    "12345678900": [  # Felipe Bedani
        {"id": 1, "model": "G3", "brand": "Taurus", "caliber": ".40 S&W", "serie": "TA123456", "type": "Pistola"},
    ],
    "10000000006": [  # Helena Costa
        {"id": 2, "model": "G3", "brand": "Glock", "caliber": "9mm", "serie": "GL654321", "type": "Pistola"},
    ],
}


def consultar_armas(cpf: str) -> list[dict]:
    """Armas registradas do atirador. Devolve lista vazia se o CPF não
    tem arma simulada cadastrada -- nem todo cliente é atirador (mesma
    regra de consultar_habitualidade). Ver comentário acima de
    _PERFIS_ARMAS_TESTE sobre por que ainda não tem modo real."""
    return _PERFIS_ARMAS_TESTE.get(_limpar_cpf(cpf), [])


# Perfis de documentos com vencimento pra teste -- espelha GET /registers/
# shooters/documentos-por-data-vencimento da API real. Esse endpoint real
# é filtrado por INTERVALO DE DATA (dataInicio/dataFinal) e devolve o
# clube inteiro de uma vez, não por CPF -- pra usar isso de verdade
# precisaria buscar o idatirador do CPF e filtrar a resposta em massa por
# ele, o que ainda não está implementado (mesma ressalva de
# consultar_armas acima). "liberado" = documento já pode ser retirado/
# usado; "arquivo_url" fica None no simulado (não existe arquivo de
# verdade pra baixar).
_PERFIS_DOCUMENTOS_VENCIMENTO_TESTE = {
    "12345678900": [  # Felipe Bedani
        {
            "idarma": 1,
            "arma": "Pistola Taurus G3 .40 S&W",
            "cr": "12345",
            "guia_trafego": [
                {"vencimento": "10/12/2026", "arquivo_url": None, "liberado": True, "observacao": None},
            ],
            "simaf": [
                {"vencimento": "05/03/2027", "arquivo_url": None, "liberado": True},
            ],
        },
    ],
}


def consultar_documentos_vencimento(cpf: str) -> list[dict]:
    """Guia de tráfego e SIMAF por arma do atirador, com data de
    vencimento e link de download. Lista vazia = sem arma/documento
    simulado cadastrado para este CPF. Ver comentário acima de
    _PERFIS_DOCUMENTOS_VENCIMENTO_TESTE sobre por que ainda não tem modo
    real."""
    return _PERFIS_DOCUMENTOS_VENCIMENTO_TESTE.get(_limpar_cpf(cpf), [])


# Nomes dos campos-array da resposta real de habitualidade (colunares,
# paralelos por índice dentro de cada arma) que este módulo sabe mapear
# pro formato simples já consumido por portal/app.py e motor_ia/
# consultor.py. Só os campos abaixo -- a resposta real tem dezenas de
# outros (nr_sumula, cidade_uf, sigma, cms_id...) sem descrição conferida,
# então mapear todos seria inventar sentido para campo que ninguém viu
# numa resposta de verdade ainda.
_CAMPOS_EVENTO_HABITUALIDADE_REAL = {
    "modalidades_simples": "modalidade",
    "local": "local",
    "arma_formatada": "arma",
    "competicao": "competicao",
}


def _normalizar_habitualidade_real(dados_brutos: dict) -> dict:
    """Converte a resposta real de GET /registers/habitualities/{cpf} --
    colunar, agrupada em habitualidades[grupo_arma][id_arma] com arrays
    paralelos por índice -- no MESMO formato simples que o dado simulado
    sempre teve: habitualidades[grupo_arma] = {"count":, "eventos": [{...}
    ]}. Sem essa conversão, portal/app.py e motor_ia/consultor.py quebram
    no primeiro CPF consultado de verdade, porque os dois esperam
    "eventos" direto dentro de cada grupo, não mais um nível de arma por
    baixo.

    Estrutura inferida da documentação (SwaggerHub) em 2026-07-30 --
    NUNCA testada contra uma resposta real, porque a credencial ainda não
    foi liberada. Conferir e ajustar os nomes de campo aqui assim que a
    primeira resposta de verdade chegar (ver _CAMPOS_EVENTO_HABITUALIDADE_REAL).
    """
    habitualidades_brutas = dados_brutos.get("habitualidades") or {}
    habitualidades = {}
    for grupo_arma, armas in habitualidades_brutas.items():
        eventos = []
        for dados_arma in (armas or {}).values():
            datas = dados_arma.get("data_participacao") or []
            for indice, data in enumerate(datas):
                evento = {"data_participacao": data}
                for campo_real, campo_normalizado in _CAMPOS_EVENTO_HABITUALIDADE_REAL.items():
                    valores = dados_arma.get(campo_real) or []
                    if indice < len(valores):
                        evento[campo_normalizado] = valores[indice]
                eventos.append(evento)
        habitualidades[grupo_arma] = {"count": len(eventos), "eventos": eventos}

    return {
        "simulado": False,
        "idatirador": dados_brutos.get("idatirador"),
        "atirador": dados_brutos.get("atirador"),
        "matricula": dados_brutos.get("matricula"),
        "cr": dados_brutos.get("cr"),
        "cpf": dados_brutos.get("cpf"),
        "habitualidades": habitualidades,
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
    dados = dados[0] if isinstance(dados, list) and dados else dados
    return _normalizar_habitualidade_real(dados)


if __name__ == "__main__":
    resultado = consultar_habitualidade("12345678900")
    print(f"Modo simulado: {resultado.get('simulado', False)}")
    print(resultado)

    print()
    print("CR:", consultar_cr("12345678900"))

    print()
    print("Armas:", consultar_armas("12345678900"))

    print()
    print("Documentos com vencimento:", consultar_documentos_vencimento("12345678900"))
