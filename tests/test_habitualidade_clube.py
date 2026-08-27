"""Panorama de habitualidade do clube (camada 1).

O que esta camada faz: CONTAR participações e ordenar por quem precisa de
atenção. O que ela deliberadamente NÃO faz: dizer se alguém cumpriu o
mínimo legal. O mínimo depende do nível do CR (Decreto nº 11.615/2023,
art. 35 -- 8, ou 12+4, ou 20+6), e a API do Shooting House não expõe o
nível de ninguém. Dizer a um atirador que ele está em dia quando não está
custa o CR dele.

A outra regra que estes testes protegem: o retrato guardado nunca pode se
passar por consulta ao vivo. Toda linha carrega `sincronizado_em`, e
"nunca consultado" tem que ser distinguível de "consultei e deu zero".
"""
import sqlite3
from datetime import date

import pytest

from domain.clube_tiro import motor_filiados
from tests.conftest import EMPRESA_A, EMPRESA_B

FILIADO_A = {
    "idatirador": 101, "matricula": "F101", "nome": "Atirador Um",
    "cpf": "52998224725", "email": "um@exemplo.local", "status_filiacao": "Ativo",
}
FILIADO_B = {
    "idatirador": 102, "matricula": "F102", "nome": "Atirador Dois",
    "cpf": "11144477735", "email": None, "status_filiacao": "Ativo",
}


@pytest.fixture
def dominio(tmp_path, monkeypatch):
    """Banco de Domínio temporário, com a tabela filiado criada a partir
    do schema REAL -- nunca de uma cópia escrita à mão aqui, que sairia
    de sincronia sem ninguém perceber (mesma regra do conftest do Core)."""
    from pathlib import Path

    caminho = tmp_path / "dominio_teste.db"
    schema = (Path(__file__).resolve().parent.parent
              / "domain" / "clube_tiro" / "db" / "schema.sql").read_text(encoding="utf-8")
    con = sqlite3.connect(caminho)
    con.executescript(schema)
    con.commit()
    con.close()

    monkeypatch.setattr(motor_filiados, "DOMAIN_DB", str(caminho))
    return caminho


# --------------------------------------------------------------------
# Contagem
# --------------------------------------------------------------------

def _habitualidade(datas):
    return {"habitualidades": {"ACLP": {
        "count": len(datas),
        "eventos": [{"data_participacao": d} for d in datas],
    }}}


def test_conta_so_o_que_esta_dentro_da_janela():
    hoje = date(2026, 8, 25)
    dados = _habitualidade([
        "01/09/2025",  # dentro (menos de 12 meses)
        "15/01/2026",  # dentro
        "20/08/2026",  # dentro
        "01/06/2025",  # FORA -- mais de 12 meses
    ])

    total, ultima = motor_filiados.contar_participacoes(dados, hoje=hoje)

    assert total == 3
    # A última participação é a mais recente de TODAS, não só das da
    # janela -- é o que responde "há quanto tempo essa pessoa não aparece".
    assert ultima == "2026-08-20"


def test_sem_evento_nenhum_conta_zero():
    total, ultima = motor_filiados.contar_participacoes({"habitualidades": {}})

    assert total == 0
    assert ultima is None


def test_data_em_formato_estranho_nao_vira_contagem_errada():
    """A API real manda "09/10/2025 16:30"; o normalizador separa a hora,
    mas se um dia vier algo que não dá pra ler, ignorar é melhor que
    contar errado -- este número orienta cobrança de gente."""
    dados = _habitualidade(["15/01/2026", "sei lá quando", ""])

    total, _ = motor_filiados.contar_participacoes(dados, hoje=date(2026, 8, 25))

    assert total == 1


# --------------------------------------------------------------------
# Guarda e leitura
# --------------------------------------------------------------------

def test_salvar_filiado_e_idempotente(dominio):
    primeiro = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    segundo = motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_A, nome="Nome Corrigido"))

    assert primeiro == segundo
    panorama = motor_filiados.listar_panorama(EMPRESA_A)
    assert len(panorama) == 1
    assert panorama[0]["nome"] == "Nome Corrigido"


