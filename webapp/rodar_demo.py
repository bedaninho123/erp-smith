"""Sobe o painel administrativo com um banco TEMPORÁRIO de gente
fictícia, sem tocar no banco real.

Para que serve: conferir uma tela nova (ou mostrar o sistema pra alguém)
sem abrir nome, CPF e documento de cliente de verdade na tela. É o mesmo
princípio de `integracoes/diagnostico_shooting_house.py` -- quando dá pra
trabalhar sem dado real, trabalha-se sem dado real.

    .venv\\Scripts\\python.exe -m webapp.rodar_demo

Sobe em http://127.0.0.1:5010 (porta diferente do painel de verdade, pros
dois poderem rodar ao mesmo tempo). Login e senha aparecem no console.

O banco nasce do zero a cada execução, a partir do schema REAL
(core/db/schema.sql), e é apagado ao fechar. Nada aqui escreve no
`core/db/erp_smith.db` nem no `.env`.
"""
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = Path(tempfile.mkdtemp(prefix="erp_smith_demo_"))

# --- antes de qualquer import do projeto: core/conexao.py e
# --- motor_ia/conexao.py leem estes caminhos uma vez, na importação.
os.environ["ERP_CORE_DB"] = str(PASTA / "core_demo.db")
os.environ["ERP_DOMAIN_DB"] = str(PASTA / "dominio_demo.db")
# Chaves de sessão próprias: sem isto o painel geraria uma chave nova e a
# gravaria no .env de verdade.
os.environ.setdefault("WEBAPP_SECRET_KEY", "chave-de-demonstracao-nao-usar-em-producao")
os.environ.setdefault("PORTAL_SECRET_KEY", "chave-de-demonstracao-nao-usar-em-producao")
# Integração externa desligada: a demonstração usa o modo simulado.
os.environ["SHOOTING_HOUSE_ATIVO"] = ""

from werkzeug.security import generate_password_hash  # noqa: E402

EMPRESA = "EMP-000001"
SENHA = "demo1234"
EMAIL_LOGIN = "gestor@demonstracao.local"
AGORA = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Pessoas inventadas. Os CPFs têm dígito verificador válido de propósito,
# senão o cadastro os recusaria (ver core/motor_clientes.py::cpf_valido).
#
# Nenhum deles é 529.982.247-25 de propósito: esse é o CPF que a busca
# simulada do Shooting House encontra, e precisa ficar LIVRE para o fluxo
# de cadastro novo poder ser percorrido inteiro. Usar o mesmo aqui faria
# a demonstração cair sempre em "já existe um cliente com este CPF".
CLIENTES_FICTICIOS = [
    # Helena tem o MESMO CPF de uma filiada ativa (ver _FILIADOS_TESTE em
    # integracoes/shooting_house.py): é ela que faz a ligação entre as
    # duas populações aparecer na demonstração -- some na lista de
    # Filiados com a etiqueta "cliente", e a ficha dela mostra o bloco
    # "no clube". Sem alguém nos dois lados, a funcionalidade existe mas
    # não dá pra ver.
    ("CLI-000001", "Helena Costa", "10000000006", "helena@exemplo.local", "(14) 99999-0001", "Marília"),
    # Ricardo é cliente do despachante e NUNCA passou pelo clube -- o
    # caso corriqueiro de quem só faz transferência de arma.
    ("CLI-000002", "Ricardo Exemplo", "11144477735", "ricardo@exemplo.local", "(14) 99999-0002", "Marília"),
]


