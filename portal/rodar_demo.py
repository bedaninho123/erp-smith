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

import os  # noqa: E402

# Gmail DESLIGADO na demonstração (2026-10-14): com o token.json do clube
# na pasta do projeto, pedir acesso pela tela de login mandaria e-mail de
# verdade, pela conta do atendimento, para o endereço da cliente
# inventada. Apontando para um arquivo que não existe, o Portal cai no
# caminho de desenvolvimento e imprime link e código aqui no console.
os.environ["ERP_GMAIL_TOKEN_PATH"] = str(base.PASTA / "sem_gmail_na_demo.json")

from core.motor_portal_auth import criar_token  # noqa: E402

PORTA = 5012
CLIENTE_DEMO = "CLI-000001"  # Helena Costa, a que tem dossiê montado


def _anuidades_de_exemplo() -> list[tuple[str, str]]:
    """Os três jeitos de estar com a anuidade (2026-11-10, ver
    domain/clube_tiro/regra_anuidade.py), cada um numa pessoa inventada
    que já é filiada na lista simulada do clube. Devolve (cliente_id,
    descrição) de quem ganhou link de entrada.

    A anuidade é escrita direto no retrato porque a lista simulada não traz
    esses campos -- é o mesmo lugar de onde o Portal lê em modo simulado."""
    import sqlite3
    from datetime import date, timedelta

    from core import motor_marketplace
    from core.motor_casos import criar_caso

    def dias(n):
        return (date.today() + timedelta(days=n)).isoformat()

    # (cpf, nome, situação da anuidade, validade, tem caso?, anúncio?, descrição)
    pessoas = [
        ("10000000006", "Helena Costa", "Sim", dias(240), None, None,
         "anuidade em dia (cartão verde, tudo liberado)"),
        ("10000000015", "William Cardoso", "Não", dias(-10), True, "Carabina .22 do William",
         "venceu há 10 dias, na carência (cartão âmbar, ainda tudo liberado)"),
        ("10000000020", "Larissa Barbosa", "Não", dias(-60), True, None,
         "passou da carência, mas é cliente do despachante (fica só com o dela)"),
        ("10000000014", "Vanessa Teixeira", "Não", dias(-60), False, "Pistola da Vanessa",
         "passou da carência e só era sócia (só o aviso de renovação)"),
    ]

    con = sqlite3.connect(os.environ["ERP_DOMAIN_DB"])
    for cpf, _nome, em_dia, validade, *_ in pessoas:
        con.execute(
            "UPDATE filiado SET anuidade_em_dia = ?, anuidade_validade = ? "
            "WHERE empresa_id = ? AND cpf = ?",
            (em_dia, validade, base.EMPRESA, cpf),
        )
    con.commit()
    con.close()

    links = [(CLIENTE_DEMO, pessoas[0][6])]
    for numero, (cpf, nome, _em_dia, _validade, tem_caso, anuncio, descricao) in enumerate(pessoas[1:], start=60):
        # Direto no banco, como base._criar_banco_core faz com a Helena: os
        # CPFs da lista simulada do clube não têm dígito verificador válido,
        # e criar_cliente (com razão) os recusaria.
        cliente_id = f"CLI-{numero:06d}"
        con = sqlite3.connect(os.environ["ERP_CORE_DB"])
        con.execute(
            "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, email, status, "
            "atendimento_ia, data_cadastro) VALUES (?,?,?,?,?,?,?,?)",
            (cliente_id, base.EMPRESA, nome, cpf, f"{nome.split()[0].lower()}@exemplo.local",
             "Ativo", "Sim", base.AGORA),
        )
        con.commit()
        con.close()
        if tem_caso:
            criar_caso(
                base.EMPRESA, cliente_id, titulo=f"Renovação de CR — {nome.split()[0]}",
                categoria="Regularização documental", origem="Painel",
                canal_origem="Presencial", criado_por="Demonstração",
            )
        if anuncio:
            anuncio_id = motor_marketplace.criar_anuncio(
                base.EMPRESA, cliente_id, categoria="Arma", titulo=anuncio,
                contato_telefone="(14) 99999-0000",
            )
            motor_marketplace.aprovar(base.EMPRESA, anuncio_id, revisado_por="Demonstração")
        links.append((cliente_id, f"{nome} -- {descricao}"))
    return links


CPF_HELENA = "10000000006"