def test_o_mesmo_cpf_pode_ser_filiado_de_duas_empresas(dominio):
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.salvar_filiado(EMPRESA_B, FILIADO_A)

    assert len(motor_filiados.listar_panorama(EMPRESA_A)) == 1
    assert len(motor_filiados.listar_panorama(EMPRESA_B)) == 1


def test_panorama_nao_vaza_filiado_de_outra_empresa(dominio):
    """O banco de Domínio é anexado, então NÃO passa pelas views do Core
    que se filtram sozinhas -- aqui o filtro é escrito à mão, e é isso
    que este teste protege."""
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.salvar_filiado(EMPRESA_B, FILIADO_B)

    panorama = motor_filiados.listar_panorama(EMPRESA_A)

    assert [f["cpf"] for f in panorama] == [FILIADO_A["cpf"]]


def test_nunca_sincronizado_e_diferente_de_zero_participacoes(dominio):
    """A distinção que a tela precisa: "não sei" e "sei que não teve" não
    podem parecer a mesma coisa. Nunca sincronizado é NULL, não 0."""
    nunca = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    zerado = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)
    motor_filiados.registrar_habitualidade(EMPRESA_A, zerado, 0, None)

    por_id = {f["filiado_id"]: f for f in motor_filiados.listar_panorama(EMPRESA_A)}

    assert por_id[nunca]["participacoes_12m"] is None
    assert por_id[nunca]["sincronizado_em"] is None
    assert por_id[zerado]["participacoes_12m"] == 0
    assert por_id[zerado]["sincronizado_em"] is not None


def test_falha_de_consulta_nao_apaga_o_retrato_anterior(dominio):
    """Um retrato velho e datado vale mais que nenhum -- desde que a tela
    mostre a data, que é por isso que sincronizado_em é preservado."""
    filiado_id = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.registrar_habitualidade(EMPRESA_A, filiado_id, 7, "2026-08-01")
    sincronizado_antes = motor_filiados.listar_panorama(EMPRESA_A)[0]["sincronizado_em"]

    motor_filiados.registrar_habitualidade(
        EMPRESA_A, filiado_id, None, None, erro="Shooting House respondeu HTTP 503."
    )

    linha = motor_filiados.listar_panorama(EMPRESA_A)[0]
    assert linha["participacoes_12m"] == 7
    assert linha["ultima_participacao"] == "2026-08-01"
    assert linha["sincronizado_em"] == sincronizado_antes
    assert "503" in linha["sincronizacao_erro"]


def test_fila_de_sincronizacao_comeca_por_quem_nunca_foi_consultado(dominio):
    ja_visto = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.registrar_habitualidade(EMPRESA_A, ja_visto, 5, "2026-08-01")
    nunca = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)

    fila = motor_filiados.proximos_a_sincronizar(EMPRESA_A, limite=10)

    assert fila[0]["filiado_id"] == nunca


def test_limite_da_fila_e_respeitado(dominio):
    """É o que impede uma rodada de despejar 900 chamadas na API do
    fornecedor de uma vez."""
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)

    assert len(motor_filiados.proximos_a_sincronizar(EMPRESA_A, limite=1)) == 1


# (Havia aqui um teste afirmando que a ordem PADRÃO era "quem precisa de
# atenção". Em 2026-08-26 o usuário pediu que a tela abrisse com os mais
# atualizados no topo, então o padrão virou "recentes" e a ordenação
# antiga continua disponível como opção. As duas estão cobertas por
# test_ordem_padrao_e_participacao_mais_recente e
# test_ordem_por_quem_precisa_de_atencao_inverte -- manter o teste antigo
# aqui deixaria dois testes afirmando padrões opostos.)


