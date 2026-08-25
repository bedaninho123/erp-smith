"""O cliente do Shooting House nunca escreve nada lá. Só lê.

Não é preferência de estilo, são três razões que se somam:

1. **O Shooting House é o sistema de registro que reporta à Polícia
   Federal e ao Exército.** Um registro de habitualidade gravado por
   nós entraria nessa cadeia. Se o nosso sistema e o deles divergirem,
   o que vale legalmente é o deles -- e a divergência teria sido criada
   por nós.

2. **A credencial escreve.** A especificação da API tem
   `POST /registers/event/{shooterId}` (registra habitualidade),
   `POST /registers/shooter` (cadastra filiado), `/add-credit`,
   `/store/order/pay`, biometria. Ou seja: um vazamento da credencial
   guardada no .env desta máquina não seria "alguém leu dado", seria
   "alguém fabricou habitualidade em nome de um filiado" -- exatamente
   a fraude que a regulamentação de arma de fogo existe pra impedir.
   Quanto menos caminhos de escrita existirem no nosso código, menor a
   chance de um deles ser usado por engano ou por bug.

3. **Contrato.** O uso desta API é limitado a não construir sistema que
   confronte o Shooting House. Consumir dado pra gerir o próprio clube é
   uma coisa; passar a gravar registro regulatório por fora do produto
   deles é outra, e não é uma linha que se atravessa sem querer.

Por que um teste que LÊ o código em vez de executar (mesma ideia de
test_empresa_id_propagado.py): não existe teste de comportamento que
prove a AUSÊNCIA de uma chamada. Um `requests.post` acrescentado daqui a
seis meses, num caminho que a suíte não percorre, passaria despercebido
até rodar em produção -- e "rodar em produção" aqui significa gravar
registro no sistema que fala com a PF.
"""
import ast
import pathlib

import pytest

MODULOS_DO_SHOOTING_HOUSE = [
    "integracoes/shooting_house.py",
    "integracoes/diagnostico_shooting_house.py",
]

# Tudo que não é leitura. `get` fica de fora de propósito -- é o único
# verbo permitido.
VERBOS_DE_ESCRITA = {"post", "put", "patch", "delete", "request", "Session"}

RAIZ = pathlib.Path(__file__).resolve().parent.parent


def _chamadas_http(caminho: pathlib.Path) -> list[str]:
    """Devolve os verbos HTTP chamados sobre `requests` no arquivo."""
    arvore = ast.parse(caminho.read_text(encoding="utf-8"), filename=str(caminho))
    encontrados = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call):
            continue
        alvo = no.func
        # Pega tanto `requests.post(...)` quanto `shooting_house.requests.post(...)`
        if isinstance(alvo, ast.Attribute) and isinstance(alvo.value, ast.Name):
            if alvo.value.id == "requests":
                encontrados.append(alvo.attr)
    return encontrados


@pytest.mark.parametrize("modulo", MODULOS_DO_SHOOTING_HOUSE)
def test_nenhuma_chamada_de_escrita_ao_shooting_house(modulo):
    caminho = RAIZ / modulo
    assert caminho.exists(), f"{modulo} sumiu -- ajuste este teste junto"

    escritas = [v for v in _chamadas_http(caminho) if v in VERBOS_DE_ESCRITA]

    assert not escritas, (
        f"{modulo} passou a chamar requests.{escritas[0]}(). O cliente do "
        "Shooting House é SOMENTE LEITURA -- ver o cabeçalho deste teste. "
        "Se escrever lá virou mesmo um requisito, isso precisa ser uma "
        "decisão consciente (regulatória e contratual), não um import novo."
    )


def test_o_teste_pega_uma_escrita_de_verdade(tmp_path):
    """Controle positivo: sem isto, um erro no analisador faria o teste
    acima passar para sempre, dando uma sensação de proteção que não
    existe."""
    falso = tmp_path / "modulo_com_escrita.py"
    falso.write_text(
        "import requests\n"
        "def gravar():\n"
        "    return requests.post('https://exemplo', json={})\n",
        encoding="utf-8",
    )

    assert "post" in _chamadas_http(falso)