def _habitualidade_da_helena(*_args, **_kwargs) -> dict:
    """Histórico inventado da Helena, com as MESMAS modalidades que o
    Shooting House manda de verdade (Treino, Arma Curta, Arma Longa,
    Provas Nacionais, Provas Especiais, Silhueta Metálica) -- a lista
    simulada da integração só tem "Tiro Prático", e a tabela por
    modalidade da tela de Habitualidade não tinha o que mostrar. Datas
    contadas a partir de hoje, para cair nos quatro períodos."""
    from datetime import date, timedelta

    # (dias atrás, modalidade, grupo, competição)
    registros = [
        (8, "Treino", "ACRR", "TREINO"), (21, "Treino", "ACRR", "TREINO"),
        (35, "Arma Curta", "ACRR", "Copa do Clube"), (35, "Arma Longa", "ALRP", "Copa do Clube"),
        (52, "Treino", "ACRR", "TREINO"), (70, "Provas Nacionais", "ACRR", "Prova Nacional"),
        (95, "Treino", "ACRR", "TREINO"), (110, "Silhueta Metálica", "ACRR", "Etapa Silhueta"),
        (110, "Silhueta Metálica", "ALRP", "Etapa Silhueta"), (150, "Treino", "ACRR", "TREINO"),
        (190, "Provas Especiais", "ACRR", "Prova Especial"), (190, "Provas Especiais", "ACRR", "Prova Especial"),
        (240, "Treino", "ACRR", "TREINO"), (300, "Treino", "ACRR", "TREINO"),
        (330, "Provas Nacionais", "ACRR", "Prova Nacional"), (420, "Arma Curta", "ACRR", "Copa do Clube"),
        (480, "Treino", "ACRR", "TREINO"), (560, "Provas Especiais", "ACRR", "Prova Especial"),
        (650, "Provas Nacionais", "ACRR", "Prova Nacional"), (800, "Treino", "ACRR", "TREINO"),
        (900, "Arma Longa", "ALRP", "Copa do Clube"), (1000, "Silhueta Metálica", "ACRR", "Etapa Silhueta"),
    ]
    grupos: dict = {}
    for dias, modalidade, grupo, competicao in registros:
        grupos.setdefault(grupo, {"eventos": []})["eventos"].append({
            "data_participacao": (date.today() - timedelta(days=dias)).strftime("%d/%m/%Y"),
            "hora_participacao": "10:00",
            "modalidade": modalidade,
            "competicao": competicao,
            "arma": "Pistola 9mm (exemplo)" if grupo == "ACRR" else "Carabina .22 (exemplo)",
            "local": "Estande do clube (exemplo)",
        })
    for dados in grupos.values():
        dados["count"] = len(dados["eventos"])
    return {"simulado": True, "habitualidades": grupos}


def main() -> None:
    base._criar_banco_core()
    base._criar_banco_dominio()
    base._popular_habitualidade()
    pessoas = _anuidades_de_exemplo()

    print()
    print("=" * 68)
    print("PORTAL DO CLIENTE -- demonstração, banco temporário")
    print("=" * 68)
    print("  Links de entrada (uso único, valem poucos minutos):")
    for cliente_id, descricao in pessoas:
        # Token de verdade, pelo mesmo motor que o e-mail usaria -- não um
        # atalho que pula a autenticação. Se o link mágico quebrar um dia,
        # esta demonstração quebra junto, que é o comportamento certo.
        token = criar_token(base.EMPRESA, cliente_id)
        print()
        print(f"  {descricao}")
        print(f"  http://127.0.0.1:{PORTA}/portal/entrar/{token}")
    print()
    print(f"  Helena tem 6 documentos no dossiê e um CRAF pronto (Despachante).")
    print(f"  Na vitrine da Helena aparece o anúncio do William; o da Vanessa")
    print(f"  está pausado pela anuidade (continua no banco, aprovado).")
    print(f"  Banco  : {base.PASTA}  (apagado ao fechar)")
    print("=" * 68)
    print()

    import portal.app as portal_app
    from portal.app import app

    # Só na demonstração e só para a Helena: as outras pessoas seguem no
    # simulado da integração, como sempre.
    consulta_original = portal_app.consultar_habitualidade

    def consultar_habitualidade_demo(cpf, *args, **kwargs):
        if cpf == CPF_HELENA:
            return _habitualidade_da_helena()
        return consulta_original(cpf, *args, **kwargs)

    portal_app.consultar_habitualidade = consultar_habitualidade_demo

    try:
        app.run(host="127.0.0.1", port=PORTA, debug=False, use_reloader=False)
    finally:
        import shutil

        shutil.rmtree(base.PASTA, ignore_errors=True)


if __name__ == "__main__":
    main()