def test_paginacao_que_nao_anda_para_em_vez_de_martelar_a_api(monkeypatch):
    """`page` é suposição nossa -- a especificação do endpoint documenta
    só sortBy e status. Se ele for ignorado, a API devolve sempre a
    página 1, e um laço ingênuo pediria a mesma coisa até bater a trava:
    200 chamadas ao fornecedor e milhares de linhas repetidas."""
    from integracoes import shooting_house

    chamadas = []

    def _sempre_a_pagina_1(caminho, params=None):
        chamadas.append(params)
        return {
            "data": [{"id": 1, "name": "Fulano", "cpf": "52998224725", "status": "A"}],
            "meta": {"pagination": {"current_page": 1, "total_pages": 121}},
        }

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(shooting_house, "_chamar_api", _sempre_a_pagina_1)

    filiados = shooting_house.listar_filiados()

    # Duas chamadas é o mínimo possível: só comparando a segunda resposta
    # com a primeira dá pra saber que a página não andou. O que não pode
    # é continuar depois disso, nem trazer a mesma pessoa duas vezes.
    assert len(chamadas) == 2, f"deveria parar na segunda; fez {len(chamadas)}"
    assert len(filiados) == 1, "trouxe gente repetida"


def test_paginacao_que_anda_percorre_todas(monkeypatch):
    """Controle positivo: sem isto, um laço que parasse sempre na
    primeira página passaria no teste acima e traria 1/121 do clube."""
    from integracoes import shooting_house

    # Uma pessoa DIFERENTE por página -- é o que paginação de verdade faz,
    # e é o que separa "percorreu as três" de "pediu três vezes a mesma".
    por_pagina = {1: "52998224725", 2: "11144477735", 3: "39053344705"}

    def _paginado(caminho, params=None):
        pagina = params["page"]
        return {
            "data": [{"id": pagina, "name": f"Filiado {pagina}",
                      "cpf": por_pagina[pagina], "status": "A"}],
            "meta": {"pagination": {"current_page": pagina, "total_pages": 3}},
        }

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(shooting_house, "_chamar_api", _paginado)

    assert len(shooting_house.listar_filiados()) == 3


def test_listar_todos_pede_as_duas_listas_de_status(monkeypatch):
    """Não existe "todos" neste endpoint: status é 1 (ativo) ou 0
    (inativo), e só. O código mandava 0 achando que era "sem filtro", e a
    primeira execução real trouxe 547 pessoas num clube de 1454 --
    exatamente o número de inativos.

    O estrago seria silencioso: o panorama listaria só inativos, e a
    sincronização de habitualidade, que busca quem está 'Ativo', não
    acharia ninguém e não faria nada, sem erro nenhum."""
    from integracoes import shooting_house

    pedidos = []

    def _por_status(caminho, params=None):
        pedidos.append(params["status"])
        cpf = "52998224725" if params["status"] == 1 else "11144477735"
        nome = "Ativo Um" if params["status"] == 1 else "Inativo Um"
        return {
            "data": [{"id": 1, "name": nome, "cpf": cpf,
                      "status": "A" if params["status"] == 1 else "I"}],
            "meta": {"pagination": {"current_page": 1, "total_pages": 1}},
        }

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(shooting_house, "_chamar_api", _por_status)

    todos = shooting_house.listar_filiados(somente_ativos=False)

    assert sorted(pedidos) == [0, 1], "precisa pedir as DUAS listas"
    assert {f["status_filiacao"] for f in todos} == {"Ativo", "Inativo"}
    assert len(todos) == 2


def test_listar_somente_ativos_nao_pede_os_inativos(monkeypatch):
    """Controle positivo: a rodada normal não precisa gastar uma chamada
    a mais trazendo quem saiu do clube."""
    from integracoes import shooting_house

    pedidos = []

    def _registra(caminho, params=None):
        pedidos.append(params["status"])
        return {"data": [], "meta": {"pagination": {"current_page": 1, "total_pages": 1}}}

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(shooting_house, "_chamar_api", _registra)

    shooting_house.listar_filiados(somente_ativos=True)

    assert pedidos == [1]


def test_cadastro_nao_grava_bairro_no_campo_cidade(monkeypatch):
    """O bloco `address` da API não tem cidade -- tem district (bairro).
    Preencher cidade com o bairro seria um erro silencioso, que só
    apareceria quando alguém filtrasse clientes por cidade."""
    from integracoes import shooting_house

    monkeypatch.setattr(shooting_house, "shooting_house_ativo", lambda: True)
    monkeypatch.setattr(
        shooting_house, "_chamar_api",
        lambda caminho, params=None: {
            "name": "Fulano", "cpf": "52998224725", "status": "A",
            "address": {"address": "Rua X", "district": "Centro", "zip": "17500000"},
        },
    )

    cadastro = shooting_house.consultar_cadastro("52998224725")

    assert cadastro["cidade"] is None
    assert "Centro" not in str(cadastro.values())


