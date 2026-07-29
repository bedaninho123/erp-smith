"""Motor de Usuários: cria e administra o acesso dos usuários do painel de
uma empresa. Papéis e permissões de verdade (2026-07-29): dois papéis,
Gestor (acesso total) e Atendente (opera casos/clientes/documentos, sem
acesso administrativo) -- validado aqui, não por CHECK no schema, mesmo
padrão do status do Caso em core/motor_casos.py.

Este módulo nunca define senha -- isso continua exclusivo de
webapp/definir_senha.py, rodado interativamente pelo próprio usuário
(CLAUDE.md). Usuário criado aqui nasce com senha_hash=NULL, "login ainda
não configurado".
"""
from datetime import datetime, timezone
from typing import Optional

from core.conexao import conectar

PAPEIS_VALIDOS = ("Gestor", "Atendente")


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


def atualizar_papel(empresa_id: str, usuario_id: str, novo_papel: str) -> None:
    if novo_papel not in PAPEIS_VALIDOS:
        raise ValueError(f"Papel inválido: {novo_papel}. Use um de {PAPEIS_VALIDOS}.")
    con = conectar(empresa_id)
    try:
        _usuario_da_empresa(con, empresa_id, usuario_id)
        con.execute(
            "UPDATE usuario SET papel = ? WHERE usuario_id = ? AND empresa_id = ?",
            (novo_papel, usuario_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()


def atualizar_ativo(empresa_id: str, usuario_id: str, ativo: str) -> None:
    if ativo not in ("Sim", "Não"):
        raise ValueError("Campo 'ativo' inválido.")
    con = conectar(empresa_id)
    try:
        _usuario_da_empresa(con, empresa_id, usuario_id)
        con.execute(
            "UPDATE usuario SET ativo = ? WHERE usuario_id = ? AND empresa_id = ?",
            (ativo, usuario_id, empresa_id),
        )
        con.commit()
    finally:
        con.close()
