"""Confere a integração com o Shooting House SEM expor dado de pessoa
nenhuma na tela.

Por que existe: `_normalizar_habitualidade_real()` foi escrita lendo a
documentação (SwaggerHub), nunca contra uma resposta de verdade. Os
nomes de campo podem estar errados, e o jeito de descobrir isso é olhar
uma resposta real. Só que "olhar uma resposta real" significa colocar o
histórico de treinos e as armas de uma pessoa no terminal -- e o
terminal do Windows guarda histórico, o PowerShell também, e a tela
costuma estar sendo compartilhada exatamente na hora em que se está
depurando algo.

Então este módulo imprime a PLANTA da resposta, nunca o conteúdo: nomes
de campo, tipo de cada um, quantidade de itens. Nunca uma data, um nome,
um número de série. O suficiente para corrigir o mapeamento, e nada
além disso.

Roda mesmo com SHOOTING_HOUSE_ATIVO desligado -- é justamente pra ser
usado ANTES de ligar a chave geral. Uso:

    .venv\\Scripts\\python.exe -m integracoes.diagnostico_shooting_house

Use o SEU PRÓPRIO CPF. Consultar o CPF de um cliente "só pra testar" é
tratar dado de terceiro como material de teste -- se precisar mesmo,
peça autorização à pessoa antes.
"""
from getpass import getpass
from urllib.parse import urlparse

from integracoes import config
from integracoes.shooting_house import (
    ShootingHouseIndisponivel,
    _CAMPOS_EVENTO_HABITUALIDADE_REAL,
    _chamar_api,
    _limpar_cpf,
    _mascarar_cpf,
    _normalizar_habitualidade_real,
    verificar_credencial,
)

# Até onde descer na estrutura. Fundo o bastante pra enxergar
# habitualidades[grupo][arma][campo], que é o nível onde mora a dúvida.
PROFUNDIDADE_MAXIMA = 5


def _tipo_legivel(valor) -> str:
    if valor is None:
        return "vazio (null)"
    return {
        bool: "sim/não", int: "número", float: "número", str: "texto",
        list: "lista", dict: "bloco",
    }.get(type(valor), type(valor).__name__)


def _chave_segura(chave: str) -> str:
    """Nome de campo é estrutura e pode aparecer. Chave que é só número
    (id de arma, id de atirador) é dado, então vira rótulo genérico."""
    return "<id>" if str(chave).isdigit() else str(chave)


def _descrever(valor, indentacao: int = 0, profundidade: int = 0) -> list[str]:
    """Descreve a forma do dado. Nunca devolve o valor em si -- só tipo,
    tamanho e nomes de campo."""
    espaco = "  " * indentacao
    if profundidade >= PROFUNDIDADE_MAXIMA:
        return [f"{espaco}... (não descido mais fundo)"]

    if isinstance(valor, dict):
        linhas = []
        for chave, sub in valor.items():
            nome = _chave_segura(chave)
            if isinstance(sub, (dict, list)):
                tamanho = len(sub)
                linhas.append(f"{espaco}{nome}: {_tipo_legivel(sub)} com {tamanho} item(ns)")
                linhas.extend(_descrever(sub, indentacao + 1, profundidade + 1))
            else:
                linhas.append(f"{espaco}{nome}: {_tipo_legivel(sub)}")
        return linhas

    if isinstance(valor, list):
        if not valor:
            return [f"{espaco}(lista vazia)"]
        # Só o primeiro item -- os outros têm a mesma forma, e repetir
        # não acrescenta informação nenhuma sobre a estrutura.
        linhas = [f"{espaco}[cada item da lista tem esta forma:]"]
        linhas.extend(_descrever(valor[0], indentacao + 1, profundidade + 1))
        return linhas

    return [f"{espaco}{_tipo_legivel(valor)}"]


