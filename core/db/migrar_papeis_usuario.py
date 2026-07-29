"""Normaliza usuario.papel para os dois valores válidos de verdade
(core/motor_usuarios.PAPEIS_VALIDOS: 'Gestor', 'Atendente'), no banco que
já está em uso -- sem alterar a estrutura da tabela.

Até aqui, papel era texto livre e nenhum código lia esse valor. Qualquer
linha que não seja já 'Gestor' ou 'Atendente' vira 'Gestor': quem já tinha
acesso ao sistema inteiro (todo mundo, hoje) não perde acesso sem querer só
porque a coluna ganhou significado. O próprio Gestor rebaixa quem quiser
depois, pela tela de Usuários em Configurações.

Idempotente -- rodar de novo não faz nada. Usa conectar_admin() porque
mexe em dado de todas as empresas ao mesmo tempo (CLAUDE.md: admin só em
script de setup).

Uso: `.venv\\Scripts\\python.exe -m core.db.migrar_papeis_usuario`
"""
from core.conexao import conectar_admin
from core.motor_usuarios import PAPEIS_VALIDOS


def main() -> None:
    con = conectar_admin()
    try:
        placeholders = ",".join("?" * len(PAPEIS_VALIDOS))
        fora_do_padrao = con.execute(
            f"SELECT usuario_id, nome, papel FROM usuario WHERE papel NOT IN ({placeholders})",
            PAPEIS_VALIDOS,
        ).fetchall()
        if not fora_do_padrao:
            print(f"Nada a fazer: todo usuário já está em {PAPEIS_VALIDOS}.")
            return

        for linha in fora_do_padrao:
            print(f"  {linha['usuario_id']} -- {linha['nome']}: '{linha['papel']}' -> 'Gestor'")
        con.execute(
            f"UPDATE usuario SET papel = 'Gestor' WHERE papel NOT IN ({placeholders})",
            PAPEIS_VALIDOS,
        )
        con.commit()
        print(f"\nPronto. {len(fora_do_padrao)} usuário(s) normalizado(s) para 'Gestor'.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
