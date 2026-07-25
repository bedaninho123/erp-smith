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


def destinatario_para_notificar(caso_id: str) -> Optional[dict]:
    """Nome e e-mail do cliente dono do caso, só se a notificação estiver
    ligada em configuracoes e o cliente tiver e-mail cadastrado. Devolve
    None quando não deve notificar (não é erro -- e-mail é opcional no
    cadastro do cliente, ver docs/portal_cliente_arquitetura.md seção 2)."""
    config = obter_configuracoes()
    if config.get("notificar_cliente_mudanca_status") != "Sim":
        return None

    con = conectar()
    try:
        linha = con.execute(
            "SELECT cl.nome, cl.email FROM caso ca "
            "JOIN cliente cl ON cl.cliente_id = ca.cliente_id "
            "WHERE ca.caso_id = ?",
            (caso_id,),
        ).fetchone()
    finally:
        con.close()

    if not linha or not linha["email"]:
        return None
    return {"nome": linha["nome"], "email": linha["email"]}


if __name__ == "__main__":
    con = conectar()
    caso_id = con.execute("SELECT caso_id FROM caso LIMIT 1").fetchone()["caso_id"]
    con.close()
    print(f"Caso de teste: {caso_id}")
    print("Destinatário:", destinatario_para_notificar(caso_id))
