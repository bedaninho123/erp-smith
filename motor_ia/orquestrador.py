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
import traceback
from typing import Optional

from core import motor_identidade, motor_log_administrativo
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
    "CONSULTA_CR": "Consulta",
    "CONSULTA_CLIENTE": "Consulta",
    "ATENDIMENTO_GERAL": "Consulta",
    "ATENDIMENTO_HUMANO": "Consulta",
    "CONSULTA_PROCESSO": "Consulta",
    "CONSULTA_DOCUMENTOS_VENCIMENTO": "Consulta",
}

# Intenções que só fazem sentido responder sabendo quem é o cliente --
# sem isso, o Consultor não teria o que buscar (processo/cadastro/
# habitualidade/CR/documento de arma são sempre de alguém específico).
_INTENCOES_QUE_EXIGEM_CADASTRO = {
    "CONSULTA_PROCESSO", "CONSULTA_CLIENTE", "CONSULTA_HABITUALIDADE", "CONSULTA_CR",
    "CONSULTA_DOCUMENTOS_VENCIMENTO",
}


def _categoria_do_caso(empresa_id: str, classificacao: ResultadoClassificacao) -> str:
    if classificacao.servico_mencionado:
        con = conectar(empresa_id)
        try:
            linha = con.execute(
                "SELECT categoria FROM servico WHERE nome_servico = ? "
                "AND empresa_id = ? AND ativo = 'Sim'",
                (classificacao.servico_mencionado, empresa_id),
            ).fetchone()
            if linha:
                return linha["categoria"]
        finally:
            con.close()
    return _CATEGORIA_POR_INTENCAO.get(classificacao.intencao, "Outros")


def _cpf_do_cliente(empresa_id: str, cliente_id: str) -> Optional[str]:
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT cpf FROM cliente WHERE empresa_id = ? AND cliente_id = ?",
            (empresa_id, cliente_id),
        ).fetchone()
        return linha["cpf"] if linha else None
    finally:
        con.close()


def _registrar_acesso_sensivel(
    empresa_id: str, cliente_id: str, intencao: str, canal: str,
    liberado: bool, motivo: Optional[str],
) -> None:
    """Deixa rastro de toda vez que alguém pede dado de arma/CR/
    habitualidade por um canal não autenticado -- liberado ou negado.

    Sem isso, a pergunta "quem consultou o dado de arma de fulano, e
    quando?" não teria resposta nenhuma, que é exatamente a pergunta que
    aparece quando algo dá errado com dado pessoal de terceiros. Uma
    sequência de acessos NEGADOS ao mesmo cliente também é o sinal mais
    visível de alguém tentando adivinhar CPF.

    Falhar aqui não pode derrubar o atendimento (mesmo critério já usado
    para o envelope de conversa em atendimento/processar.py), mas também
    não passa calado: imprime o erro."""
    try:
        con = conectar(empresa_id)
        try:
            motor_log_administrativo.registrar(
                con, empresa_id,
                tipo_evento="ACESSO_DADO_SENSIVEL",
                alvo=cliente_id,
                descricao=f"{intencao} por {canal}",
                valor_anterior=None,
                valor_novo="liberado" if liberado else f"negado: {motivo}",
                criado_por="sistema/atendimento",
            )
            con.commit()
        finally:
            con.close()
    except Exception:
        print("[AVISO] Falha ao registrar acesso a dado sensível no log administrativo:")
        traceback.print_exc()


