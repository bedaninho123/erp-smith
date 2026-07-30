"""Rede de segurança estática pro controle de acesso do painel -- mesmo
espírito de tests/test_empresa_id_propagado.py, mas pra decorator de
acesso em vez de empresa_id. Em vez de ler o código como texto (AST),
varre app.url_map de verdade: cada rota /api/* precisa ter passado por
@login_required e por @gestor_required ou @funcao_required(...), o que é
lido de marcadores (`_login_protegido`, `_controle_acesso`) que os três
decorators gravam em si mesmos (webapp/app.py). Assim uma rota nova
esquecida pega o teste sem precisar que alguém lembre de escrever um
caso específico pra ela.
"""
import pytest

from webapp.app import app, funcao_required

# Rotas /api/* que de propósito não levam gestor_required nem
# funcao_required -- cada uma com o motivo, mesmo padrão de exceção
# documentada que o resto do projeto usa (CLAUDE.md).
ROTAS_API_SEM_CONTROLE_DE_FUNCAO = {
    # Compartilhada entre a ficha do Caso e a do Cliente -- gatear por
    # uma função só quebraria a outra tela (mesmo problema que
    # /api/campeonatos teve com Resultados). A barreira real é o filtro
    # de empresa_id, não isto.
    "documento_arquivo",
}


def _rotas_api():
    return [r for r in app.url_map.iter_rules() if r.rule.startswith("/api/")]


def test_toda_rota_api_exige_login():
    sem_login = [
        r.endpoint for r in _rotas_api()
        if not getattr(app.view_functions[r.endpoint], "_login_protegido", False)
    ]
    assert not sem_login, f"Rota(s) /api/* sem @login_required: {sem_login}"


def test_toda_rota_api_tem_controle_de_acesso():
    sem_controle = [
        r.endpoint for r in _rotas_api()
        if r.endpoint not in ROTAS_API_SEM_CONTROLE_DE_FUNCAO
        and getattr(app.view_functions[r.endpoint], "_controle_acesso", None) is None
    ]
    assert not sem_controle, (
        f"Rota(s) /api/* sem @gestor_required nem @funcao_required: {sem_controle}. "
        "Se for proposital, adicione o endpoint em ROTAS_API_SEM_CONTROLE_DE_FUNCAO "
        "aqui, com o motivo -- igual documento_arquivo."
    )


def test_excecao_documentada_continua_existindo():
    # Se documento_arquivo for removida/renomeada, a exceção acima vira
    # lixo sem ninguém perceber -- este teste força atualizar os dois
    # juntos.
    endpoints = {r.endpoint for r in _rotas_api()}
    for endpoint in ROTAS_API_SEM_CONTROLE_DE_FUNCAO:
        assert endpoint in endpoints, (
            f"'{endpoint}' está em ROTAS_API_SEM_CONTROLE_DE_FUNCAO mas não existe "
            "mais como rota -- remova da lista."
        )


def test_funcao_invalida_falha_na_hora_de_decorar():
    # Trava a garantia central: um typo em @funcao_required("...") não
    # pode virar acesso liberado em silêncio (tem_permissao() devolve
    # True quando não acha a chave) -- tem que estourar já na importação
    # do módulo, não só num teste que ninguém escreveu ainda.
    with pytest.raises(AssertionError):
        funcao_required("chave-que-nao-existe-no-catalogo")