def _conferir_configuracao() -> bool:
    print("=" * 68)
    print("1. CONFIGURAÇÃO")
    print("=" * 68)

    endereco = urlparse(config.SHOOTING_HOUSE_BASE_URL)
    host = endereco.hostname or "(não configurado)"
    print(f"   Endereço da API : {config.SHOOTING_HOUSE_BASE_URL}")
    print(f"   Servidor        : {host}")

    if "beta" in host.lower() or "homolog" in host.lower() or "sandbox" in host.lower():
        ambiente = "HOMOLOGAÇÃO / BETA (pelo nome do servidor)"
    else:
        ambiente = "aparenta ser PRODUÇÃO (o nome do servidor não diz 'beta')"
    print(f"   Ambiente        : {ambiente}")

    if endereco.scheme != "https":
        print(f"   HTTPS           : NÃO -- o endereço usa {endereco.scheme!r}.")
        print("                     A credencial viajaria em texto claro. Abortado.")
        return False
    print("   HTTPS           : sim")

    if not config.shooting_house_credencial_presente():
        print("   Credencial      : NÃO encontrada no .env")
        print()
        print("   Preencha SHOOTING_HOUSE_USER e SHOOTING_HOUSE_PASSWORD no .env")
        print("   e rode de novo. Não precisa ligar SHOOTING_HOUSE_ATIVO para este")
        print("   diagnóstico -- ele é justamente o passo anterior a isso.")
        return False
    print("   Credencial      : presente (valor nunca é impresso)")

    estado = "LIGADO" if config.SHOOTING_HOUSE_ATIVO else "desligado"
    print(f"   Modo real       : {estado}  (SHOOTING_HOUSE_ATIVO)")
    if not config.SHOOTING_HOUSE_ATIVO:
        print("                     O sistema segue no simulado no atendimento normal;")
        print("                     este diagnóstico consulta de verdade mesmo assim.")
    print()
    return True


def _conferir_credencial() -> bool:
    """Usa GET /checkAuth, que não consulta pessoa nenhuma. Este passo
    sozinho já responde "a credencial é deste ambiente?" -- por isso vem
    antes de o CPF ser pedido: se a resposta for não, ninguém precisa
    digitar CPF nenhum."""
    print("=" * 68)
    print("2. A CREDENCIAL VALE NESTE SERVIDOR?  (sem consultar ninguém)")
    print("=" * 68)

    resultado = verificar_credencial()
    if resultado["ok"]:
        print("   SIM. Credencial aceita.")
        print("   -> A credencial que você recebeu é DESTE ambiente, o que está")
        print("      configurado acima. Se ali diz BETA e você esperava produção,")
        print("      peça ao Shooting House o endereço de produção.")
        print()
        return True

    print(f"   NÃO: {resultado['detalhe']}")
    print()
    print("   Se fala em credencial recusada, o caso mais provável é a credencial")
    print("   ser do OUTRO ambiente. Peça o endereço correspondente ao Shooting")
    print("   House e ponha em SHOOTING_HOUSE_BASE_URL no .env.")
    print()
    return False


