"""Cliente SOMENTE LEITURA da API de Parceiros do Shooting House
(https://app.swaggerhub.com/apis/shootinghouse/Parceiros/1.0.1) -- o
sistema de gestão do clube de tiro que já guarda atirador, arma,
habitualidade e campeonatos. O ERP Smith não duplica esse dado; consulta
ao vivo quando precisa responder sobre ele (mesmo princípio das views do
Core: consultar, não copiar).

SOMENTE LEITURA, e isso é regra, não estilo: o Shooting House é o
sistema de registro que reporta à Polícia Federal e ao Exército. A
credencial TEM permissão de escrita (registrar habitualidade, cadastrar
filiado, adicionar crédito), e é justamente por isso que nenhum caminho
de escrita existe aqui -- ver tests/test_shooting_house_somente_leitura.py,
que lê este arquivo e falha se alguém acrescentar um.

Pelo mesmo motivo, este módulo nunca guarda cópia do que leu: consulta
ao vivo, sempre. Dado regulatório com duas fontes é dado que uma hora
diverge, e a fonte que vale legalmente é a deles.

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
    shooting_house_ativo,
    shooting_house_credencial_presente,
    validar_base_url,
)

# Quanto esperar a API responder antes de desistir. Curto de propósito:
# quem está esperando do outro lado é o poller (que roda a cada 2 min) e
# o Portal (com um cliente olhando a tela). Uma chamada pendurada trava
# a fila de atendimento inteira.
TIMEOUT_SEGUNDOS = 10


class ShootingHouseIndisponivel(Exception):
    """Não deu pra saber a resposta -- API fora do ar, credencial
    recusada, ou a consulta simplesmente ainda não tem implementação
    real. O ponto é que "não sei" NUNCA pode virar "não tem nada
    registrado" na resposta ao cliente: num domínio de arma de fogo,
    dizer a alguém que ele não tem CR registrado quando ele tem é pior
    do que não responder. Quem trata isso é motor_ia/consultor.py, que
    marca a fonte como indisponível e faz o atendimento ir pra um
    humano."""


def _limpar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf)


def _mascarar_cpf(cpf: str) -> str:
    """CPF vira ***.***.789-** em qualquer texto que possa acabar em log,
    e-mail de alerta ou banco.

    Isto não é preciosismo: a URL da API tem o CPF no caminho
    (.../habitualities/12345678900), e o erro que o requests levanta traz
    a URL inteira dentro da mensagem. Sem mascarar, um fora-do-ar da API
    escreveria CPF de cliente real em atendimento/poller.log, na coluna
    log_ia.erro do banco E num e-mail de alerta disparado por
    atendimento/alertas.py -- três lugares que ninguém trata como dado
    sensível."""
    digitos = _limpar_cpf(cpf or "")
    if len(digitos) != 11:
        return "(CPF inválido)"
    return f"***.***.{digitos[6:9]}-**"


def _chamar_api(caminho: str, params: Optional[dict] = None) -> dict:
    """Faz a chamada e transforma QUALQUER falha em
    ShootingHouseIndisponivel com mensagem já limpa de dado pessoal --
    nenhuma exceção crua do requests escapa daqui, justamente porque a
    mensagem crua carrega a URL com o CPF (ver _mascarar_cpf).

    allow_redirects=False de propósito: se a API responder um redirect
    para http:// (ou para outro host), o requests reenviaria a credencial
    Basic Auth para o novo endereço. Redirect aqui é tratado como falha,
    não seguido."""
    try:
        resposta = requests.get(
            f"{SHOOTING_HOUSE_BASE_URL}{caminho}",
            params=params,
            auth=(SHOOTING_HOUSE_USER, SHOOTING_HOUSE_PASSWORD),
            timeout=TIMEOUT_SEGUNDOS,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        raise ShootingHouseIndisponivel(
            f"Falha de rede ao consultar o Shooting House ({type(e).__name__})."
        ) from None  # from None: corta o encadeamento, senão a mensagem
        # original (com a URL e o CPF dentro) reaparece no traceback.

    if resposta.is_redirect or resposta.is_permanent_redirect:
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu com um redirecionamento, que não é "
            "seguido para não reenviar a credencial a outro endereço."
        )
    if resposta.status_code in (401, 403):
        raise ShootingHouseIndisponivel(
            "Shooting House recusou a credencial (verifique SHOOTING_HOUSE_USER "
            "e SHOOTING_HOUSE_PASSWORD no .env)."
        )
    if resposta.status_code == 404:
        # 404 aqui é ambíguo -- pode ser "atirador não existe" ou "rota
        # errada". Tratar como "não tem registro" seria justamente a
        # afirmação falsa que esta classe existe pra evitar.
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu 404 para esta consulta (atirador não "
            "encontrado ou endpoint mudou)."
        )
    if not resposta.ok:
        raise ShootingHouseIndisponivel(
            f"Shooting House respondeu HTTP {resposta.status_code}."
        )

    try:
        return resposta.json()
    except ValueError:
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu algo que não é JSON."
        ) from None


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
        {"id": 1, "model": "G3", "brand": "Taurus", "caliber": ".40 S&W", "serie": "TA123456", "type": "Pistola", "grupo": "ACRR"},
    ],
    "10000000006": [  # Helena Costa
        {"id": 2, "model": "G3", "brand": "Glock", "caliber": "9mm", "serie": "GL654321", "type": "Pistola", "grupo": "ACRP"},
    ],
}


def consultar_armas(cpf: str) -> list[dict]:
    """Armas registradas do atirador. Devolve lista vazia se o CPF não
    tem arma simulada cadastrada -- nem todo cliente é atirador (mesma
    regra de consultar_habitualidade). Ver comentário acima de
    _PERFIS_ARMAS_TESTE sobre por que ainda não tem modo real.

    Passou a ter modo real em 2026-08-26. Até então levantava
    ShootingHouseIndisponivel, porque se acreditava que o endpoint só
    aceitava o `idatirador` interno e que a conversão CPF -> idatirador
    não existia. Existe: é o `searchBy`, o mesmo parâmetro que faz a
    busca de cadastro funcionar.

    Uma lista vazia aqui é uma AFIRMAÇÃO ("consultei, esta pessoa não tem
    arma registrada"), e é por isso que a falha de rede vira exceção em
    vez de lista vazia -- dizer a um atirador que ele não tem arma quando
    a consulta nem aconteceu seria o pior erro possível desta função."""
    cpf_limpo = _limpar_cpf(cpf)
    if not shooting_house_ativo():
        return _PERFIS_ARMAS_TESTE.get(cpf_limpo, [])

    if len(cpf_limpo) != 11:
        raise ShootingHouseIndisponivel("CPF inválido para consulta.")

    dados = _chamar_api(
        f"/registers/shooters/weapon/{cpf_limpo}", {"searchBy": "cpf"}
    )
    if isinstance(dados, dict):
        # Algumas rotas embrulham a lista em {"data": [...]}.
        dados = dados.get("data") or []
    if not isinstance(dados, list):
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu num formato inesperado para armas."
        )
    return [
        {
            "id": a.get("id"),
            "type": a.get("type"),
            "brand": a.get("brand"),
            "model": a.get("model"),
            "caliber": a.get("caliber"),
            "serie": a.get("serie"),
            "sigma": a.get("sigma"),
            # `grupo` não está no schema Weapon documentado publicamente
            # (a especificação pública só lista id/model/caliber/serie/
            # brand/type/shooter_id/sigma). Tentativa mantida aqui porque
            # é de graça (só um .get a mais) -- mas conferido contra
            # resposta real em 2026-09-02: para a arma testada, `serie`,
            # `sigma` e `grupo` vieram todos None por este endpoint (só
            # type/brand/model/caliber vieram). `completar_arma_via_habitualidade`
            # abaixo é quem de fato preenche os três, a partir da
            # habitualidade -- ver docstring dela.
            "grupo": a.get("grupo"),
        }
        for a in dados if isinstance(a, dict)
    ]


_RE_SERIE_ARMA_FORMATADA = re.compile(r"^\(([^)]+)\)")
_RE_SIGMA_ARMA_FORMATADA = re.compile(r"n[ºo]\s*sigma:?\s*(\S+)", re.IGNORECASE)


def completar_arma_via_habitualidade(arma: dict, habitualidade: dict) -> dict:
    """Preenche série, sigma e grupo de uma arma (de `consultar_armas`)
    usando a resposta de `consultar_habitualidade` da MESMA pessoa,
    quando o endpoint de armas não trouxe esses três campos.

    Por quê: conferido contra resposta real em 2026-09-02 -- o endpoint
    de armas devolveu type/brand/model/caliber, mas serie/sigma/grupo
    vieram todos vazios para a arma testada. A habitualidade, para essa
    MESMA arma, tem os três: `grupo` é a chave de fora de
    `habitualidades[grupo][id_arma]` (já usada em portal/app.py e em
    /api/filiados/<cpf>/ficha), e `arma_formatada` embute a série entre
    parênteses no início do texto e o sigma depois de "Nº Sigma:" (ex.:
    "(ABA212416) Pistola - g17 - 9mm - Nº Sigma: 256").

    O casamento entre as duas respostas é por TEXTO (o `model` da arma
    aparecendo dentro do `arma_formatada` do evento), não pelo `id` --
    não há confirmação de que o `id` de consultar_armas() é o mesmo
    `id_arma` de dentro de habitualidades (a spec pública não liga os
    dois), e apostar nisso sem confirmar arriscaria casar arma errada em
    silêncio. Casar pelo texto foi o que os dois prints do usuário
    mostraram bater (mesmo "g17", mesmo "9mm" nos dois lados) -- e se
    nenhum evento tiver o modelo desta arma, os campos que já eram None
    continuam None, nunca um valor inventado.

    Só entra aqui o que o endpoint de armas NÃO trouxe -- campo que já
    veio de lá (`arma.get(...)` verdadeiro) nunca é sobrescrito."""
    if arma.get("serie") and arma.get("sigma") and arma.get("grupo"):
        return arma  # endpoint de armas já trouxe tudo -- nada a completar

    modelo = str(arma.get("model") or "").strip().lower()
    if not modelo:
        return arma

    for grupo, dados in (habitualidade.get("habitualidades") or {}).items():
        for evento in dados.get("eventos", []):
            texto = evento.get("arma") or ""
            if modelo not in texto.lower():
                continue
            serie_m = _RE_SERIE_ARMA_FORMATADA.match(texto)
            sigma_m = _RE_SIGMA_ARMA_FORMATADA.search(texto)
            return {
                **arma,
                "serie": arma.get("serie") or (serie_m.group(1) if serie_m else None),
                "sigma": arma.get("sigma") or (sigma_m.group(1) if sigma_m else None),
                "grupo": arma.get("grupo") or grupo,
            }
    return arma


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
    real.

    Mesma trava de consultar_armas com o modo real ligado -- e aqui o
    risco é ainda mais concreto: dizer a um atirador que a guia de
    tráfego dele está em dia (ou que não existe) sem ter consultado nada
    pode fazê-lo transportar arma com documento vencido."""
    if shooting_house_ativo():
        raise ShootingHouseIndisponivel(
            "Consulta de guia de tráfego/SIMAF ainda não tem implementação "
            "real: o endpoint do Shooting House filtra por intervalo de data "
            "e devolve o clube inteiro, sem busca por CPF."
        )
    return _PERFIS_DOCUMENTOS_VENCIMENTO_TESTE.get(_limpar_cpf(cpf), [])


# Nomes dos campos-array da resposta real de habitualidade (colunares,
# paralelos por índice dentro de cada arma) que este módulo sabe mapear
# pro formato simples já consumido por portal/app.py e motor_ia/
# consultor.py. Só os campos abaixo -- a resposta real tem dezenas de
# outros (nr_sumula, cidade_uf, sigma, cms_id...) sem descrição conferida,
# então mapear todos seria inventar sentido para campo que ninguém viu
# numa resposta de verdade ainda.
#
# CONFIRMADO CONTRA UMA RESPOSTA REAL em 2026-08-25 (não só contra a
# especificação): os cinco campos usados (os quatro abaixo +
# data_participacao) existem com estes nomes exatos, e a conversão rodou
# somando 38 participações em 2 grupos de arma. A estrutura é a esperada:
# habitualidades[grupo][id_arma][campo] = lista paralela por índice.
#
# Duas diferenças entre especificação e realidade apareceram na conferência,
# nenhuma delas em campo que usamos -- mas valem como lembrete de que uma
# não substitui a outra: a especificação diz `qtd_arma`, a resposta traz
# `qtd_armas`; e existe um `evento_2` que a especificação não menciona.
# Duas ressalvas descobertas na mesma leitura, que valem na hora de olhar
# uma resposta de verdade:
#
# - `competicao` NÃO é "nome da competição ou vazio", como o dado
#   simulado deste módulo sempre fingiu. Num treino comum ela vem com o
#   texto "TREINO". Ou seja, o filtro `if v` do Redator não a descarta, e
#   a IA recebe "competicao: TREINO" -- que ela pode fraseiar como
#   "Competição: TREINO" pro cliente. Conferir na primeira resposta real.
# - `arma_formatada` traz o número de série embutido no texto
#   ("(ABA212416) Pistola - TH380 CLUBE - 380 ACP"). É por isso que
#   mascarar só um campo chamado "serie" não bastaria pra manter número
#   de série fora do prompt da OpenAI.
_CAMPOS_EVENTO_HABITUALIDADE_REAL = {
    "modalidades_simples": "modalidade",
    "local": "local",
    "arma_formatada": "arma",
    "competicao": "competicao",
}


def _separar_data_e_hora(valor: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """A API real manda "09/10/2025 16:30" -- data E hora no mesmo campo.

    Bug pego lendo a especificação (2026-08-25), antes de acontecer: todo
    o resto do projeto trata `data_participacao` como só o dia, e
    `portal/app.py` faz `strptime(..., "%d/%m/%Y")` para ordenar a lista.
    Com a hora colada, esse strptime levanta ValueError e a tela de
    Habitualidade do Portal quebra inteira -- na primeira consulta real,
    para o primeiro atirador de verdade.

    A hora não é jogada fora (é informação legítima de um treino), só
    guardada separada em `hora_participacao`."""
    if not valor:
        return None, None
    partes = str(valor).strip().split(" ", 1)
    dia = partes[0] or None
    hora = partes[1].strip() if len(partes) > 1 and partes[1].strip() else None
    return dia, hora


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
                data_dia, hora = _separar_data_e_hora(data)
                evento = {"data_participacao": data_dia, "hora_participacao": hora}
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


# Cadastro fictício pra tela de cadastro funcionar sem credencial. Mesmo
# princípio dos outros perfis de teste: CPF desconhecido devolve None
# ("não é atirador deste clube"), nunca uma pessoa inventada.
#
# São DOIS CPFs de propósito, e a diferença entre eles é o ponto:
#
# - 529.982.247-25 tem dígito verificador válido, então percorre o fluxo
#   inteiro -- buscar, preencher, salvar. É o que usar pra ver a tela
#   funcionando de ponta a ponta.
# - 123.456.789-00 é o CPF fictício que o resto do projeto usa desde
#   sempre (habitualidade, CR, armas) e NÃO tem dígito válido. Ele acha o
#   cadastro mas é recusado por core/motor_clientes.py na hora de salvar
#   -- o que é útil de ver acontecer, porque é exatamente o que protege
#   contra um dígito trocado virar consulta ao Shooting House da pessoa
#   errada.
_PERFIS_CADASTRO_TESTE = {
    "52998224725": {
        "nome": "Felipe Bedani",
        "email": "felipe.exemplo@example.com",
        "telefone": "(14) 99999-8888",
        "cidade": "Marília",
        "matricula": "F101",
        "status_filiacao": "Ativo",
    },
    "12345678900": {
        "nome": "Atirador de Teste (CPF com dígito inválido)",
        "email": None,
        "telefone": None,
        "cidade": "Marília",
        "matricula": "F999",
        "status_filiacao": "Ativo",
    },
}

# O QUE SAI da consulta de cadastro, e nada além disso. A resposta real de
# GET /registers/shooters/{id} traz muito mais: armas, pendência
# financeira, situação documental do CR, foto, RG, data de nascimento.
# Nada disso entra aqui.
#
# O motivo é o mesmo que vale pro projeto inteiro: esta consulta existe
# pra preencher um cadastro de cliente do despachante -- nome, contato,
# cidade. Trazer arma e CR "já que veio na resposta" seria criar uma
# cópia de dado regulatório dentro do nosso banco, que é exatamente o
# que "consultar, não copiar" proíbe. Habitualidade, CR e arma se
# consultam ao vivo, na hora que alguém pergunta.
_CAMPOS_CADASTRO = ("nome", "email", "telefone", "cidade", "matricula", "status_filiacao")


def _telefone_do_shooter(dados: dict) -> Optional[str]:
    """Monta "(DD) NNNNN-NNNN" a partir do bloco `phones` da API, que vem
    com DDI, DDD e número separados. Formatação em Python: o cadastro é
    texto livre e vai ser lido por gente."""
    telefones = dados.get("phones") or {}
    if isinstance(telefones, list):
        telefones = telefones[0] if telefones else {}
    ddd = str(telefones.get("ddd") or "").strip()
    numero = re.sub(r"\D", "", str(telefones.get("number") or ""))
    if not numero:
        return None
    if len(numero) > 4:
        numero = f"{numero[:-4]}-{numero[-4:]}"
    return f"({ddd}) {numero}" if ddd else numero


def consultar_cadastro(cpf: str) -> Optional[dict]:
    """Dados cadastrais do atirador, para preencher a tela de cadastro de
    cliente do despachante. `None` = este CPF não é atirador do clube --
    o que é normal: nem todo cliente do despachante passou pelo clube.

    Devolve só os campos de `_CAMPOS_CADASTRO`; ver o comentário lá sobre
    por que o resto da resposta é descartado de propósito.
    """
    cpf_limpo = _limpar_cpf(cpf)
    if len(cpf_limpo) != 11:
        raise ShootingHouseIndisponivel("CPF inválido para consulta.")

    if not shooting_house_ativo():
        perfil = _PERFIS_CADASTRO_TESTE.get(cpf_limpo)
        return {"simulado": True, "cpf": cpf_limpo, **perfil} if perfil else None

    # searchBy: "usado para buscar por outro ID como CPF" (especificação
    # da API). É o que dispensa saber o idatirador interno.
    dados = _chamar_api(f"/registers/shooters/{cpf_limpo}", {"searchBy": "cpf"})
    if isinstance(dados, list):
        dados = dados[0] if dados else None
    if not isinstance(dados, dict) or not dados.get("name"):
        return None

    # `cidade` fica vazia de propósito. O bloco `address` da API tem
    # address, number, complement, district e zip -- NÃO tem cidade.
    # A versão anterior caía em `district` como reserva, o que gravaria o
    # BAIRRO no campo cidade do cadastro: um erro silencioso, que ninguém
    # perceberia até alguém filtrar clientes por cidade e não achar
    # ninguém. Campo vazio é honesto; campo preenchido com a coisa errada
    # não é.
    return {
        "simulado": False,
        "cpf": cpf_limpo,
        "nome": dados.get("name"),
        "email": (dados.get("email") or "").lower() or None,
        "telefone": _telefone_do_shooter(dados),
        "cidade": None,
        "matricula": dados.get("registratitionCode"),
        # "A" = ativo, "I" = inativo (definição ShooterResume). Traduzido
        # aqui porque letra solta não significa nada numa tela.
        "status_filiacao": {"A": "Ativo", "I": "Inativo"}.get(
            (dados.get("status") or "").upper()
        ),
    }


# Lista de filiados simulada. Os CPFs são exatamente os de
# _PERFIS_HABITUALIDADE_TESTE, de propósito: assim o panorama do clube
# nasce com variedade real -- gente em dia, gente irregular e gente sem
# registro nenhum -- em vez de uma tabela toda zerada que não mostra se a
# tela funciona.
_FILIADOS_TESTE = [
    {"idatirador": 101, "matricula": "F101", "nome": "Felipe Bedani",
     "cpf": "12345678900", "email": "felipe.exemplo@example.com", "status_filiacao": "Ativo"},
    {"idatirador": 102, "matricula": "F102", "nome": "Helena Costa",
     "cpf": "10000000006", "email": None, "status_filiacao": "Ativo"},
    {"idatirador": 103, "matricula": "F103", "nome": "Vanessa Teixeira",
     "cpf": "10000000014", "email": None, "status_filiacao": "Ativo"},
    {"idatirador": 104, "matricula": "F104", "nome": "William Cardoso",
     "cpf": "10000000015", "email": None, "status_filiacao": "Ativo"},
    {"idatirador": 105, "matricula": "F105", "nome": "Larissa Barbosa",
     "cpf": "10000000020", "email": None, "status_filiacao": "Ativo"},
    {"idatirador": 106, "matricula": "F106", "nome": "Ex-Filiado Exemplo",
     "cpf": "39053344705", "email": None, "status_filiacao": "Inativo"},
]


# Catálogo de modalidades de teste. Poucas e reconhecíveis de propósito:
# quem abrir a tela no modo simulado precisa perceber na hora que está
# vendo dado de exemplo, não as 300 modalidades do clube.
_MODALIDADES_TESTE = [
    {"grupo_id": 1, "grupo": "Tiro ao Prato (exemplo)",
     "modalidades": [{"id": 1, "nome": "Trap Americano"}, {"id": 2, "nome": "Skeet"}]},
    {"grupo_id": 4, "grupo": "Tiro de Precisão (exemplo)",
     "modalidades": [{"id": 30, "nome": "Saque Rápido"}, {"id": 31, "nome": "Duelo 20s"}]},
]


def listar_modalidades() -> list[dict]:
    """GET /championship/modalities/groups -- o catálogo de modalidades
    do clube, agrupado.

    É o ÚNICO endpoint de campeonato que responde com dado para esta
    credencial (2026-08-27): `/championship/stage` devolve lista vazia, e
    sem id de etapa não há como chamar os resultados por prova. Ver
    CLAUDE.md, "Financeiro do clube".

    Catálogo puro -- nome de modalidade não é dado de pessoa nenhuma, ao
    contrário de tudo o mais que este módulo lê.
    """
    if not shooting_house_ativo():
        return _MODALIDADES_TESTE

    dados = _chamar_api("/championship/modalities/groups", {})
    grupos = []
    for item in dados if isinstance(dados, list) else []:
        modalidades = [
            {"id": m.get("id"), "nome": (m.get("name") or "").strip()}
            for m in (item.get("modalities") or [])
            if m.get("id") is not None and (m.get("name") or "").strip()
        ]
        if not modalidades:
            # Grupo sem modalidade não vira linha: seria um item de menu
            # que não leva a lugar nenhum.
            continue
        grupos.append({
            "grupo_id": item.get("id"),
            # O clube tem um grupo com nome vazio (id 1000, onde ficam as
            # modalidades criadas por eles). Sem este rótulo a tela
            # mostraria um cabeçalho em branco com 35 itens embaixo.
            "grupo": (item.get("name") or "").strip() or "Sem grupo",
            "modalidades": modalidades,
        })
    return grupos


def _dentro(bloco: dict, *caminho):
    """Desce por um caminho de chaves, devolvendo None em qualquer buraco.

    A resposta da API traz `monthly`, `financial`, `documents` e `orders`
    como blocos aninhados que às vezes vêm vazios ou ausentes. Sem isto,
    um bloco faltando viraria KeyError no meio de uma sincronização de 40
    páginas -- e derrubaria a rodada inteira por causa de um cadastro
    incompleto.
    """
    atual = bloco
    for chave in caminho:
        if not isinstance(atual, dict):
            return None
        atual = atual.get(chave)
    return atual


def _sim_nao(valor) -> Optional[str]:
    """bool da API -> "Sim"/"Não" do projeto. **None continua None.**

    A distinção é a de sempre: `False` é "consultei, está em atraso";
    `None` é "o campo não veio". Transformar ausência em "Não" faria o
    painel acusar de inadimplente quem só tem cadastro incompleto.
    """
    if valor is None:
        return None
    return "Sim" if bool(valor) else "Não"


def _data_iso(valor) -> Optional[str]:
    """Data da API -> 'AAAA-MM-DD'. Aceita os dois formatos que aparecem
    na mesma resposta (ISO e dd/mm/aaaa) e devolve None no que não
    entender -- data ilegível vira ausência, nunca data errada."""
    texto = str(valor or "").strip()
    if not texto:
        return None
    if len(texto) >= 10 and texto[4] == "-" and texto[7] == "-":
        return texto[:10]
    if len(texto) >= 10 and texto[2] == "/" and texto[5] == "/":
        dia, mes, ano = texto[:10].split("/")
        return f"{ano}-{mes}-{dia}"
    return None


def listar_filiados(somente_ativos: bool = True) -> list[dict]:
    """Lista os filiados do clube (GET /registers/shooters/paginate).

    É o espelho que alimenta a tabela `filiado` do Domínio. Traz só campos
    de identificação -- nada de arma, CR ou situação financeira, pela mesma
    razão de `consultar_cadastro`.

    ATENÇÃO ao volume: um clube real tem mais de mil filiados. Este
    endpoint é o ÚNICO que devolve gente em massa, e é por isso que a
    sincronização de habitualidade não pode se apoiar nele -- habitualidade
    continua sendo uma consulta por CPF, uma pessoa por vez.

    NÃO EXISTE "todos" neste endpoint: `status` é 1 (ativo) ou 0 (inativo),
    e só. Este código mandava 0 achando que era "sem filtro", e a primeira
    execução real trouxe 547 pessoas num clube de 1454 -- exatamente o
    número de INATIVOS. O estrago seria silencioso: o panorama listaria só
    inativos, e a sincronização de habitualidade, que busca quem está
    'Ativo', não acharia ninguém e não faria nada, sem erro nenhum. Para
    ter o clube inteiro é preciso pedir as duas listas e juntar.
    """
    if not shooting_house_ativo():
        return [
            f for f in _FILIADOS_TESTE
            if not somente_ativos or f["status_filiacao"] == "Ativo"
        ]

    if somente_ativos:
        return _listar_por_status(ativos=True)
    # Duas chamadas, uma por status. A deduplicação por CPF de
    # _listar_por_status vale dentro de cada lista; aqui as duas são
    # concatenadas, e um CPF não pode estar nas duas ao mesmo tempo.
    return _listar_por_status(ativos=True) + _listar_por_status(ativos=False)


def _listar_por_status(ativos: bool) -> list[dict]:
    filiados = []
    # Não dá pra saber, pela PRIMEIRA resposta, se o parâmetro `page`
    # está sendo respeitado -- só comparando com a segunda. Ou seja: uma
    # chamada repetida é inevitável para detectar. Duplicar gente no
    # resultado, não: este conjunto garante que a mesma pessoa entre uma
    # vez só, aconteça o que acontecer com a paginação.
    cpfs_vistos = set()
    pagina = 1
    ultima_pagina_vista = 0
    while True:
        parametros = {"status": 1 if ativos else 0, "page": pagina}
        resposta = _chamar_api("/registers/shooters/paginate", parametros)

        if isinstance(resposta, list):
            lote, tem_proxima = resposta, False
        else:
            lote = resposta.get("data") or []
            paginacao = (resposta.get("meta") or {}).get("pagination") or {}
            pagina_atual = paginacao.get("current_page") or 0
            total_paginas = paginacao.get("total_pages") or 1

            # A especificação documenta só `sortBy` e `status` neste
            # endpoint -- `page` é suposição nossa, tirada do formato da
            # resposta (que traz current_page/total_pages). Se ele for
            # ignorado, `current_page` fica parada no 1 e o laço pediria
            # a MESMA página até bater a trava: 200 chamadas à API do
            # fornecedor e milhares de linhas repetidas.
            #
            # Então a condição de continuar não é "existe próxima", é "a
            # página ANDOU". Não andou, para -- com uma página de dado em
            # vez de nenhuma, e sem martelar ninguém.
            if pagina_atual <= ultima_pagina_vista:
                tem_proxima = False
            else:
                ultima_pagina_vista = pagina_atual
                tem_proxima = pagina_atual < total_paginas

        for item in lote:
            cpf_limpo = _limpar_cpf(str(item.get("cpf") or ""))
            if len(cpf_limpo) != 11 or not item.get("name"):
                # Sem CPF válido não dá pra ligar com nada nem consultar
                # habitualidade depois -- entra no relatório da
                # sincronização em vez de virar linha inútil no banco.
                continue
            if cpf_limpo in cpfs_vistos:
                continue
            cpfs_vistos.add(cpf_limpo)
            filiados.append({
                "idatirador": item.get("id"),
                "matricula": item.get("registratitionCode"),
                "nome": item.get("name"),
                "cpf": cpf_limpo,
                "email": (item.get("email") or "").lower() or None,
                "status_filiacao": {"A": "Ativo", "I": "Inativo"}.get(
                    (item.get("status") or "").upper()
                ),
                # --- vínculo e situação financeira (2026-08-27) ---
                # Estes campos vêm DE GRAÇA nesta mesma resposta. Descobrir
                # isso mudou o desenho inteiro do Financeiro: a situação de
                # anuidade do clube todo sai em ~40 chamadas paginadas, e
                # não numa consulta por CPF como a habitualidade.
                #
                # `monthly` é a anuidade/mensalidade: status é "em dia sim
                # ou não" e expirationDate é ATÉ QUANDO vale. `financial` é
                # a situação financeira geral (inclui comanda em aberto).
                # Os dois são bool na origem -- convertidos aqui para o
                # "Sim"/"Não" que o resto do projeto usa, com None quando o
                # campo não veio: ausente não é "está devendo".
                "data_filiacao": _data_iso(item.get("affiliationDate")),
                "tipo_filiado": item.get("type"),
                "anuidade_em_dia": _sim_nao(_dentro(item, "monthly", "status")),
                "anuidade_validade": _data_iso(_dentro(item, "monthly", "expirationDate")),
                "financeiro_em_dia": _sim_nao(_dentro(item, "financial", "status")),
                "cr_numero": _dentro(item, "documents", "cr", "number"),
                "cr_validade": _data_iso(_dentro(item, "documents", "cr", "expirationDate")),
                "cr_em_dia": _sim_nao(_dentro(item, "documents", "cr", "status")),
                "tem_pedido_aberto": _sim_nao(_dentro(item, "orders", "status")),
            })

        if not tem_proxima or not lote:
            return filiados
        pagina += 1
        if pagina > 200:  # trava de segurança contra paginação sem fim
            return filiados


def _buscar_atirador(cpf_limpo: str) -> Optional[dict]:
    """GET /registers/shooters/{cpf}?searchBy=cpf -- a resposta crua.

    `searchBy` é o parâmetro que a especificação descreve como "usado para
    buscar por outro ID como CPF"; é ele que dispensa saber o `idatirador`
    interno. O valor "cpf" ainda não foi confirmado contra a API real: se
    estiver errado, o sintoma é não achar ninguém, não um erro."""
    dados = _chamar_api(f"/registers/shooters/{cpf_limpo}", {"searchBy": "cpf"})
    if isinstance(dados, list):
        dados = dados[0] if dados else None
    return dados if isinstance(dados, dict) and dados.get("name") else None


def consultar_ficha_completa(cpf: str) -> Optional[dict]:
    """Tudo que a API sabe sobre o atirador, para EXIBIR na tela do
    painel -- nunca para guardar.

    Diferente de `consultar_cadastro`, que é enxuta de propósito: aquela
    alimenta o formulário de cliente novo, e trazer arma ou CR pra lá
    criaria cópia de dado regulatório no nosso banco. Esta é consulta ao
    vivo, mostrada e descartada -- é o "consultar, não copiar" fazendo o
    trabalho dele.

    None = este CPF não é atirador do clube. Devolve `simulado: True`
    enquanto a chave geral estiver desligada.
    """
    cpf_limpo = _limpar_cpf(cpf)
    if len(cpf_limpo) != 11:
        raise ShootingHouseIndisponivel("CPF inválido para consulta.")

    if not shooting_house_ativo():
        perfil = _PERFIS_CADASTRO_TESTE.get(cpf_limpo)
        if not perfil:
            return None
        return {
            "simulado": True, "cpf": cpf_limpo, **perfil,
            "rg": None, "nascimento": None, "filiado_desde": None,
            "profissao": None, "estado_civil": None, "titulo": None,
            "endereco": None, "cr": None,
            "anuidade_em_dia": "Sim", "anuidade_validade": "2027-03-31",
            "financeiro_em_dia": "Sim",
        }

    dados = _buscar_atirador(cpf_limpo)
    if not dados:
        return None

    endereco = dados.get("address") or {}
    cr_bruto = ((dados.get("documents") or {}).get("cr")) or {}
    return {
        "simulado": False,
        "cpf": cpf_limpo,
        "idatirador": dados.get("id"),
        "matricula": dados.get("registratitionCode"),
        "nome": dados.get("name"),
        "email": (dados.get("email") or "").lower() or None,
        "telefone": _telefone_do_shooter(dados),
        "rg": dados.get("rg"),
        "nascimento": dados.get("birthDate"),
        "filiado_desde": dados.get("affiliationDate"),
        "profissao": dados.get("profession"),
        "estado_civil": dados.get("civilStatus"),
        "titulo": (dados.get("title") or {}).get("name"),
        "status_filiacao": {"A": "Ativo", "I": "Inativo"}.get(
            (dados.get("status") or "").upper()
        ),
        # Só a rua/bairro/CEP -- a API não tem cidade neste bloco (ver
        # consultar_cadastro), então não se inventa uma.
        "endereco": {
            "logradouro": endereco.get("address"),
            "numero": endereco.get("number"),
            "complemento": endereco.get("complement"),
            "bairro": endereco.get("district"),
            "cep": endereco.get("zip"),
        } if endereco else None,
        # `status` aqui é "situação documental em dia", booleano da API --
        # não é a mesma coisa que "o CR não vence" (Decreto nº
        # 11.615/2023). A tela mostra o campo, sem concluir nada dele.
        "cr": {
            "numero": cr_bruto.get("number"),
            "em_dia": cr_bruto.get("status"),
            "data_expiracao_bruta": cr_bruto.get("expirationDate"),
        } if cr_bruto else None,
        # Anuidade/financeiro (2026-09-03) -- mesmos campos que
        # `_listar_por_status` já lê pra popular `filiado` em massa, só
        # que AO VIVO aqui: essa é a diferença que a docstring desta
        # função promete ("pergunta na hora", nunca o retrato). `monthly`
        # é a anuidade (status + até quando vale); `financial` é a
        # situação financeira geral. `_sim_nao`/`_data_iso` preservam
        # None quando o campo não veio -- ausência não é "em atraso".
        "anuidade_em_dia": _sim_nao(_dentro(dados, "monthly", "status")),
        "anuidade_validade": _data_iso(_dentro(dados, "monthly", "expirationDate")),
        "financeiro_em_dia": _sim_nao(_dentro(dados, "financial", "status")),
    }


def verificar_credencial() -> dict:
    """Bate no GET /checkAuth, que só responde "a autenticação vale ou
    não" -- sem CPF, sem nome, sem dado de pessoa nenhuma no caminho da
    URL nem na resposta.

    É a forma certa de descobrir se a credencial recebida pertence ao
    ambiente configurado em SHOOTING_HOUSE_BASE_URL: credencial de
    produção batendo no servidor de homologação (ou o contrário) é
    recusada, e a recusa já é a resposta. Antes de existir este caminho,
    a única maneira de testar era consultar a habitualidade de alguém --
    ou seja, usar o dado de uma pessoa real como material de teste.

    Devolve {"ok": bool, "detalhe": str}. Não levanta exceção: quem chama
    é diagnóstico, e "falhou" aqui é resultado, não erro de programação.
    """
    if not shooting_house_credencial_presente():
        return {"ok": False, "detalhe": "Credencial não configurada no .env."}
    try:
        validar_base_url()
        _chamar_api("/checkAuth")
    except (ShootingHouseIndisponivel, RuntimeError) as e:
        return {"ok": False, "detalhe": str(e)}
    return {"ok": True, "detalhe": "Credencial aceita por este servidor."}


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
    credencial configurada. Com o modo real ligado, levanta
    ShootingHouseIndisponivel em vez de devolver None (mesma razão de
    consultar_armas: None aqui seria lido como "este cliente não tem CR",
    e a IA diria isso a um atirador que tem).
    """
    if shooting_house_ativo():
        raise ShootingHouseIndisponivel(
            "Consulta de CR ainda não tem implementação real: falta confirmar "
            "com o Shooting House qual endpoint devolve a confirmação "
            "cadastral do CR por CPF."
        )
    return _cr_simulado(_limpar_cpf(cpf))


def consultar_habitualidade(
    cpf: str,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> dict:
    cpf_limpo = _limpar_cpf(cpf)

    if not shooting_house_ativo():
        return _habitualidade_simulada(cpf_limpo)

    if len(cpf_limpo) != 11:
        # Não manda pra API o que já se sabe que é inválido -- CPF entra
        # na URL, e texto solto de cliente ("meu cpf é o mesmo de antes")
        # não tem por que virar caminho de requisição.
        raise ShootingHouseIndisponivel("CPF inválido para consulta.")

    params = {}
    if data_inicio:
        params["startDate"] = data_inicio
    if data_fim:
        params["endDate"] = data_fim

    dados = _chamar_api(f"/registers/habitualities/{cpf_limpo}", params)

    if isinstance(dados, list):
        if not dados:
            # LISTA VAZIA = a pessoa não tem nenhuma participação
            # registrada. É resposta legítima, não falha -- e é o caso
            # mais importante do panorama, porque é exatamente quem está
            # atrasado.
            #
            # Até 2026-08-25 isto caía no "formato inesperado" abaixo e
            # virava ShootingHouseIndisponivel: o sistema transformava
            # "sei que não treinou" em "não consegui consultar", e a
            # pessoa aparecia como erro em vez de aparecer como zero.
            # Descoberto na primeira sincronização real -- 3 das 25
            # pessoas consultadas eram assim.
            return _normalizar_habitualidade_real({"cpf": cpf_limpo})
        dados = dados[0]

    if not isinstance(dados, dict):
        raise ShootingHouseIndisponivel(
            "Shooting House respondeu num formato inesperado para habitualidade."
        )
    return _normalizar_habitualidade_real(dados)


if __name__ == "__main__":
    # Teste de fumaça com o CPF fictício de sempre. Recusa rodar com o
    # modo real ligado: este bloco imprime a resposta inteira na tela, e
    # com credencial de verdade isso seria despejar o histórico de
    # treinos e as armas de uma pessoa real no terminal (e no histórico
    # do PowerShell). Para conferir a API real existe outro caminho, que
    # mostra só a ESTRUTURA da resposta e nenhum valor:
    #     .venv\Scripts\python.exe -m integracoes.diagnostico_shooting_house
    if shooting_house_ativo():
        raise SystemExit(
            "Modo real ligado (SHOOTING_HOUSE_ATIVO=Sim). Este teste de fumaça "
            "imprime dado pessoal na tela e por isso não roda assim.\n"
            "Use: .venv\\Scripts\\python.exe -m integracoes.diagnostico_shooting_house"
        )

    resultado = consultar_habitualidade("12345678900")
    print(f"Modo simulado: {resultado.get('simulado', False)}")
    print(resultado)

    print()
    print("CR:", consultar_cr("12345678900"))

    print()
    print("Armas:", consultar_armas("12345678900"))

    print()
    print("Documentos com vencimento:", consultar_documentos_vencimento("12345678900"))
