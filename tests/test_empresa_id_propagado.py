"""Toda função que exige `empresa_id` é chamada passando `empresa_id`.

Este teste existe por causa de um bug real. O refactor multi-tenant
fechou com a suíte verde, e mesmo assim dois módulos ficaram para trás:
`atualizar_memoria()` recebeu a empresa mas a interna `_gerar_resumo()`
não, e `demo_pipeline.py` passou inteiro em branco. O primeiro só
apareceu quando alguém abriu o painel e usou (`HTTP 500`); o segundo,
por ser ferramenta manual, não apareceu de jeito nenhum
(docs/schema_multi_tenant.md, "Quarto achado do refactor").

Python não reclama de argumento faltando na hora de importar -- só
quando a linha executa. Num projeto onde `empresa_id` é o que separa o
dado de um despachante do dado do outro, esperar a linha executar é
esperar demais: o caminho que falta pode ser justamente o que só roda
em produção.

Então este teste lê o código-fonte (AST) em vez de executá-lo. Não
chama a OpenAI, não abre banco, não sobe servidor -- por isso pode
cobrir o projeto inteiro, inclusive os caminhos que a suíte nunca
percorre.

**O que ele NÃO prova:** que o `empresa_id` passado é o *certo*. Passar
a empresa errada continua sendo um vazamento, e é disso que
test_isolamento_painel.py e test_isolamento_portal.py cuidam. Aqui só
se prova que ninguém esqueceu de passar.
"""
import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
IGNORAR = {".venv", ".git", "node_modules", ".agents", ".claude", "__pycache__"}

PARAMETRO = "empresa_id"


def _arquivos_do_projeto():
    return [
        caminho
        for caminho in RAIZ.rglob("*.py")
        if not any(parte in IGNORAR for parte in caminho.parts)
    ]


def _modulo_de(caminho: pathlib.Path) -> str:
    """core/conexao.py -> 'core.conexao'."""
    return ".".join(caminho.relative_to(RAIZ).with_suffix("").parts)


def _exige_empresa(no) -> "tuple | None":
    """Devolve (índice do parâmetro, é obrigatório?) ou None.

    O índice importa porque quem chama pode passar posicionalmente:
    `registrar_log(empresa_id, prompt_key=...)` é tão válido quanto
    `registrar_log(empresa_id=...)`.
    """
    posicionais = [a.arg for a in no.args.posonlyargs + no.args.args]
    if PARAMETRO in posicionais:
        indice = posicionais.index(PARAMETRO)
        primeiro_com_padrao = len(posicionais) - len(no.args.defaults)
        return indice, indice < primeiro_com_padrao
    if PARAMETRO in [a.arg for a in no.args.kwonlyargs]:
        indice_kw = [a.arg for a in no.args.kwonlyargs].index(PARAMETRO)
        return None, no.args.kw_defaults[indice_kw] is None
    return None


def _catalogar(arvores: dict) -> dict:
    """{(módulo, nome da função): (índice, obrigatório)}.

    A chave inclui o módulo de propósito: `conectar` existe duas vezes
    no projeto com assinaturas diferentes -- o do Core exige a empresa,
    o do Domínio não (o Domínio filtra no WHERE, ver CLAUDE.md). Casar
    só pelo nome acusaria o Domínio errado.
    """
    catalogo = {}
    for caminho, arvore in arvores.items():
        modulo = _modulo_de(caminho)
        for no in ast.walk(arvore):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                exigencia = _exige_empresa(no)
                if exigencia:
                    catalogo[(modulo, no.name)] = exigencia
    return catalogo


