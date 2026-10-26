"""Batimentos das rotinas de fundo e o veredito de saúde (2026-10-14).

Por que existe: a leitura de e-mail ficou quase dois meses parada
(token do Gmail vencido) sem ninguém perceber, porque o site continuava
no ar -- e o alerta de falha saía pelo mesmo Gmail quebrado. Um monitor
que só pergunta "o site responde?" teria dito que estava tudo bem.

Cada rotina registra um batimento quando termina uma rodada que DEU
CERTO de verdade (`registrar`). `avaliar()` diz quem está atrasado. A
rota `/saude` do painel publica o veredito para um monitor externo.

Em memória, por processo: é um processo só em produção
(webapp/servir.py), e as rotinas rodam dentro dele. Ao reiniciar, tudo
nasce "aguardando" -- e só vira falha se o prazo da rotina passar sem
nenhuma rodada boa, contando da subida.
"""
import threading
import time
from typing import Optional

# Prazo máximo sem uma rodada boa. E-mail roda a cada 60s: 15 min
# tolera o Google instável por uns minutos sem acordar ninguém. Backup
# roda a cada 24h: 26h dá folga para uma rodada lenta.
LIMITES_SEGUNDOS = {
    "email": 15 * 60,
    "backup": 26 * 60 * 60,
    # Cópia dos documentos para as pastas de cliente no Drive (2026-10-20):
    # roda a cada 10 min; 2h sem uma rodada boa é Drive fora do ar ou
    # autorização vencida, não instabilidade.
    "documentos_drive": 2 * 60 * 60,
    # Sincronização do clube com o Shooting House (2026-10-26): roda a
    # cada 3h. 8h tolera UMA rodada perdida (a API às vezes falha logo
    # depois de um deploy) e acusa quando duas seguidas falham.
    "habitualidade": 8 * 60 * 60,
}

_trava = threading.Lock()
_batidas: dict[str, float] = {}
_inicio = time.time()


def registrar(rotina: str) -> None:
    with _trava:
        _batidas[rotina] = time.time()


def avaliar(agora: Optional[float] = None) -> dict:
    """{rotina: 'ok' | 'aguardando' | 'atrasado'}. 'aguardando' é a rotina
    que ainda não rodou desde a subida e ainda está dentro do prazo --
    conta como saudável, senão todo deploy dispararia alarme."""
    agora = time.time() if agora is None else agora
    with _trava:
        batidas = dict(_batidas)
    estado = {}
    for rotina, limite in LIMITES_SEGUNDOS.items():
        ultima = batidas.get(rotina)
        if ultima is not None:
            estado[rotina] = "ok" if agora - ultima <= limite else "atrasado"
        else:
            estado[rotina] = "aguardando" if agora - _inicio <= limite else "atrasado"
    return estado
