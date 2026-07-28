"""Decide SE e PARA QUEM notificar o cliente quando o status de um Caso
ou Processo muda -- regra de negócio pura (respeita
configuracoes.notificar_cliente_mudanca_status e exige e-mail
cadastrado), mas nunca manda o e-mail: Core não depende de Integrações
(mesma regra de core/motor_portal_auth.py). Quem manda é quem chama
este módulo (webapp/app.py), reaproveitando integracoes/gmail.py sem
modificar nada nela.

O e-mail em si é sempre genérico (nunca revela o novo status no corpo)
-- domínio regulado (documentação de arma de fogo), então o conteúdo
sensível só aparece depois do cliente logar no Portal.
"""
from typing import Optional

from core.conexao import conectar
from core.configuracoes import obter_configuracoes


def destinatario_para_notificar(empresa_id: str, caso_id: str) -> Optional[dict]:
    """Nome e e-mail do cliente dono do caso, só se a notificação estiver
    ligada em configuracoes e o cliente tiver e-mail cadastrado. Devolve
    None quando não deve notificar (não é erro -- e-mail é opcional no
    cadastro do cliente, ver docs/portal_cliente_arquitetura.md seção 2)."""
    config = obter_configuracoes(empresa_id)
    if config.get("notificar_cliente_mudanca_status") != "Sim":
        return None

    con = conectar(empresa_id)
    try:
        # Filtra os dois lados do JOIN: um caso_id de outra empresa não
        # pode devolver o e-mail do cliente dela.
        linha = con.execute(
            "SELECT cl.nome, cl.email FROM caso ca "
            "JOIN cliente cl ON cl.cliente_id = ca.cliente_id AND cl.empresa_id = ca.empresa_id "
            "WHERE ca.caso_id = ? AND ca.empresa_id = ?",
            (caso_id, empresa_id),
        ).fetchone()
    finally:
        con.close()

    if not linha or not linha["email"]:
        return None
    return {"nome": linha["nome"], "email": linha["email"]}


if __name__ == "__main__":
    EMPRESA = "EMP-000001"
    con = conectar(EMPRESA)
    caso_id = con.execute(
        "SELECT caso_id FROM caso WHERE empresa_id = ? LIMIT 1", (EMPRESA,)
    ).fetchone()["caso_id"]
    con.close()
    print(f"Caso de teste: {caso_id}")
    print("Destinatário:", destinatario_para_notificar(EMPRESA, caso_id))