# --------------------------------------------------------------------
# Busca do panorama
# --------------------------------------------------------------------

@pytest.fixture
def dois_filiados(dominio):
    motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_A, nome="Ana Atiradora"))
    motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_B, nome="Bruno Bala"))
    return dominio


def _nomes(empresa_id, **kwargs):
    return [f["nome"] for f in motor_filiados.listar_panorama(empresa_id, **kwargs)]


def test_busca_por_nome(dois_filiados):
    assert _nomes(EMPRESA_A, busca="bruno") == ["Bruno Bala"]


def test_busca_por_matricula(dois_filiados):
    assert _nomes(EMPRESA_A, busca="F101") == ["Ana Atiradora"]


@pytest.mark.parametrize("digitado", ["52998224725", "529.982.247-25", "529982"])
def test_busca_por_cpf_com_ou_sem_pontuacao(dois_filiados, digitado):
    """O CPF é guardado só com dígitos, mas a tela MOSTRA pontuado. Sem
    limpar a pontuação, copiar o número da própria tela e colar na busca
    não acharia ninguém."""
    assert _nomes(EMPRESA_A, busca=digitado) == ["Ana Atiradora"]


def test_busca_por_nome_nao_devolve_o_clube_inteiro(dois_filiados):
    """A armadilha do filtro de CPF: reduzir "Ana" a dígitos dá string
    vazia, e um LIKE '%%' casaria com todo mundo -- a busca devolveria o
    clube inteiro parecendo que funcionou."""
    assert _nomes(EMPRESA_A, busca="Ana") == ["Ana Atiradora"]


def test_busca_sem_resultado_devolve_vazio(dois_filiados):
    assert _nomes(EMPRESA_A, busca="ninguem com esse nome") == []


def test_busca_nao_atravessa_a_empresa(dois_filiados):
    """O banco de Domínio é anexado e não passa pelas views do Core: o
    filtro de empresa é escrito à mão, e o OR da busca poderia passar por
    cima dele se faltassem os parênteses."""
    motor_filiados.salvar_filiado(EMPRESA_B, dict(FILIADO_A, nome="Ana Da Outra"))

    assert _nomes(EMPRESA_A, busca="Ana") == ["Ana Atiradora"]


@pytest.fixture
def tres_com_datas(dominio):
    """Três filiados com históricos diferentes -- o suficiente para
    exercitar faixa, período e ordenação."""
    recente = motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_A, nome="Recente"))
    motor_filiados.registrar_habitualidade(EMPRESA_A, recente, 22, "2026-08-20")

    antigo = motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_B, nome="Antigo"))
    motor_filiados.registrar_habitualidade(EMPRESA_A, antigo, 5, "2026-02-10")

    nunca = motor_filiados.salvar_filiado(
        EMPRESA_A, dict(FILIADO_A, cpf="39053344705", nome="Nunca")
    )
    motor_filiados.registrar_habitualidade(EMPRESA_A, nunca, 0, None)
    return dominio


def test_ordem_padrao_e_participacao_mais_recente(tres_com_datas):
    """Pedido do usuário: "sempre deixar com os mais atualizados". Quem
    nunca participou vai pro fim, não pro começo."""
    assert _nomes(EMPRESA_A) == ["Recente", "Antigo", "Nunca"]


def test_ordem_por_quem_precisa_de_atencao_inverte(tres_com_datas):
    """A ordenação original da tela continua disponível -- é a que serve
    pra cobrar quem está atrasado."""
    assert _nomes(EMPRESA_A, ordenar_por="atencao") == ["Nunca", "Antigo", "Recente"]


def test_ordenacao_desconhecida_cai_no_padrao_em_vez_de_quebrar(tres_com_datas):
    """ORDER BY não aceita parâmetro do SQLite, então o valor entra por
    interpolação. Aceitar o que o navegador manda seria injeção de SQL;
    a lista controlada é o que impede."""
    assert _nomes(EMPRESA_A, ordenar_por="; DROP TABLE filiado") == _nomes(EMPRESA_A)