def _criar_banco_core() -> None:
    con = sqlite3.connect(os.environ["ERP_CORE_DB"])
    con.row_factory = sqlite3.Row
    con.executescript((RAIZ / "core" / "db" / "schema.sql").read_text(encoding="utf-8"))
    con.executescript((RAIZ / "core" / "db" / "views.sql").read_text(encoding="utf-8"))

    con.execute(
        "INSERT INTO empresa (empresa_id, nome, dominio, ativo, criado_em) VALUES (?,?,?,?,?)",
        (EMPRESA, "Clube de Demonstração", "clube_tiro", "Sim", AGORA),
    )
    con.execute(
        "INSERT INTO servico (service_id, empresa_id, service_key, nome_servico, "
        "categoria, documentos_obrigatorios, ativo) VALUES (?,?,?,?,?,?,?)",
        ("SER-000001", EMPRESA, "transferencia_arma", "Transferência de Arma",
         "Transferência", "RG, CPF, CR", "Sim"),
    )
    con.execute(
        "INSERT INTO usuario (usuario_id, empresa_id, nome, email, papel, ativo, "
        "criado_em, senha_hash) VALUES (?,?,?,?,?,?,?,?)",
        ("USR-000001", EMPRESA, "Gestor de Demonstração", EMAIL_LOGIN, "Gestor",
         "Sim", AGORA, generate_password_hash(SENHA)),
    )
    for cliente_id, nome, cpf, email, telefone, cidade in CLIENTES_FICTICIOS:
        con.execute(
            "INSERT INTO cliente (cliente_id, empresa_id, nome, cpf, email, telefone, "
            "cidade, status, atendimento_ia, data_cadastro) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cliente_id, EMPRESA, nome, cpf, email, telefone, cidade, "Ativo", "Sim", AGORA),
        )
    # Um caso por cliente, e tarefas em três situações de prazo. Mesma
    # razão do _popular_habitualidade(): sem caso nenhum, as telas de
    # Casos e de Tarefas abrem vazias e não dá pra ver se funcionam --
    # e é justamente o prazo atrasado (vermelho) que precisa ser
    # conferido com o olho, não só com teste.
    for caso_id, cliente_id, titulo in [
        ("CAS-000001", "CLI-000001", "Transferência de arma — Helena"),
        ("CAS-000002", "CLI-000002", "Renovação de CR — Ricardo"),
    ]:
        con.execute(
            "INSERT INTO caso (caso_id, empresa_id, cliente_id, titulo, descricao, "
            "categoria, tipo_caso, origem, canal_origem, status, fase, prioridade, "
            "responsavel_id, criado_em, atualizado_em, criado_por, alterado_por, "
            "versao, ativo) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (caso_id, EMPRESA, cliente_id, titulo, "Caso de demonstração.",
             "Transferência", "Solicitação", "Atendimento", "Email", "Em andamento",
             "Triagem", "Normal", "USR-000001", AGORA, AGORA, "demonstração",
             "demonstração", 1, "Sim"),
        )
    con.commit()
    con.close()

    _criar_tarefas_demo()


def _criar_tarefas_demo() -> None:
    """Pelo motor, não por INSERT: é ele que decide cliente_id, status
    inicial e o registro no histórico do caso. Um INSERT à mão aqui
    mostraria uma tela que o sistema de verdade não produz."""
    from core.motor_tarefas import criar_tarefa

    hoje = datetime.now(timezone.utc).date()
    for caso_id, tipo, descricao, dias, prioridade in [
        ("CAS-000001", "Cobrar documento",
         "Solicitar comprovante de residência atualizado.", -4, "Alta"),
        ("CAS-000001", "Consultar andamento",
         "Verificar protocolo no órgão responsável.", 0, "Normal"),
        ("CAS-000002", "Ligar para o cliente",
         "Confirmar a data da renovação com o Ricardo.", 6, "Normal"),
        ("CAS-000002", "Conferir documento", None, None, "Baixa"),
    ]:
        criar_tarefa(
            EMPRESA, caso_id, tipo=tipo, descricao=descricao,
            prazo=(hoje + timedelta(days=dias)).isoformat() if dias is not None else None,
            prioridade=prioridade, responsavel_id="USR-000001",
            criado_por="demonstração",
        )


def _criar_banco_dominio() -> None:
    """O banco de Domínio é anexado pelo motor_ia/conexao.py. Sem ele o
    SQLite criaria um arquivo vazio e qualquer consulta a `dominio.*`
    quebraria."""
    schema = RAIZ / "domain" / "clube_tiro" / "db" / "schema.sql"
    if not schema.exists():
        return
    con = sqlite3.connect(os.environ["ERP_DOMAIN_DB"])
    con.executescript(schema.read_text(encoding="utf-8"))
    con.commit()
    con.close()


def _popular_habitualidade() -> None:
    """Roda a sincronização em modo simulado, para a tela de Habitualidade
    nascer com dado variado -- gente em dia, irregular e sem registro. Sem
    isto ela abriria vazia e não daria pra ver se funciona."""
    from domain.clube_tiro.sincronizar_habitualidade import sincronizar

    saida = sincronizar(EMPRESA, limite=50)
    hab = saida.get("habitualidade") or {}
    print(f"  Filiados sincronizados: {saida['lista']['total']} "
          f"(habitualidade consultada: {hab.get('consultados', 0)})")


def main() -> None:
    _criar_banco_core()
    _criar_banco_dominio()
    _popular_habitualidade()

    print()
    print("=" * 60)
    print("PAINEL DE DEMONSTRAÇÃO -- banco temporário, gente fictícia")
    print("=" * 60)
    print(f"  Endereço : http://127.0.0.1:5010")
    print(f"  Login    : {EMAIL_LOGIN}")
    print(f"  Senha    : {SENHA}")
    print(f"  Banco    : {PASTA}  (apagado ao fechar)")
    print()
    print("  Shooting House em modo SIMULADO. CPFs que a busca encontra:")
    print("    529.982.247-25  -> percorre o fluxo inteiro")
    print("    123.456.789-00  -> achado, mas recusado ao salvar (dígito inválido)")
    print("=" * 60)
    print()

    from webapp.app import app

    try:
        app.run(host="127.0.0.1", port=5010, debug=False, use_reloader=False)
    finally:
        shutil.rmtree(PASTA, ignore_errors=True)


if __name__ == "__main__":
    main()
