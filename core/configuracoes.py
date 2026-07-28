"""Acesso de leitura à tabela configuracoes do Core.

As configurações são por empresa (docs/schema_multi_tenant.md §3):
nome_empresa, telefone, horário de atendimento, assinatura de e-mail e
até revisao_humana_ativa -- uma empresa pode querer o freio de revisão
ligado e outra não.
"""
from core.conexao import conectar


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
