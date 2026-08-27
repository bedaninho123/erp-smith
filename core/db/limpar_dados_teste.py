"""Apaga o dado de ATENDIMENTO do Core, deixando o sistema pronto para
começar a operar de verdade.

Por que existe: o Core nasceu populado de dado de teste -- primeiro a
migração da planilha (`migrate_dados_teste.py`), depois os clientes
fictícios (`gerar_clientes_ficticios.py`), depois os casos que os testes
de pipeline criaram. Nada disso é cliente de verdade, e no dia em que o
despachante começar a trabalhar esse dado só atrapalha: infla o painel,
mente nos indicadores e se mistura com o atendimento real.

O QUE ELE APAGA: cliente, caso, processo, documento (linha e arquivo),
documento_checklist, tarefas, mensagem, conversa, sessão, memória de IA,
histórico, log de IA e token do Portal.

O QUE ELE NÃO TOCA, de propósito:
  - empresa, usuário, senha e permissão -- o seu acesso ao painel;
  - serviço e documento_exigido -- o catálogo do despachante, que é
    trabalho de configuração, não dado de atendimento;
  - configurações e templates;
  - **o banco de Domínio inteiro** -- os 978 filiados, habitualidade,
    situação financeira, campeonatos e modalidades continuam intactos.
    Aquilo é espelho do Shooting House, não dado de teste.

SEGURANÇA. O padrão é NÃO apagar: sem `--confirmar` ele só mostra o que
faria. E ele se recusa a rodar sem um backup recente, porque a operação
não tem volta -- `core.db.backup` guarda banco e documentos.

    # ver o que seria apagado (não apaga nada)
    .venv\\Scripts\\python.exe -m core.db.limpar_dados_teste

    # apagar de verdade
    .venv\\Scripts\\python.exe -m core.db.limpar_dados_teste --confirmar
"""
import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.conexao import conectar_admin

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# NÃO EXISTE ordem de exclusão que satisfaça as chaves estrangeiras
# deste schema, e descobrir isso rodando foi o que fez a primeira versão
# falhar: as tabelas formam CICLO.
#
#     caso    -> sessao (sessao_principal_id), memoria_ia (memoria_id)
#     sessao  -> caso (caso_id), conversa, processo, cliente
#     conversa-> sessao (sessao_id), caso, cliente
#     memoria_ia -> sessao (ultima_sessao_id)
#     documento  -> mensagem (mensagem_id)
#
# Qualquer que seja a primeira a sair, alguém ainda aponta para ela. Não
# é defeito do schema -- é o desenho: a sessão sabe de que caso é, e o
# caso sabe qual é a sessão principal.
#
# A saída é `PRAGMA defer_foreign_keys` (ver limpar()), que adia a
# checagem até o COMMIT: no fim tudo está vazio e nada aponta para nada.
# A ordem abaixo continua sendo filhos-antes-de-pais por clareza de
# leitura, não por exigência do banco.
TABELAS = (
    "documento_checklist",
    "documento",
    "tarefas",
    "mensagem",
    "conversa",
    "log_ia",
    "historico",
    "processo",
    "caso",
    "sessao",
    "memoria_ia",
    "portal_token",
    "cliente",
)

# Quanto tempo de backup ainda conta como "recente". Doze horas cobre
# "rodei o backup de manhã e só fui confirmar à tarde" sem aceitar o
# backup automático de ontem como rede de segurança para uma decisão
# tomada hoje.
HORAS_BACKUP_RECENTE = 12