def _conferir_habitualidade(cpf: str) -> None:
    print("=" * 68)
    print("3. RESPOSTA DE HABITUALIDADE (estrutura, sem conteúdo)")
    print("=" * 68)
    print(f"   CPF consultado  : {_mascarar_cpf(cpf)}")
    print()

    try:
        bruto = _chamar_api(f"/registers/habitualities/{cpf}")
    except ShootingHouseIndisponivel as e:
        print(f"   NÃO FOI POSSÍVEL CONSULTAR: {e}")
        print()
        print("   Se a mensagem fala em credencial recusada, é sinal de que a")
        print("   credencial recebida não vale para ESTE servidor -- provavelmente")
        print("   ela é do outro ambiente. Peça ao Shooting House o endereço")
        print("   correspondente e coloque em SHOOTING_HOUSE_BASE_URL no .env.")
        return

    print("   Credencial ACEITA por este servidor.")
    print("   -> é este o ambiente ao qual a sua credencial pertence.")
    print()

    if isinstance(bruto, list):
        print(f"   A resposta veio como lista com {len(bruto)} item(ns).")
        bruto = bruto[0] if bruto else {}
        print()

    print("   Forma da resposta:")
    for linha in _descrever(bruto, indentacao=2):
        print(linha)
    print()

    print("-" * 68)
    print("4. O MAPEAMENTO DO CÓDIGO BATE COM A RESPOSTA REAL?")
    print("-" * 68)

    if not isinstance(bruto, dict):
        print("   Resposta não é um bloco -- mapeamento não pôde ser conferido.")
        return

    # Campos do topo que _normalizar_habitualidade_real espera.
    for campo in ("idatirador", "atirador", "matricula", "cr", "cpf", "habitualidades"):
        marca = "ok  " if campo in bruto else "FALTA"
        print(f"   [{marca}] {campo}")

    # Campos de cada evento -- o ponto que nunca foi testado.
    grupos = bruto.get("habitualidades") or {}
    campos_vistos = set()
    for armas in grupos.values():
        if isinstance(armas, dict):
            for dados_arma in armas.values():
                if isinstance(dados_arma, dict):
                    campos_vistos.update(dados_arma.keys())

    print()
    print("   Campos de evento que o código procura dentro de cada arma:")
    for campo_real, campo_normalizado in (
        {"data_participacao": "data_participacao"} | _CAMPOS_EVENTO_HABITUALIDADE_REAL
    ).items():
        marca = "ok  " if campo_real in campos_vistos else "FALTA"
        print(f"   [{marca}] {campo_real}  ->  {campo_normalizado}")

    faltando = campos_vistos - set(_CAMPOS_EVENTO_HABITUALIDADE_REAL) - {"data_participacao"}
    if faltando:
        print()
        print("   Campos que a API devolve e o código ignora hoje:")
        print("   " + ", ".join(sorted(faltando)))

    print()
    try:
        normalizado = _normalizar_habitualidade_real(bruto)
    except Exception as e:
        print(f"   A conversão QUEBROU: {type(e).__name__}: {e}")
        return

    total = sum(g.get("count", 0) for g in normalizado["habitualidades"].values())
    print(f"   Conversão rodou. Grupos: {len(normalizado['habitualidades'])}, "
          f"participações somadas: {total}.")
    if total == 0 and grupos:
        print("   ATENÇÃO: a API devolveu grupos, mas a conversão produziu zero")
        print("   participações -- é o sintoma clássico de nome de campo errado.")


def main() -> None:
    print()
    print("DIAGNÓSTICO DA INTEGRAÇÃO SHOOTING HOUSE")
    print("Nenhum dado pessoal é impresso: só nomes de campo e quantidades.")
    print()

    if not _conferir_configuracao():
        return

    if not _conferir_credencial():
        return

    print("=" * 68)
    print("PRÓXIMO PASSO (opcional): conferir a ESTRUTURA da resposta")
    print("=" * 68)
    print("Até aqui nenhum dado de pessoa foi consultado. O passo seguinte")
    print("consulta uma habitualidade de verdade para conferir se os nomes de")
    print("campo do código batem com a resposta real -- imprimindo só os nomes")
    print("dos campos e as quantidades, nunca os valores.")
    print()
    print("Use o SEU CPF, não o de um cliente. O que você digitar não aparece")
    print("na tela nem fica no histórico do terminal. Enter em branco pula.")
    cpf = _limpar_cpf(getpass("CPF (só números, não aparece ao digitar): "))
    print()

    if not cpf:
        print("Pulado. A conferência de credencial e ambiente acima já está feita.")
        return
    if len(cpf) != 11:
        print("CPF precisa ter 11 dígitos. Nada foi consultado.")
        return

    _conferir_habitualidade(cpf)
    print()
    print("Fim. Me mostre esta saída -- ela não contém dado de ninguém.")


if __name__ == "__main__":
    main()
