"""Motor de Usuários: cria e administra o acesso dos usuários do painel de
uma empresa. Papéis e permissões de verdade (2026-07-29): dois papéis,
Gestor (acesso total) e Atendente (opera casos/clientes/documentos, sem
acesso administrativo) -- validado aqui, não por CHECK no schema, mesmo
padrão do status do Caso em core/motor_casos.py.

Este módulo nunca define senha -- isso continua exclusivo de
webapp/definir_senha.py, rodado interativamente pelo próprio usuário
(CLAUDE.md). Usuário criado aqui nasce com senha_hash=NULL, "login ainda
não configurado".

Permissões granulares (2026-07-30): Gestor tem acesso total e intocável,
sempre -- as funções abaixo só têm efeito para quem é Atendente. Sem
seed automático: ausência de linha em usuario_permissao significa
"permitido" (mesmo espírito de core/db/migrar_papeis_usuario.py -- ninguém
perde acesso por falta de linha no banco). Só existe linha quando o
Gestor mexeu explicitamente naquela função pela tela de Usuários.
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar
from core.motor_log_administrativo import registrar as registrar_log

PAPEIS_VALIDOS = ("Gestor", "Atendente")

FUNCOES_VALIDAS = {
    "atendimentos": "Atendimentos (CRM)",
    "casos": "Casos",
    "clientes": "Clientes",
    "aprovacoes_pendentes": "Aprovações Pendentes",
    "documentos_aprovar": "Documentos a Aprovar",
    "campeonatos": "Campeonatos",
    "resultados": "Resultados",
    "testar_pipeline": "Testar Pipeline",
    "status_projeto": "Status do Projeto",
}


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _proximo_id(con, tabela: str, coluna_id: str, prefixo: str) -> str:
    maior = con.execute(
        f"SELECT MAX(CAST(SUBSTR({coluna_id}, {len(prefixo) + 2}) AS INTEGER)) FROM {tabela}"
    ).fetchone()[0] or 0
    return f"{prefixo}-{maior + 1:06d}"


def listar_usuarios(empresa_id: str) -> list[dict]:
    """Todos os usuários da empresa, incluindo inativos -- o Gestor
    precisa enxergar quem está desativado para poder reativar."""
    con = conectar(empresa_id)
    try:
        linhas = con.execute(
            "SELECT usuario_id, nome, email, papel, ativo, criado_em, "
            "(senha_hash IS NOT NULL) AS login_configurado "
            "FROM usuario WHERE empresa_id = ? ORDER BY nome",
            (empresa_id,),
        ).fetchall()
        return [dict(l) for l in linhas]
    finally:
        con.close()


def criar_usuario(empresa_id: str, nome: str, email: str, papel: str) -> dict:
    nome = (nome or "").strip()
    email = (email or "").strip().lower()
    if not nome:
        raise ValueError("Nome é obrigatório.")
    if not email or "@" not in email:
        raise ValueError("E-mail inválido.")
    if papel not in PAPEIS_VALIDOS:
        raise ValueError(f"Papel inválido: {papel}. Use um de {PAPEIS_VALIDOS}.")

    con = conectar(empresa_id)
    try:
        existe = con.execute(
            "SELECT 1 FROM usuario WHERE empresa_id = ? AND lower(email) = ?",
            (empresa_id, email),
        ).fetchone()
        if existe:
            raise ValueError(f"Já existe um usuário com o e-mail {email} nesta empresa.")

        novo_id = _proximo_id(con, "usuario", "usuario_id", "USR")
        con.execute(
            "INSERT INTO usuario (usuario_id, empresa_id, nome, email, papel, ativo, criado_em) "
            "VALUES (?,?,?,?,?,'Sim',?)",
            (novo_id, empresa_id, nome, email, papel, _agora_iso()),
        )
        con.commit()
        return {"usuario_id": novo_id, "nome": nome, "email": email, "papel": papel, "ativo": "Sim"}
    finally:
        con.close()


def _usuario_da_empresa(con, empresa_id: str, usuario_id: str) -> None:
    existe = con.execute(
        "SELECT 1 FROM usuario WHERE usuario_id = ? AND empresa_id = ?",
        (usuario_id, empresa_id),
    ).fetchone()
    if not existe:
        raise ValueError(f"Usuário não encontrado: {usuario_id}")


def atualizar_papel(
    empresa_id: str, usuario_id: str, novo_papel: str,
    alterado_por: str = "Painel administrativo",
) -> None:
    if novo_papel not in PAPEIS_VALIDOS:
        raise ValueError(f"Papel inválido: {novo_papel}. Use um de {PAPEIS_VALIDOS}.")
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT papel FROM usuario WHERE usuario_id = ? AND empresa_id = ?",
            (usuario_id, empresa_id),
        ).fetchone()
        if not linha:
            raise ValueError(f"Usuário não encontrado: {usuario_id}")
        papel_antigo = linha["papel"]

        con.execute(
            "UPDATE usuario SET papel = ? WHERE usuario_id = ? AND empresa_id = ?",
            (novo_papel, usuario_id, empresa_id),
        )
        if papel_antigo != novo_papel:
            registrar_log(
                con, empresa_id, "papel_alterado", usuario_id,
                f"Papel alterado de {papel_antigo} para {novo_papel}",
                papel_antigo, novo_papel, alterado_por,
            )
        con.commit()
    finally:
        con.close()


def atualizar_ativo(
    empresa_id: str, usuario_id: str, ativo: str,
    alterado_por: str = "Painel administrativo",
) -> None:
    if ativo not in ("Sim", "Não"):
        raise ValueError("Campo 'ativo' inválido.")
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT ativo FROM usuario WHERE usuario_id = ? AND empresa_id = ?",
            (usuario_id, empresa_id),
        ).fetchone()
        if not linha:
            raise ValueError(f"Usuário não encontrado: {usuario_id}")
        ativo_antigo = linha["ativo"]

        con.execute(
            "UPDATE usuario SET ativo = ? WHERE usuario_id = ? AND empresa_id = ?",
            (ativo, usuario_id, empresa_id),
        )
        if ativo_antigo != ativo:
            registrar_log(
                con, empresa_id, "ativo_alterado", usuario_id,
                f"Ativo alterado de {ativo_antigo} para {ativo}",
                ativo_antigo, ativo, alterado_por,
            )
        con.commit()
    finally:
        con.close()


def tem_permissao(empresa_id: str, usuario_id: str, funcao: str) -> bool:
    """Usada pelo decorator funcao_required (webapp/app.py). Sem linha
    pra essa função = permitido -- é o padrão seguro (ver docstring do
    módulo)."""
    con = conectar(empresa_id)
    try:
        linha = con.execute(
            "SELECT ativo FROM usuario_permissao "
            "WHERE usuario_id = ? AND empresa_id = ? AND funcao = ?",
            (usuario_id, empresa_id, funcao),
        ).fetchone()
        return linha is None or linha["ativo"] == "Sim"
    finally:
        con.close()


def listar_permissoes(empresa_id: str, usuario_id: str) -> list[dict]:
    """As 8 funções do catálogo, com o estado de cada uma -- 'Sim' por
    padrão quando não há linha, para a tela de Usuários sempre ter algo
    concreto pra mostrar em cada toggle."""
    con = conectar(empresa_id)
    try:
        linhas = {
            l["funcao"]: l["ativo"]
            for l in con.execute(
                "SELECT funcao, ativo FROM usuario_permissao "
                "WHERE usuario_id = ? AND empresa_id = ?",
                (usuario_id, empresa_id),
            ).fetchall()
        }
        return [
            {"funcao": chave, "nome": nome, "ativo": linhas.get(chave, "Sim")}
            for chave, nome in FUNCOES_VALIDAS.items()
        ]
    finally:
        con.close()


def atualizar_permissoes(
    empresa_id: str, usuario_id: str, mapa: dict[str, str],
    alterado_por: str = "Painel administrativo",
) -> None:
    for funcao, ativo in mapa.items():
        if funcao not in FUNCOES_VALIDAS:
            raise ValueError(f"Função inválida: {funcao}.")
        if ativo not in ("Sim", "Não"):
            raise ValueError(f"Valor inválido para '{funcao}': {ativo}.")

    con = conectar(empresa_id)
    try:
        _usuario_da_empresa(con, empresa_id, usuario_id)
        # Estado atual de cada função tocada, pra logar o valor anterior
        # de verdade -- sem linha ainda, o padrão já é 'Sim' (ver
        # listar_permissoes), então é isso que conta como "anterior".
        existentes = {
            l["funcao"]: l["ativo"]
            for l in con.execute(
                "SELECT funcao, ativo FROM usuario_permissao WHERE usuario_id = ? AND empresa_id = ?",
                (usuario_id, empresa_id),
            ).fetchall()
        }
        for funcao, ativo in mapa.items():
            anterior = existentes.get(funcao, "Sim")
            con.execute(
                "INSERT OR IGNORE INTO usuario_permissao (usuario_id, empresa_id, funcao, ativo) "
                "VALUES (?,?,?,?)",
                (usuario_id, empresa_id, funcao, ativo),
            )
            con.execute(
                "UPDATE usuario_permissao SET ativo = ? "
                "WHERE usuario_id = ? AND empresa_id = ? AND funcao = ?",
                (ativo, usuario_id, empresa_id, funcao),
            )
            if anterior != ativo:
                registrar_log(
                    con, empresa_id, "permissao_alterada", usuario_id,
                    f"Permissão '{funcao}' alterada de {anterior} para {ativo}",
                    anterior, ativo, alterado_por,
                )
        con.commit()
    finally:
        con.close()