def _backup_recente() -> "tuple[bool, str]":
    """Confere se existe backup das últimas horas.

    Não é burocracia: esta é a única operação do projeto que apaga dado
    de cliente, e a diferença entre um susto e um desastre é ter de onde
    voltar. Olha a pasta de destino configurada (BACKUP_DIR), que é a
    mesma que `core.db.backup` usa.
    """
    from core.db.backup import BACKUP_DIR

    destino = Path(BACKUP_DIR)
    if not destino.exists():
        return False, f"a pasta de backup não existe ({destino})"

    pastas = sorted(
        (p for p in destino.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not pastas:
        return False, f"nenhum backup encontrado em {destino}"

    quando = datetime.fromtimestamp(pastas[0].stat().st_mtime, tz=timezone.utc)
    idade = datetime.now(timezone.utc) - quando
    if idade > timedelta(hours=HORAS_BACKUP_RECENTE):
        return False, (
            f"o backup mais recente é de {quando.astimezone():%d/%m/%Y %H:%M} "
            f"({idade.days} dia(s) atrás)"
        )
    return True, f"{pastas[0].name}, de {quando.astimezone():%d/%m/%Y %H:%M}"


def contar() -> dict:
    con = conectar_admin()
    try:
        return {tabela: con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
                for tabela in TABELAS}
    finally:
        con.close()


def arquivos_de_documento() -> list:
    """Os arquivos em disco apontados por `documento.link_arquivo`.

    Apagar só a linha do banco deixaria os arquivos órfãos na pasta --
    exatamente o descompasso que `core.db.auditar_documentos` existe para
    denunciar. Some a linha, some o arquivo.
    """
    con = conectar_admin()
    try:
        caminhos = [
            l[0] for l in con.execute(
                "SELECT link_arquivo FROM documento WHERE link_arquivo IS NOT NULL"
            ).fetchall()
        ]
    finally:
        con.close()
    return [c for c in caminhos if os.path.exists(c)]


def limpar() -> dict:
    """Apaga tudo numa transação só: ou o sistema fica limpo, ou fica
    exatamente como estava. Meio-caminho aqui seria pior que não ter
    começado.

    `defer_foreign_keys` é o que torna isso possível: as tabelas formam
    ciclo (ver o comentário de TABELAS), então nenhuma ordem funciona com
    a checagem imediata. Adiada até o COMMIT, ela ainda acontece -- e
    passa, porque no fim tudo está vazio. A integridade continua sendo
    verificada; só o momento muda.

    `isolation_level = None` é necessário porque o sqlite3 do Python
    abriria a transação sozinho no primeiro DELETE, e aí o PRAGMA teria
    rodado fora dela e não valeria de nada.
    """
    apagados = {}
    con = conectar_admin()
    try:
        con.isolation_level = None
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("BEGIN")
        con.execute("PRAGMA defer_foreign_keys = ON")
        try:
            for tabela in TABELAS:
                apagados[tabela] = con.execute(f"DELETE FROM {tabela}").rowcount
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return apagados


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apaga o dado de atendimento de teste do Core."
    )
    parser.add_argument("--confirmar", action="store_true",
                        help="apaga de verdade (sem isto, só mostra o que faria)")
    argumentos = parser.parse_args()

    contagem = contar()
    arquivos = arquivos_de_documento()
    total = sum(contagem.values())

    print("=" * 64)
    print("LIMPEZA DO DADO DE ATENDIMENTO DO CORE")
    print("=" * 64)
    for tabela in TABELAS:
        print(f"  {tabela:<22} {contagem[tabela]:>5}")
    print(f"  {'TOTAL DE LINHAS':<22} {total:>5}")
    print(f"  {'arquivos em disco':<22} {len(arquivos):>5}")
    print()
    print("NÃO será tocado: empresa, usuário, serviço, documento_exigido,")
    print("configurações, templates -- e o banco de Domínio inteiro")
    print("(filiados, habitualidade, financeiro, campeonatos, modalidades).")
    print()

    if not argumentos.confirmar:
        print("Nada foi apagado. Para apagar de verdade:")
        print("  .venv\\Scripts\\python.exe -m core.db.limpar_dados_teste --confirmar")
        return 0

    ok, detalhe = _backup_recente()
    if not ok:
        print(f"RECUSADO: {detalhe}.")
        print("Esta operação não tem volta. Rode o backup primeiro:")
        print("  .venv\\Scripts\\python.exe -m core.db.backup")
        return 1
    print(f"Backup recente encontrado: {detalhe}")
    print()

    apagados = limpar()
    for caminho in arquivos:
        try:
            os.remove(caminho)
        except OSError as e:
            # Arquivo que não sai não desfaz a limpeza do banco -- só
            # aparece no relatório para alguém apagar à mão.
            print(f"  não consegui apagar {caminho}: {e}")

    print("APAGADO:")
    for tabela in TABELAS:
        if apagados[tabela]:
            print(f"  {tabela:<22} {apagados[tabela]:>5}")
    print(f"  {'arquivos em disco':<22} {len(arquivos):>5}")
    print()
    print("O Core está limpo de atendimento. O painel abre zerado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
