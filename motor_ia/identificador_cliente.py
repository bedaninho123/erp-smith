"""Identifica um cliente a partir de nome, CPF, e-mail ou telefone -- o
passo 'Identificar cliente' que, no fluxo real (PROJETO_1.md, seção 6),
acontece antes da classificação da mensagem. Prioridade de busca:
CPF > e-mail > telefone > nome, do identificador mais confiável pro menos
confiável (nome não é único; os outros três são).
"""
import re
from typing import Optional

from motor_ia.conexao import conectar


def _limpar_cpf(cpf: str) -> str:
    return re.sub(r"\D", "", cpf)


def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


# Devolvido quando mais de um cliente casa com a busca. Não é o mesmo que
# "não achei": "não achei" pode cair pro próximo identificador da fila,
# "achei dois" precisa parar tudo -- ver _buscar_unico.
_AMBIGUO = object()


def _buscar_unico(con, sql: str, parametros: tuple, identificado_por: str = ""):
    """Devolve o cliente só quando ele é o ÚNICO que casa. Dois ou mais,
    devolve _AMBIGUO; nenhum, devolve None.

    Isto era `fetchone()` até 2026-08-25, e o `fetchone()` é o bug: numa
    busca por LIKE (telefone pelos 8 últimos dígitos, nome aproximado)
    duas pessoas podem casar, e o SQLite devolvia calado a primeira que
    aparecesse na varredura -- ordem que ninguém controla. O sistema
    então tratava um cliente como se fosse outro pelo resto do
    atendimento: consultava o processo dele, a habitualidade dele, as
    armas dele, e mandava tudo pro endereço de quem escreveu.

    Enquanto tudo era dado simulado isso era um incômodo. Com a API do
    Shooting House ligada, é entregar o histórico de treinos e o número
    de série da arma de uma pessoa para outra. Na dúvida entre duas, a
    resposta certa é não escolher nenhuma -- o orquestrador então pede o
    CPF, que é exato."""
    linhas = con.execute(sql, parametros).fetchmany(2)
    if len(linhas) > 1:
        return _AMBIGUO
    if not linhas:
        return None

    achado = dict(linhas[0])
    # Chave extra, que não vem do banco: por QUAL dos quatro
    # identificadores esta pessoa foi encontrada. Quem decide liberar
    # dado sensível (core/motor_identidade.py) precisa saber disso --
    # "achei pelo nome que veio escrito no cabeçalho do e-mail" e "achei
    # pelo CPF" são graus de confiança muito diferentes, e até agora os
    # dois saíam daqui exatamente iguais.
    achado["identificado_por"] = identificado_por
    return achado


def identificar_cliente(
    empresa_id: str,
    nome: Optional[str] = None,
    cpf: Optional[str] = None,
    email: Optional[str] = None,
    telefone: Optional[str] = None,
) -> Optional[dict]:
    """A busca é sempre DENTRO de uma empresa.

    Este é um dos pontos mais sensíveis do multi-tenant: o poller entrega
    aqui o e-mail de quem escreveu, e sem o filtro por empresa um
    remetente que é cliente de outro despachante seria identificado como
    cliente desta -- e receberia de volta o dado dele. A busca por nome
    (aproximada, com LIKE) é a mais arriscada das quatro, justamente por
    não ser exata."""
    con = conectar(empresa_id)
    try:
        if cpf:
            achado = _buscar_unico(
                con,
                "SELECT * FROM cliente WHERE empresa_id = ? AND cpf = ?",
                (empresa_id, _limpar_cpf(cpf)),
                "cpf",
            )
            # Ambíguo aqui interrompe tudo em vez de tentar o próximo
            # identificador: se dois cadastros têm o mesmo CPF, o
            # problema é do cadastro, e adivinhar por telefone/nome
            # depois disso só aumentaria a chance de acertar a pessoa
            # errada.
            if achado is _AMBIGUO:
                return None
            if achado:
                return achado

        if telefone:
            # `cliente.telefone` é texto livre e o cadastro histórico tem
            # de tudo: "(14) 99999-8888", "14999998888", "+55 14 99999
            # 8888". Comparar cru não acharia quase ninguém, então os dois
            # lados são reduzidos a dígitos na hora da comparação.
            #
            # O casamento é pelos 8 ÚLTIMOS dígitos, não pelo número
            # inteiro: é o que sobra depois de DDI e DDD, e é a parte que
            # nenhuma variação de formato mexe. Comparar o número todo
            # perderia quem foi cadastrado sem DDD, e o WhatsApp brasileiro
            # ainda tem a bagunça do nono dígito (a Meta manda números
            # antigos sem ele). Oito dígitos dentro de uma empresa só é
            # específico o bastante -- e o filtro de empresa continua
            # sendo a trava real, como no CPF.
            sufixo = _so_digitos(telefone)[-8:]
            if len(sufixo) == 8:
                achado = _buscar_unico(
                    con,
                    "SELECT * FROM cliente WHERE empresa_id = ? AND telefone IS NOT NULL "
                    "AND REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(telefone, '(', ''), ')', ''), "
                    "'-', ''), ' ', ''), '+', '') LIKE ?",
                        (empresa_id, f"%{sufixo}"),
                    "telefone",
                )
                if achado is _AMBIGUO:
                    return None
                if achado:
                    return achado

        if email:
            # Exato, mas ainda assim pode casar com dois: casal que usa o
            # mesmo endereço é comum, e nada no cadastro impede.
            achado = _buscar_unico(
                con,
                "SELECT * FROM cliente WHERE empresa_id = ? AND LOWER(email) = LOWER(?)",
                (empresa_id, email),
                "email",
            )
            if achado is _AMBIGUO:
                return None
            if achado:
                return achado

        if nome:
            achado = _buscar_unico(
                con,
                "SELECT * FROM cliente WHERE empresa_id = ? AND LOWER(nome) = LOWER(?)",
                (empresa_id, nome),
                "nome",
            )
            if achado is _AMBIGUO:
                return None
            if achado:
                return achado
            # Não achou exato -- tenta por aproximação (nome contém o texto).
            # É a busca mais frouxa das quatro: "Silva" casa com meia lista
            # de clientes, e é exatamente aí que a checagem de unicidade
            # mais rende.
            achado = _buscar_unico(
                con,
                "SELECT * FROM cliente WHERE empresa_id = ? AND LOWER(nome) LIKE LOWER(?)",
                (empresa_id, f"%{nome}%"),
                "nome",
            )
            if achado is _AMBIGUO:
                return None
            if achado:
                return achado

        return None
    finally:
        con.close()


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    testes = [
        {"cpf": "123.456.789-00"},
        {"email": "joao.teste@example.com"},
        {"nome": "Maria Oliveira"},
        {"nome": "Oliveira"},
        {"cpf": "000.000.000-00"},
        {"telefone": "5514999998888"},   # formato que a Meta entrega
        {"telefone": "(14) 99999-8888"},  # mesmo número, formato de cadastro
    ]
    for entrada in testes:
        resultado = identificar_cliente(EMPRESA, **entrada)
        achado = f"{resultado['cliente_id']} - {resultado['nome']}" if resultado else "não encontrado"
        print(f"{entrada} -> {achado}")
