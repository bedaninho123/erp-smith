"""Sincroniza a lista de filiados e o retrato de habitualidade de cada um
a partir do Shooting House.

Por que existe: o Shooting House não avisa ninguém quando um atirador
lança habitualidade no tablet. Não há push, não há "lançamentos de hoje",
e a única leitura é por CPF, uma pessoa por vez. Então o jeito de manter
um panorama do clube é perguntar de tempos em tempos.

    # rodada normal (a que a Tarefa Agendada usa)
    .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_habitualidade

    # só atualizar a lista de filiados, sem tocar em habitualidade
    .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_habitualidade --somente-lista

    # quantas pessoas consultar nesta rodada (padrão: 150)
    .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_habitualidade --limite 50

O LIMITE é o ponto mais importante deste módulo. Um clube real tem mais
de 900 filiados ativos, e habitualidade se consulta um CPF por vez -- uma
varredura completa são 900+ chamadas. Cada rodada atende quem está há
mais tempo sem sincronizar, então rodando algumas vezes por dia todo
mundo é coberto sem despejar o clube inteiro na API de uma vez.

Ainda não se sabe se o Shooting House impõe limite de chamadas; enquanto
não se souber, PAUSA_SEGUNDOS espaça as consultas de propósito.

Nada aqui escreve no Shooting House -- ver
tests/test_shooting_house_somente_leitura.py.
"""
import argparse
import time
from datetime import datetime

from domain.clube_tiro import motor_filiados
from integracoes.shooting_house import (
    ShootingHouseIndisponivel,
    consultar_habitualidade,
    listar_filiados,
)

# Respiro entre consultas. Não é otimização, é educação com um serviço de
# terceiro que a gente não controla -- e o trabalho não tem pressa nenhuma.
PAUSA_SEGUNDOS = 0.5
LIMITE_PADRAO = 150


def sincronizar_lista(empresa_id: str) -> dict:
    """Espelha a lista de filiados. Não apaga ninguém: quem sai do clube
    volta como Inativo na próxima passagem completa, e apagar linha com
    histórico de sincronização atrás é perder informação sem ganho."""
    try:
        filiados = listar_filiados(somente_ativos=False)
    except ShootingHouseIndisponivel as e:
        return {"erro": str(e), "total": 0}

    for dados in filiados:
        motor_filiados.salvar_filiado(empresa_id, dados)
    return {"erro": None, "total": len(filiados)}


def sincronizar_habitualidades(empresa_id: str, limite: int) -> dict:
    alvos = motor_filiados.proximos_a_sincronizar(empresa_id, limite)
    resultado = {"consultados": 0, "falhas": 0, "sem_participacao": 0}

    for indice, filiado in enumerate(alvos):
        if indice:
            time.sleep(PAUSA_SEGUNDOS)
        try:
            habitualidade = consultar_habitualidade(filiado["cpf"])
        except ShootingHouseIndisponivel as e:
            # Falha de um não derruba a rodada: fica registrada na linha
            # dele e a pessoa volta pro topo da fila na próxima vez.
            motor_filiados.registrar_habitualidade(
                empresa_id, filiado["filiado_id"], None, None, erro=str(e)
            )
            resultado["falhas"] += 1
            continue

        participacoes, ultima = motor_filiados.contar_participacoes(habitualidade)
        # As datas vão junto: é delas que sai o gráfico de participações
        # por dia e por mês do Dashboard. Reescrevem por inteiro o que
        # essa pessoa tinha, nunca somam -- ver registrar_habitualidade.
        datas = motor_filiados.datas_participacao(habitualidade)
        motor_filiados.registrar_habitualidade(
            empresa_id, filiado["filiado_id"], participacoes, ultima, datas=datas
        )
        resultado["consultados"] += 1
        if participacoes == 0:
            resultado["sem_participacao"] += 1

    return resultado


def sincronizar(empresa_id: str, limite: int = LIMITE_PADRAO, somente_lista: bool = False) -> dict:
    lista = sincronizar_lista(empresa_id)
    if lista["erro"]:
        return {"lista": lista, "habitualidade": None}
    if somente_lista:
        return {"lista": lista, "habitualidade": None}
    return {"lista": lista, "habitualidade": sincronizar_habitualidades(empresa_id, limite)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sincroniza filiados e habitualidade.")
    parser.add_argument("--empresa", default=None, help="empresa_id (padrão: ERP_EMPRESA_ID do .env)")
    parser.add_argument("--limite", type=int, default=LIMITE_PADRAO,
                        help=f"quantas habitualidades consultar (padrão: {LIMITE_PADRAO})")
    parser.add_argument("--somente-lista", action="store_true",
                        help="só atualiza a lista de filiados")
    argumentos = parser.parse_args()

    from atendimento.config import EMPRESA_ID

    empresa_id = argumentos.empresa or EMPRESA_ID
    inicio = datetime.now()
    print(f"[{inicio:%d/%m/%Y %H:%M}] Sincronizando filiados da empresa {empresa_id}...")

    saida = sincronizar(empresa_id, argumentos.limite, argumentos.somente_lista)

    lista = saida["lista"]
    if lista["erro"]:
        # Código != 0 para a Tarefa Agendada registrar a falha -- ela roda
        # sem console, então print() sozinho não deixaria rastro nenhum.
        print(f"FALHA ao listar filiados: {lista['erro']}")
        return 1
    print(f"  Filiados na lista: {lista['total']}")

    hab = saida["habitualidade"]
    if hab is None:
        print("  Habitualidade: não consultada (--somente-lista).")
    else:
        print(f"  Habitualidade consultada: {hab['consultados']}")
        print(f"  Sem participação na janela: {hab['sem_participacao']}")
        print(f"  Falhas: {hab['falhas']}")

    print(f"  Levou {(datetime.now() - inicio).total_seconds():.0f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
