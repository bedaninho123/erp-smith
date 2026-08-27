"""Espelha o catálogo de modalidades do clube (Shooting House).

Uma chamada só, sem CPF nenhum envolvido -- é a leitura mais barata e
mais inofensiva da integração inteira: nome de modalidade não é dado de
pessoa. Por isso roda junto da sincronização da lista de filiados
(`sincronizar_habitualidade`), sem tarefa agendada própria.

    .venv\\Scripts\\python.exe -m domain.clube_tiro.sincronizar_modalidades

O que sai do catálogo do clube é marcado inativo, nunca apagado -- pode
haver resultado antigo mencionando aquela modalidade.
"""
import argparse
from datetime import datetime

from domain.clube_tiro import motor_modalidades
from integracoes.shooting_house import ShootingHouseIndisponivel, listar_modalidades


def sincronizar(empresa_id: str) -> dict:
    try:
        grupos = listar_modalidades()
    except ShootingHouseIndisponivel as e:
        # Falha aqui não é motivo para derrubar a rodada de filiados que
        # chama esta função: catálogo velho continua servindo.
        return {"erro": str(e), "grupos": 0}

    saida = motor_modalidades.salvar_catalogo(empresa_id, grupos)
    saida["erro"] = None
    saida["grupos"] = len(grupos)
    return saida


def main() -> int:
    parser = argparse.ArgumentParser(description="Espelha o catálogo de modalidades.")
    parser.add_argument("--empresa", default=None,
                        help="empresa_id (padrão: ERP_EMPRESA_ID do .env)")
    argumentos = parser.parse_args()

    from atendimento.config import EMPRESA_ID

    empresa_id = argumentos.empresa or EMPRESA_ID
    inicio = datetime.now()
    print(f"[{inicio:%d/%m/%Y %H:%M}] Sincronizando modalidades de {empresa_id}...")

    saida = sincronizar(empresa_id)
    if saida["erro"]:
        print(f"FALHA: {saida['erro']}")
        return 1

    print(f"  Grupos: {saida['grupos']}")
    print(f"  Novas: {saida['novas']} | Atualizadas: {saida['atualizadas']} "
          f"| Desativadas: {saida['desativadas']}")
    print(f"  Levou {(datetime.now() - inicio).total_seconds():.0f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
