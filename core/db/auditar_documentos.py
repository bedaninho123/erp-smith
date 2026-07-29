"""Confere se o índice de documentos bate com os arquivos em disco.

O "banco de imagens" do ERP são duas coisas que precisam concordar: os
arquivos em `atendimento/documentos_recebidos/<empresa>/<cliente>/` e as
linhas da tabela `documento`, que guardam quem mandou, quando, de que
caso é e o caminho do arquivo. O banco nunca guarda a imagem em si --
guardar binário dentro do SQLite incharia o arquivo do banco, tornaria
todo backup pesado e não daria nada em troca, já que o painel serve o
arquivo direto do disco.

Duas coisas podem sair de sincronia, e as duas já aconteceram aqui:

- **Órfão**: arquivo no disco sem linha no banco. Foi o que sobrou dos
  testes de 2026-07-29 e da recriação do banco na migração multi-tenant
  (os arquivos ficaram, as linhas não). Ocupa espaço e ninguém enxerga
  pelo painel.
- **Quebrado**: linha no banco apontando pra arquivo que não existe. É o
  caso dos documentos migrados da planilha antiga, cujo `link_arquivo`
  aponta pra um example.com que nunca existiu.

Este script só relata -- apagar documento de arma de fogo é decisão de
gente, não de script.

Uso: `.venv\\Scripts\\python.exe -m core.db.auditar_documentos`
"""
import re
from pathlib import Path

from core.conexao import conectar_admin
from core.motor_documentos import PASTA_DOCUMENTOS


def main() -> None:
    con = conectar_admin()
    try:
        linhas = con.execute(
            "SELECT documento_id, empresa_id, cliente_id, nome_arquivo, link_arquivo, "
            "data_envio FROM documento ORDER BY documento_id"
        ).fetchall()
    finally:
        con.close()

    no_banco = {linha["documento_id"]: dict(linha) for linha in linhas}
    caminhos_esperados = set()
    quebrados = []

    for doc in no_banco.values():
        caminho = doc["link_arquivo"]
        # Documento migrado da planilha tem URL, não caminho de arquivo --
        # não é quebra, é ausência de arquivo desde sempre.
        if not caminho or caminho.startswith(("http://", "https://")):
            continue
        arquivo = Path(caminho)
        if arquivo.is_file():
            caminhos_esperados.add(arquivo.resolve())
        else:
            quebrados.append(doc)

    orfaos = []
    if PASTA_DOCUMENTOS.exists():
        for arquivo in sorted(PASTA_DOCUMENTOS.rglob("*")):
            if arquivo.is_file() and arquivo.resolve() not in caminhos_esperados:
                orfaos.append(arquivo)

    print(f"Linhas na tabela documento: {len(no_banco)}")
    print(f"Arquivos referenciados e presentes no disco: {len(caminhos_esperados)}")

    if quebrados:
        print(f"\nLinhas apontando pra arquivo que não existe ({len(quebrados)}):")
        for doc in quebrados:
            print(f"  {doc['documento_id']} ({doc['cliente_id']}) -> {doc['link_arquivo']}")
    else:
        print("\nNenhuma linha apontando pra arquivo inexistente.")

    if orfaos:
        total = sum(a.stat().st_size for a in orfaos)
        print(f"\nArquivos no disco sem linha no banco ({len(orfaos)}, {total/1024:.0f} KB):")
        for arquivo in orfaos:
            relativo = arquivo.relative_to(PASTA_DOCUMENTOS)
            doc_id = re.match(r"(DOC-\d{6})_", arquivo.name)
            pista = ""
            if doc_id and doc_id.group(1) in no_banco:
                pista = f"  (o {doc_id.group(1)} existe no banco, mas apontando pra outro caminho)"
            print(f"  {relativo}  {arquivo.stat().st_size} bytes{pista}")
        print("\nNada foi apagado -- decida você o que fazer com cada um.")
    else:
        print("\nNenhum arquivo órfão no disco.")


if __name__ == "__main__":
    main()
