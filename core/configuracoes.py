"""Acesso à tabela configuracoes do Core.

As configurações são por empresa (docs/schema_multi_tenant.md §3):
nome_empresa, telefone, horário de atendimento, assinatura de e-mail e
até revisao_humana_ativa -- uma empresa pode querer o freio de revisão
ligado e outra não.
"""
from core.conexao import conectar
from core.motor_log_administrativo import registrar as registrar_log

# Subconjunto de `configuracoes` seguro para entrar numa resposta ao
# cliente (motor_ia/consultor.py, intenção ATENDIMENTO_GERAL) -- rótulo
# amigável, não a chave crua. `obter_configuracoes()` devolve a tabela
# inteira, que também guarda ajuste interno de IA (modelo_openai,
# temperatura_ia) e o próprio freio de revisão humana
# (revisao_humana_ativa); nunca usar aquela função direto pra isso.
# Achado em 2026-09-23: pergunta de cliente sobre horário de
# funcionamento caía num rascunho genérico porque nada buscava esse
# fato -- o Classificador de propósito não tenta adivinhar esse tipo de
# pergunta (motor_ia/prompts/classificador.md), e sem fato nenhum o
# Redator não tem o que responder.
CHAVES_INSTITUCIONAIS = {
    "nome_empresa": "Nome",
    "cidade": "Cidade",
    "estado": "Estado",
    "endereco": "Endereço",
    "telefone": "Telefone",
    "whatsapp": "WhatsApp",
    "email_atendimento": "E-mail",
    "site_clube": "Site do clube",
    "site_loja": "Site da loja",
    "instagram": "Instagram",
    "horario_semana": "Horário (terça a sexta)",
    "horario_sabado": "Horário de sábado",
    "horario_domingo": "Horário de domingo",
    "primeira_visita": "Primeira visita",
    "processo_filiacao": "Como se filiar",
    "valor_anuidade": "Valor da anuidade",
    "formas_pagamento": "Formas de pagamento aceitas",
    "estrutura_clube": "Estrutura do clube",
    "estacionamento": "Estacionamento",
}


def obter_informacoes_institucionais(empresa_id: str) -> dict:
    """Rótulo amigável -> valor, só das chaves em CHAVES_INSTITUCIONAIS
    e só as que a empresa preencheu (chave ausente ou vazia não entra --
    nunca afirmar 'Endereço: ' em branco)."""
    todas = obter_configuracoes(empresa_id)
    return {
        rotulo: todas[chave]
        for chave, rotulo in CHAVES_INSTITUCIONAIS.items()
        if todas.get(chave)
    }


def obter_configuracoes(empresa_id: str) -> dict:
    con = conectar(empresa_id)
    try:
        return {
            r[0]: r[1]
            for r in con.execute(
                "SELECT chave, valor FROM configuracoes "
                "WHERE empresa_id = ? AND ativo = 'Sim'",
                (empresa_id,),
            )
        }
    finally:
        con.close()


def atualizar_configuracao(
    empresa_id: str, config_id: str, valor: str, ativo: str,
    alterado_por: str = "Painel administrativo",
) -> None:
    """Valida e grava, e registra no log administrativo quando o valor
    ou o 'ativo' realmente mudou -- inclui revisao_humana_ativa, o freio
    que faz a IA parar de enviar resposta sozinha. Antes desta mudança
    (auditoria de riscos, 2026-07-30), essa configuração podia ser
    desligada sem deixar rastro nenhum de quem ou quando."""
    valor = (valor or "").strip()
    if not valor:
        raise ValueError("O valor não pode ficar vazio.")
    if ativo not in ("Sim", "Não"):
        raise ValueError("Campo 'ativo' inválido.")

    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT chave, valor, ativo FROM configuracoes WHERE config_id = ? AND empresa_id = ?",
            (config_id, empresa_id),
        ).fetchone()
        if not linha:
            raise ValueError(f"Configuração não encontrada: {config_id}")
        chave, valor_antigo, ativo_antigo = linha["chave"], linha["valor"], linha["ativo"]

        con.execute(
            "UPDATE configuracoes SET valor = ?, ativo = ? WHERE config_id = ? AND empresa_id = ?",
            (valor, ativo, config_id, empresa_id),
        )
        if valor_antigo != valor or ativo_antigo != ativo:
            registrar_log(
                con, empresa_id, "configuracao_alterada", config_id,
                f"Configuração '{chave}' alterada",
                f"{valor_antigo} ({ativo_antigo})", f"{valor} ({ativo})", alterado_por,
            )
        con.commit()
    finally:
        con.close()
