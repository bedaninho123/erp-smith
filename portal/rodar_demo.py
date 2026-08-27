"""Sobe o Portal do Cliente com o MESMO banco temporário de gente
fictícia do painel de demonstração, e já imprime um link de entrada.

Para que serve: o Portal é a tela que o filiado vê, e era a mais difícil
de conferir -- entrar nele exige um link mágico enviado por e-mail, e no
banco de verdade isso significa usar o e-mail de um cliente real. Aqui o
cliente é a Helena Costa, inventada, e o link sai pronto no console.

    .venv\\Scripts\\python.exe -m portal.rodar_demo

Sobe em http://127.0.0.1:5012 -- porta própria, para conviver com o
Portal de verdade (5002) e com o painel de demonstração (5010).

Reaproveita `webapp.rodar_demo` de propósito: importar aquele módulo já
define ERP_CORE_DB/ERP_DOMAIN_DB para uma pasta descartável e traz as
funções que montam o banco. Duplicar a montagem aqui criaria duas
demonstrações que divergem com o tempo -- e a hora em que divergissem
seria a hora em que uma delas passaria a mostrar tela que a outra não
tem. Nada aqui escreve no banco real nem no `.env`.
"""
# O import PRECISA vir antes de qualquer coisa do projeto: é ele que
# aponta as variáveis de ambiente para a pasta temporária.
from webapp import rodar_demo as base  # noqa: E402

from core.motor_portal_auth import criar_token  # noqa: E402

PORTA = 5012
CLIENTE_DEMO = "CLI-000001"  # Helena Costa, a que tem dossiê montado


def main() -> None:
    base._criar_banco_core()
    base._criar_banco_dominio()
    base._popular_habitualidade()

    # Token de verdade, pelo mesmo motor que o e-mail usaria -- não um
    # atalho que pula a autenticação. Se o link mágico quebrar um dia,
    # esta demonstração quebra junto, que é o comportamento certo.
    token = criar_token(base.EMPRESA, CLIENTE_DEMO)
    entrada = f"http://127.0.0.1:{PORTA}/entrar/{token}"

    print()
    print("=" * 68)
    print("PORTAL DO CLIENTE -- demonstração, banco temporário")
    print("=" * 68)
    print(f"  Entre por este link (uso único, vale poucos minutos):")
    print(f"  {entrada}")
    print()
    print(f"  Cliente: Helena Costa (fictícia), com 5 documentos no dossiê")
    print(f"  Banco  : {base.PASTA}  (apagado ao fechar)")
    print("=" * 68)
    print()

    from portal.app import app

    try:
        app.run(host="127.0.0.1", port=PORTA, debug=False, use_reloader=False)
    finally:
        import shutil

        shutil.rmtree(base.PASTA, ignore_errors=True)


if __name__ == "__main__":
    main()