@pytest.mark.parametrize(
    "faixa, esperado",
    [
        ("sem_nenhuma", ["Nunca"]),
        ("1_a_7", ["Antigo"]),
        ("20_ou_mais", ["Recente"]),
        ("nao_consultado", []),
        ("faixa_inventada", ["Recente", "Antigo", "Nunca"]),
    ],
)
def test_filtro_por_faixa_de_participacoes(tres_com_datas, faixa, esperado):
    assert _nomes(EMPRESA_A, faixa=faixa) == esperado


def test_filtro_por_periodo_da_ultima_participacao(tres_com_datas):
    assert _nomes(EMPRESA_A, participou_de="2026-06-01") == ["Recente"]
    assert _nomes(EMPRESA_A, participou_ate="2026-06-01") == ["Antigo"]
    assert _nomes(
        EMPRESA_A, participou_de="2026-01-01", participou_ate="2026-12-31"
    ) == ["Recente", "Antigo"]


def test_quem_nunca_participou_some_do_filtro_por_periodo(tres_com_datas):
    """E está certo: ele não participou DENTRO do período pedido. Quem
    procura essa gente usa a faixa "nenhuma participação"."""
    assert "Nunca" not in _nomes(EMPRESA_A, participou_de="2020-01-01")


def test_filtro_por_situacao(dominio):
    motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_A, nome="Atual"))
    motor_filiados.salvar_filiado(
        EMPRESA_A, dict(FILIADO_B, nome="Saiu", status_filiacao="Inativo")
    )

    assert _nomes(EMPRESA_A, situacao="Ativo") == ["Atual"]
    assert _nomes(EMPRESA_A, situacao="Inativo") == ["Saiu"]
    assert sorted(_nomes(EMPRESA_A, situacao="")) == ["Atual", "Saiu"]


def test_filtros_se_combinam(tres_com_datas):
    assert _nomes(EMPRESA_A, busca="Recente", faixa="20_ou_mais") == ["Recente"]
    assert _nomes(EMPRESA_A, busca="Recente", faixa="1_a_7") == []


def test_busca_respeita_o_filtro_de_inativos(dominio):
    motor_filiados.salvar_filiado(
        EMPRESA_A, dict(FILIADO_A, nome="Ex Filiado", status_filiacao="Inativo")
    )

    assert _nomes(EMPRESA_A, busca="Ex") == []
    assert _nomes(EMPRESA_A, busca="Ex", somente_ativos=False) == ["Ex Filiado"]


def test_rota_do_panorama_aceita_busca(painel, dominio):
    motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_A, nome="Ana Atiradora"))
    motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_B, nome="Bruno Bala"))

    resposta = painel.get("/api/filiados/panorama?busca=bruno")

    dados = resposta.get_json()
    assert [f["nome"] for f in dados["filiados"]] == ["Bruno Bala"]
    assert dados["total_encontrados"] == 1
    # O resumo é do clube, não da busca -- são perguntas diferentes.
    assert dados["resumo"]["total"] == 2


# --------------------------------------------------------------------
# A ponte entre as duas populações (cliente do despachante x filiado)
# --------------------------------------------------------------------

def test_obter_por_cpf_encontra_o_filiado(dominio):
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)

    achado = motor_filiados.obter_por_cpf(EMPRESA_A, "529.982.247-25")

    assert achado["nome"] == FILIADO_A["nome"]


def test_obter_por_cpf_devolve_none_para_quem_nao_e_filiado(dominio):
    """Resposta normal, não erro: cliente do despachante que nunca passou
    pelo clube é caso corriqueiro (transferência de arma, por exemplo)."""
    assert motor_filiados.obter_por_cpf(EMPRESA_A, "11144477735") is None
    assert motor_filiados.obter_por_cpf(EMPRESA_A, "abc") is None
    assert motor_filiados.obter_por_cpf(EMPRESA_A, None) is None


def test_obter_por_cpf_nao_atravessa_a_empresa(dominio):
    motor_filiados.salvar_filiado(EMPRESA_B, FILIADO_A)

    assert motor_filiados.obter_por_cpf(EMPRESA_A, FILIADO_A["cpf"]) is None


