"""Orquestra o fluxo real de atendimento descrito no PROJETO_1.md (seção
6): identificar cliente -> localizar/criar sessão -> classificar ->
planejar -> localizar/criar caso -> consultar -> redigir -> auditar ->
(se aprovado) atualizar sessão + memória. Este módulo não decide regra
de negócio -- só chama, na ordem certa, os módulos que já decidem cada
parte.

Remetente não identificado como cliente NÃO é mais motivo para não
responder nada (bug real encontrado em teste: alguém de fora perguntou
o horário e não recebeu resposta nenhuma). Perguntas que não exigem
saber quem está perguntando (ATENDIMENTO_GERAL, CONSULTA_DOCUMENTOS)
são respondidas normalmente, sem sessão/caso/memória (essas exigem
cliente_id no banco). Perguntas que exigem identidade (CONSULTA_PROCESSO,
CONSULTA_CLIENTE, CONSULTA_HABITUALIDADE) recebem a mensagem
institucional pedindo CPF, em vez de silêncio.
"""
from typing import Optional

from core.conexao import conectar
from core.configuracoes import obter_configuracoes
from core.motor_casos import localizar_ou_criar_caso
from core.motor_sessoes import atualizar_sessao, localizar_ou_criar_sessao
from motor_ia.atualizador_memoria import atualizar_memoria
from motor_ia.auditor import ResultadoAuditoria, auditar
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

# Intenções que só fazem sentido responder sabendo quem é o cliente --
# sem isso, o Consultor não teria o que buscar (processo/cadastro/
# habitualidade são sempre de alguém específico).
_INTENCOES_QUE_EXIGEM_CADASTRO = {
    "CONSULTA_PROCESSO", "CONSULTA_CLIENTE", "CONSULTA_HABITUALIDADE",
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
        if cliente:
            cliente_id = cliente["cliente_id"]

    classificacao = classificar(mensagem)
    plano = planejar(classificacao)

    if not cliente_id and classificacao.intencao in _INTENCOES_QUE_EXIGEM_CADASTRO:
        # Não dá pra consultar processo/cadastro/habitualidade de
        # ninguém específico -- responde pedindo identificação em vez
        # de ficar em silêncio ou inventar que "não encontrou nada".
        config = obter_configuracoes()
        return {
            "cliente_id": None,
            "sessao_id": None,
            "caso_id": None,
            "classificacao": classificacao,
            "plano": plano,
            "dados": {},
            "resposta": config.get(
                "mensagem_cliente_nao_encontrado",
                "Não localizamos seu cadastro. Poderia nos informar seu CPF?",
            ),
            "auditoria": ResultadoAuditoria(
                aprovado=True, acao="enviar",
                motivo="Remetente não identificado como cliente cadastrado.",
            ),
            "memoria_id": None,
        }

    sessao_id = (
        localizar_ou_criar_sessao(cliente_id, canal, identificador_canal)
        if cliente_id else None
    )

    caso_id = None
    if cliente_id and not plano.encaminhar_humano:
        categoria = _categoria_do_caso(classificacao)
        caso_id = localizar_ou_criar_caso(
            cliente_id, titulo=classificacao.resumo[:120], categoria=categoria,
            canal_origem=canal,
        )

    dados = consultar(plano, cliente_id=cliente_id, classificacao=classificacao)
    cliente_nome = (dados.get("cliente") or {}).get("nome") or (nome or "Cliente")
    resposta = redigir(dados, cliente_nome=cliente_nome, caso_id=caso_id, sessao_id=sessao_id)
    resultado_auditoria = auditar(
        resposta, dados, cliente_nome, plano, caso_id=caso_id, sessao_id=sessao_id
    )

    memoria_id = None
    if cliente_id and resultado_auditoria.acao == "enviar":
        atualizar_sessao(
            sessao_id,
            caso_id=caso_id,
            ultima_intencao=classificacao.intencao,
            ultima_mensagem_cliente=mensagem,
            ultima_resposta_ia=resposta,
            resumo_sessao=classificacao.resumo,
        )
        memoria_id = atualizar_memoria(
            cliente_id, classificacao, dados, resposta,
            caso_id=caso_id, sessao_id=sessao_id,
        )

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
