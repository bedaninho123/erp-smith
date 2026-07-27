"""Limite simples de tentativas por janela de tempo -- usado nos formulários
de login (painel administrativo e Portal do Cliente) pra dificultar força
bruta de senha e spam do link mágico por e-mail. Em memória, por processo:
cada app (webapp/, portal/) roda isolado, então não precisa de banco nem de
biblioteca externa para isso -- reinicia zerado quando o processo reinicia,
o que é aceitável no estágio atual (hospedagem local, ver
docs/portal_cliente_arquitetura.md).
"""
import threading
import time
from collections import defaultdict, deque

_trava = threading.Lock()
_tentativas: dict[str, deque] = defaultdict(deque)


def excedeu_limite(chave: str, max_tentativas: int, janela_segundos: int) -> bool:
    """Registra uma tentativa para `chave` e devolve True se isso ultrapassa
    `max_tentativas` dentro dos últimos `janela_segundos`. Quem chama decide
    o que `chave` representa (ex.: "login_webapp:<ip>") -- este módulo só
    conta, não sabe nada sobre login/e-mail/token."""
    agora = time.monotonic()
    with _trava:
        fila = _tentativas[chave]
        while fila and agora - fila[0] > janela_segundos:
            fila.popleft()
        if len(fila) >= max_tentativas:
            return True
        fila.append(agora)
        return False


if __name__ == "__main__":
    chave = "teste"
    for i in range(3):
        print(f"tentativa {i + 1}: excedeu={excedeu_limite(chave, max_tentativas=3, janela_segundos=60)}")
    print(f"tentativa 4 (deve exceder): excedeu={excedeu_limite(chave, max_tentativas=3, janela_segundos=60)}")