def _mapa_de_nomes(arvore, modulo_atual: str) -> "tuple[dict, dict]":
    """Descobre de que módulo veio cada nome usado no arquivo.

    Devolve (funções importadas, módulos importados). Definição local
    ganha de import, que é como o próprio Python resolve.
    """
    funcoes, modulos = {}, {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
            for alias in no.names:
                funcoes[alias.asname or alias.name] = (no.module, alias.name)
                modulos[alias.asname or alias.name] = f"{no.module}.{alias.name}"
        elif isinstance(no, ast.Import):
            for alias in no.names:
                modulos[alias.asname or alias.name] = alias.name
    for no in ast.walk(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcoes[no.name] = (modulo_atual, no.name)
    return funcoes, modulos


def _chamadas_sem_empresa(arvores: dict, catalogo: dict) -> list:
    faltando = []
    for caminho, arvore in arvores.items():
        modulo = _modulo_de(caminho)
        funcoes, modulos = _mapa_de_nomes(arvore, modulo)

        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue

            alvo = None
            if isinstance(no.func, ast.Name):
                alvo = funcoes.get(no.func.id)
            elif isinstance(no.func, ast.Attribute) and isinstance(no.func.value, ast.Name):
                origem = modulos.get(no.func.value.id)
                if origem:
                    alvo = (origem, no.func.attr)

            if alvo not in catalogo:
                continue

            indice, obrigatorio = catalogo[alvo]
            if not obrigatorio:
                continue

            por_nome = any(k.arg == PARAMETRO for k in no.keywords)
            desempacotado = any(k.arg is None for k in no.keywords)  # **kwargs
            por_posicao = indice is not None and len(no.args) > indice

            if not (por_nome or desempacotado or por_posicao):
                faltando.append(
                    f"{caminho.relative_to(RAIZ).as_posix()}:{no.lineno} "
                    f"chama {alvo[0]}.{alvo[1]}() sem {PARAMETRO}"
                )
    return faltando


def _analisar(arquivos):
    arvores = {}
    for caminho in arquivos:
        try:
            arvores[caminho] = ast.parse(caminho.read_text(encoding="utf-8"))
        except SyntaxError as e:
            pytest.fail(f"{caminho} não compila: {e}")
    return _chamadas_sem_empresa(arvores, _catalogar(arvores))


# --------------------------------------------------------------------

def test_nenhuma_chamada_esquece_o_empresa_id():
    faltando = _analisar(_arquivos_do_projeto())

    assert not faltando, (
        "Função que exige empresa_id sendo chamada sem ele -- vai estourar "
        "TypeError quando essa linha rodar:\n  " + "\n  ".join(faltando)
    )


def test_a_varredura_enxerga_o_bug_que_a_motivou(tmp_path):
    """Controle positivo. Sem isto, uma varredura que não achasse nada
    nunca -- por bug nela mesma -- passaria para sempre, silenciosa.

    O código abaixo é a forma exata do bug real de 2026-07-29.
    """
    modulo = tmp_path / "modulo_falso.py"
    modulo.write_text(
        "def obter_configuracoes(empresa_id):\n"
        "    return {}\n"
        "\n"
        "def gerar_resumo(empresa_id):\n"
        "    return obter_configuracoes()\n",
        encoding="utf-8",
    )

    global RAIZ
    raiz_real = RAIZ
    try:
        RAIZ = tmp_path
        achados = _analisar([modulo])
    finally:
        RAIZ = raiz_real

    assert len(achados) == 1
    assert "obter_configuracoes" in achados[0]


def test_o_conectar_do_dominio_nao_e_falso_positivo():
    """O Domínio tem `conectar()` próprio, sem empresa_id, e filtra por
    empresa no WHERE (CLAUDE.md). Uma varredura que casasse só pelo nome
    da função acusaria esses arquivos -- e um teste que grita errado é
    um teste que as pessoas aprendem a ignorar.
    """
    dominio = [
        caminho for caminho in _arquivos_do_projeto()
        if caminho.parts[len(RAIZ.parts):][0] == "domain"
    ]
    assert dominio, "nenhum arquivo de domínio encontrado -- o teste perdeu o alvo"

    assert not _analisar(dominio)
