"""Acesso à tabela configuracoes do Core.

As configurações são por empresa (docs/schema_multi_tenant.md §3):
nome_empresa, telefone, horário de atendimento, assinatura de e-mail e
até revisao_humana_ativa -- uma empresa pode querer o freio de revisão
ligado e outra não.
"""
from core.conexao import conectar
from core.motor_log_administrativo import registrar as registrar_log


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