def test_ficha_do_cliente_mostra_o_lado_do_clube(painel, dominio):
    """A mesma pessoa nas duas populações: a ficha do despachante passa a
    mostrar o que o clube sabe dela, sem obrigar a copiar o CPF e
    procurar na outra tela."""
    from core.motor_clientes import criar_cliente

    cliente = criar_cliente(EMPRESA_A, nome="Pessoa Dos Dois", cpf="52998224725")
    filiado_id = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)
    motor_filiados.registrar_habitualidade(EMPRESA_A, filiado_id, 9, "2026-08-01")

    dados = painel.get(f"/api/clientes/{cliente['cliente_id']}").get_json()

    assert dados["filiado"]["participacoes_12m"] == 9
    assert dados["filiado"]["matricula"] == FILIADO_A["matricula"]


def test_ficha_de_quem_nao_e_filiado_traz_filiado_nulo(painel, dominio):
    from core.motor_clientes import criar_cliente

    cliente = criar_cliente(EMPRESA_A, nome="So Despachante", cpf="11144477735")

    assert painel.get(f"/api/clientes/{cliente['cliente_id']}").get_json()["filiado"] is None


def test_rota_distingue_situacao_ausente_de_situacao_vazia(painel, dominio):
    """Três estados, não dois. O parâmetro AUSENTE significa "use o
    padrão (ativos)"; presente e VAZIO significa "todos, de propósito".

    Confundir os dois foi um bug de verdade: a opção "Todos" da tela
    devolvia só os ativos, sem erro nenhum. Os testes do motor passavam
    -- era a rota que colapsava os dois casos."""
    motor_filiados.salvar_filiado(EMPRESA_A, dict(FILIADO_A, nome="Atual"))
    motor_filiados.salvar_filiado(
        EMPRESA_A, dict(FILIADO_B, nome="Saiu", status_filiacao="Inativo")
    )

    ausente = painel.get("/api/filiados/panorama").get_json()
    vazia = painel.get("/api/filiados/panorama?situacao=").get_json()
    inativos = painel.get("/api/filiados/panorama?situacao=Inativo").get_json()

    assert [f["nome"] for f in ausente["filiados"]] == ["Atual"]
    assert sorted(f["nome"] for f in vazia["filiados"]) == ["Atual", "Saiu"]
    assert [f["nome"] for f in inativos["filiados"]] == ["Saiu"]


def test_panorama_marca_quem_tambem_e_cliente(painel, dominio):
    from core.motor_clientes import criar_cliente

    cliente = criar_cliente(EMPRESA_A, nome="Pessoa Dos Dois", cpf="52998224725")
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)   # mesmo CPF
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)   # só filiado

    dados = painel.get("/api/filiados/panorama").get_json()

    por_cpf = {f["cpf"]: f for f in dados["filiados"]}
    assert por_cpf["52998224725"]["cliente_id"] == cliente["cliente_id"]
    assert por_cpf["11144477735"]["cliente_id"] is None
    assert dados["total_tambem_clientes"] == 1


def test_marcacao_de_cliente_nao_atravessa_a_empresa(painel, dominio):
    """O cruzamento é feito em código, não por FK -- são bancos
    diferentes. Se o filtro de empresa escapasse de um dos dois lados, um
    filiado desta empresa apareceria marcado como cliente da outra."""
    from core.motor_clientes import criar_cliente

    criar_cliente(EMPRESA_B, nome="Cliente Da Outra", cpf="52998224725")
    motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)

    dados = painel.get("/api/filiados/panorama").get_json()

    assert dados["filiados"][0]["cliente_id"] is None
    assert dados["total_tambem_clientes"] == 0


def test_resumo_conta_sem_dado_e_sem_participacao(dominio):
    sem_dado = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_A)  # noqa: F841
    zerado = motor_filiados.salvar_filiado(EMPRESA_A, FILIADO_B)
    motor_filiados.registrar_habitualidade(EMPRESA_A, zerado, 0, None)

    resumo = motor_filiados.resumo_do_clube(EMPRESA_A)

    assert resumo["total"] == 2
    assert resumo["sem_dado"] == 1
    assert resumo["sem_participacao"] == 1