def atender_mensagem(
    empresa_id: str,
    mensagem: str,
    canal: str = "Email",
    identificador_canal: Optional[str] = None,
    cliente_id: Optional[str] = None,
    nome: Optional[str] = None,
    cpf: Optional[str] = None,
    email: Optional[str] = None,
    telefone: Optional[str] = None,
) -> dict:
    """empresa_id é o primeiro parâmetro de propósito: tudo daqui pra
    frente (identificação do cliente, consulta, memória) acontece dentro
    de uma empresa só. Quem chama é o canal de entrada, que sabe por qual
    caixa de e-mail/portal a mensagem chegou."""
    cliente = None
    if not cliente_id:
        cliente = identificar_cliente(
            empresa_id, nome=nome, cpf=cpf, email=email, telefone=telefone
        )
        if cliente:
            cliente_id = cliente["cliente_id"]

    # Os CPFs saem do texto AQUI, em Python, e é esta lista que o portão
    # de identidade usa lá embaixo -- nunca `classificacao.cpf_mencionado`,
    # que é produzido pela IA a partir da mesma mensagem que um atacante
    # escreve (ver core/motor_identidade.py::extrair_cpfs).
    cpfs_na_mensagem = motor_identidade.extrair_cpfs(mensagem)
    if cpf:
        # Veio do corpo do POST no webhook, que é autenticado por segredo
        # compartilhado -- entra como mais um candidato, não substitui.
        cpfs_na_mensagem.append(cpf)

    # O Classificador só precisa entender a INTENÇÃO da frase; o número
    # em si não ajuda em nada e é dado pessoal atravessando a rede até um
    # serviço de terceiro. O texto original segue inteiro para `mensagem`,
    # sessão e memória -- o banco é nosso.
    classificacao = classificar(empresa_id, motor_identidade.mascarar_cpfs_no_texto(mensagem))
    plano = planejar(classificacao)

    # PORTÃO DE IDENTIDADE (2026-08-25, ver core/motor_identidade.py).
    # Antes de consultar qualquer coisa sobre arma, CR ou habitualidade:
    # o e-mail/telefone do remetente diz apenas de onde a mensagem veio,
    # não quem a escreveu, e cabeçalho de e-mail se falsifica em um
    # minuto. Para esse tipo de dado, exige-se o CPF escrito na própria
    # mensagem, conferindo com o cadastro.
    #
    # Vem antes do Consultor de propósito: assim o CPF de quem não passou
    # no portão nem chega a ser enviado para a API do Shooting House.
    if cliente_id and motor_identidade.exige_confirmacao_cpf(classificacao.intencao, canal):
        cpf_cadastro = (cliente or {}).get("cpf") or _cpf_do_cliente(empresa_id, cliente_id)
        veredito = motor_identidade.verificar_acesso_dado_sensivel(
            classificacao.intencao, canal,
            cpfs_mencionados=cpfs_na_mensagem,
            cpf_cadastro=cpf_cadastro,
            # None quando quem chamou já entregou o cliente_id pronto (o
            # painel, os testes) -- aí a identificação não passou por
            # aqui e não há origem duvidosa a barrar.
            identificado_por=(cliente or {}).get("identificado_por"),
        )
        _registrar_acesso_sensivel(
            empresa_id, cliente_id, classificacao.intencao, canal,
            veredito.liberado, veredito.motivo,
        )
        if not veredito.liberado:
            config = obter_configuracoes(empresa_id)
            return {
                "empresa_id": empresa_id,
                "cliente_id": cliente_id,
                "sessao_id": None,
                "caso_id": None,
                "classificacao": classificacao,
                "plano": plano,
                "dados": {},
                # Mensagem fixa e institucional, igual pra todos os motivos
                # de recusa -- ver o comentário em
                # verificar_acesso_dado_sensivel sobre por que ela não conta
                # qual dos casos aconteceu.
                "resposta": config.get(
                    "mensagem_confirmar_cpf",
                    "Para sua segurança, informações sobre registro de arma, CR e "
                    "habitualidade só são enviadas mediante confirmação de "
                    "identidade. Por favor, responda esta mensagem informando o "
                    "seu CPF completo.",
                ),
                "auditoria": ResultadoAuditoria(
                    aprovado=True, acao="enviar",
                    motivo=f"Confirmação de identidade exigida: {veredito.motivo}",
                ),
                "memoria_id": None,
            }

    if not cliente_id and classificacao.intencao in _INTENCOES_QUE_EXIGEM_CADASTRO:
        # Não dá pra consultar processo/cadastro/habitualidade de
        # ninguém específico -- responde pedindo identificação em vez
        # de ficar em silêncio ou inventar que "não encontrou nada".
        config = obter_configuracoes(empresa_id)
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
        localizar_ou_criar_sessao(empresa_id, cliente_id, canal, identificador_canal)
        if cliente_id else None
    )

    caso_id = None
    if cliente_id and not plano.encaminhar_humano:
        categoria = _categoria_do_caso(empresa_id, classificacao)
        caso_id = localizar_ou_criar_caso(
            empresa_id, cliente_id, titulo=classificacao.resumo[:120], categoria=categoria,
            canal_origem=canal, descricao=classificacao.resumo,
        )

    dados = consultar(plano, empresa_id=empresa_id, cliente_id=cliente_id, classificacao=classificacao)
    cliente_nome = (dados.get("cliente") or {}).get("nome") or (nome or "Cliente")
    resposta = redigir(
        empresa_id, dados, cliente_nome=cliente_nome, caso_id=caso_id, sessao_id=sessao_id
    )
    resultado_auditoria = auditar(
        empresa_id, resposta, dados, cliente_nome, plano, caso_id=caso_id, sessao_id=sessao_id
    )

    memoria_id = None
    if cliente_id and resultado_auditoria.acao == "enviar":
        atualizar_sessao(
            empresa_id,
            sessao_id,
            caso_id=caso_id,
            ultima_intencao=classificacao.intencao,
            ultima_mensagem_cliente=mensagem,
            ultima_resposta_ia=resposta,
            resumo_sessao=classificacao.resumo,
        )
        memoria_id = atualizar_memoria(
            empresa_id, cliente_id, classificacao, dados, resposta,
            caso_id=caso_id, sessao_id=sessao_id,
        )

    return {
        "empresa_id": empresa_id,
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
        "EMP-000001",
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
