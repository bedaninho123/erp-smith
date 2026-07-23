"""Orquestra o fluxo real de atendimento descrito no PROJETO_1.md (seção
6): identificar cliente -> localizar/criar sessão -> classificar ->
planejar -> localizar/criar caso -> consultar -> redigir -> auditar ->
(se aprovado) atualizar sessão + memória. Este módulo não decide regra
de negócio -- só chama, na ordem certa, os módulos que já decidem cada
parte.

Gap conhecido: ainda não registra em log_ia (auditoria técnica de cada
chamada à OpenAI) -- os módulos individuais não expõem tokens/custo de
forma fácil de propagar ainda. Fica para uma próxima rodada.
"""
from typing import Optional

from core.conexao import conectar
from core.motor_casos import localizar_ou_criar_caso
from core.motor_sessoes import atualizar_sessao, localizar_ou_criar_sessao
from motor_ia.atualizador_memoria import atualizar_memoria
from motor_ia.auditor import auditar
from motor_ia.classificador import ResultadoClassificacao, classificar
from motor_ia.consultor import consultar
from motor_ia.identificador_cliente import identificar_cliente
from motor_ia.planejador import planejar
from motor_ia.redator import redigir

_CATEGORIA_POR_INTENCAO = {
    "CONSULTA_HABITUALIDADE": "Habitualidade",
    "CONSULTA_CLIENTE": "Consulta",
    "ATENDIMENTO_GERAL": "Consulta",
    "ATENDIMENTO_HUMANO": "Consulta",
    "CONSULTA_PROCESSO": "Consulta",
}


def _categoria_do_caso(classificacao: ResultadoClassificacao) -> str:
    if classificacao.servico_mencionado:
        con = conectar()
        try:
            linha = con.execute(
                "SELECT categoria FROM servico WHERE nome_servico = ? AND ativo = 'Sim'",
                (classificacao.servico_mencionado,),
            ).fetchone()
            if linha:
                return linha["categoria"]
        finally:
            con.close()
    return _CATEGORIA_POR_INTENCAO.get(classificacao.intencao, "Outros")


def atender_mensagem(
    mensagem: str,
    canal: str = "Email",
    identificador_canal: Optional[str] = None,
    cliente_id: Optional[str] = None,
    nome: Optional[str] = None,
    cpf: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    if not cliente_id:
        cliente = identificar_cliente(nome=nome, cpf=cpf, email=email)
        if not cliente:
            return {"erro": "Cliente não identificado com os dados informados."}
        cliente_id = cliente["cliente_id"]

    sessao_id = localizar_ou_criar_sessao(cliente_id, canal, identificador_canal)

    classificacao = classificar(mensagem)
    plano = planejar(classificacao)

    caso_id = None
    if not plano.encaminhar_humano:
        categoria = _categoria_do_caso(classificacao)
        caso_id = localizar_ou_criar_caso(
            cliente_id, titulo=classificacao.resumo[:120], categoria=categoria,
            canal_origem=canal,
        )

    dados = consultar(plano, cliente_id=cliente_id, classificacao=classificacao)
    cliente_nome = (dados.get("cliente") or {}).get("nome", "Cliente")
    resposta = redigir(dados, cliente_nome=cliente_nome)
    resultado_auditoria = auditar(resposta, dados, cliente_nome, plano)

    memoria_id = None
    if resultado_auditoria.acao == "enviar":
        atualizar_sessao(
            sessao_id,
            caso_id=caso_id,
            ultima_intencao=classificacao.intencao,
            ultima_mensagem_cliente=mensagem,
            ultima_resposta_ia=resposta,
            resumo_sessao=classificacao.resumo,
        )
        memoria_id = atualizar_memoria(cliente_id, classificacao, dados, resposta)

    return {
        "cliente_id": cliente_id,
        "sessao_id": sessao_id,
        "caso_id": caso_id,
        "classificacao": classificacao,
        "plano": plano,
        "dados": dados,
        "resposta": resposta,
        "auditoria": resultado_auditoria,
        "memoria_id": memoria_id,
    }


if __name__ == "__main__":
    resultado = atender_mensagem(
        "Quais documentos preciso para transferir uma arma?",
        cliente_id="CLI-000002",
        canal="Email",
        identificador_canal="joao.teste@example.com",
    )
    print(f"Cliente: {resultado['cliente_id']}")
    print(f"Sessão: {resultado['sessao_id']}")
    print(f"Caso: {resultado['caso_id']}")
    print(f"Intenção: {resultado['classificacao'].intencao}")
    print(f"Auditoria: {resultado['auditoria'].acao}")
    print(f"Memória: {resultado['memoria_id']}")
    print()
    print(resultado["resposta"])
