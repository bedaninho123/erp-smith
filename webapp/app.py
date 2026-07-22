"""Painel local para acompanhar o desenvolvimento do ERP Smith: status do
banco/módulos e um testador interativo do pipeline do Motor IA. Ferramenta
de desenvolvimento, não faz parte do ERP em si.
"""
import sqlite3
import subprocess
import traceback
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from motor_ia.atualizador_memoria import atualizar_memoria
from motor_ia.auditor import auditar
from motor_ia.classificador import classificar
from motor_ia.conexao import CORE_DB, DOMAIN_DB, conectar
from motor_ia.consultor import consultar
from motor_ia.identificador_cliente import identificar_cliente
from motor_ia.planejador import planejar
from motor_ia.redator import redigir

BASE_DIR = Path(__file__).resolve().parent.parent

MODULOS_MOTOR_IA = [
    ("Identificador de Cliente", "motor_ia/identificador_cliente.py"),
    ("Classificador", "motor_ia/classificador.py"),
    ("Planejador", "motor_ia/planejador.py"),
    ("Consultor", "motor_ia/consultor.py"),
    ("Montador de Contexto", "motor_ia/montador_contexto.py"),
    ("Redator", "motor_ia/redator.py"),
    ("Auditor", "motor_ia/auditor.py"),
    ("Atualizador de Memória", "motor_ia/atualizador_memoria.py"),
]

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    con = sqlite3.connect(CORE_DB)
    tabelas_core = [
        r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    tabelas = []
    for nome in tabelas_core:
        n = con.execute(f"SELECT COUNT(*) FROM {nome}").fetchone()[0]
        tabelas.append({"nome": nome, "linhas": n, "camada": "Core"})
    con.close()

    con_dom = sqlite3.connect(DOMAIN_DB)
    tabelas_dom = [
        r[0] for r in con_dom.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    for nome in tabelas_dom:
        n = con_dom.execute(f"SELECT COUNT(*) FROM {nome}").fetchone()[0]
        tabelas.append({"nome": nome, "linhas": n, "camada": "Domínio"})
    con_dom.close()

    log = subprocess.run(
        ["git", "log", "--pretty=format:%h|%ad|%s", "--date=format:%Y-%m-%d %H:%M"],
        cwd=BASE_DIR, capture_output=True, text=True, check=True,
    ).stdout.strip()
    commits = []
    if log:
        for linha in log.split("\n"):
            hash_, data, mensagem = linha.split("|", 2)
            commits.append({"hash": hash_, "data": data, "mensagem": mensagem})

    modulos = [
        {"nome": nome, "existe": (BASE_DIR / caminho).exists()}
        for nome, caminho in MODULOS_MOTOR_IA
    ]

    return jsonify(tabelas=tabelas, commits=commits, modulos=modulos)


@app.route("/api/clientes")
def clientes():
    con = sqlite3.connect(CORE_DB)
    linhas = con.execute(
        "SELECT cliente_id, nome FROM cliente ORDER BY nome"
    ).fetchall()
    con.close()
    return jsonify([{"cliente_id": r[0], "nome": r[1]} for r in linhas])


@app.route("/api/identificar_cliente", methods=["POST"])
def identificar():
    corpo = request.get_json(force=True)
    nome = (corpo.get("nome") or "").strip() or None
    cpf = (corpo.get("cpf") or "").strip() or None
    email = (corpo.get("email") or "").strip() or None

    if not (nome or cpf or email):
        return jsonify(erro="Informe nome, CPF ou e-mail."), 400

    cliente = identificar_cliente(nome=nome, cpf=cpf, email=email)
    if not cliente:
        return jsonify(encontrado=False), 200

    return jsonify(
        encontrado=True,
        cliente_id=cliente["cliente_id"],
        nome=cliente["nome"],
        cpf=cliente["cpf"],
        email=cliente["email"],
    )


@app.route("/api/pipeline", methods=["POST"])
def pipeline():
    corpo = request.get_json(force=True)
    mensagem = (corpo.get("mensagem") or "").strip()
    cliente_id = corpo.get("cliente_id")

    if not mensagem or not cliente_id:
        return jsonify(erro="Preencha a mensagem e escolha um cliente."), 400

    try:
        classificacao = classificar(mensagem)
        plano = planejar(classificacao)
        dados = consultar(plano, cliente_id=cliente_id, classificacao=classificacao)
        cliente_nome = (dados.get("cliente") or {}).get("nome", "Cliente")
        resposta = redigir(dados, cliente_nome=cliente_nome)
        resultado = auditar(resposta, dados, cliente_nome, plano)

        memoria_id = None
        if resultado.acao == "enviar":
            memoria_id = atualizar_memoria(cliente_id, classificacao, dados, resposta)
    except Exception as e:
        traceback.print_exc()
        return jsonify(erro=f"{type(e).__name__}: {e}"), 500

    return jsonify(
        classificacao=classificacao.model_dump(),
        plano={
            "rota": plano.rota,
            "fontes": plano.fontes,
            "encaminhar_humano": plano.encaminhar_humano,
            "motivo_humano": plano.motivo_humano,
        },
        dados=dados,
        resposta_gerada=resposta,
        auditoria=resultado.model_dump(),
        memoria_atualizada=memoria_id,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
