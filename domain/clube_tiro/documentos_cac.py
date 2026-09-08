"""Os tipos de documento que um CAC guarda, para o dossiê do cliente.

Vive no Domínio porque é vocabulário de clube de tiro: um escritório de
advocacia não tem CRAF nem guia de tráfego. O Core não sabe que este
arquivo existe -- `documento.tipo_documento` continua sendo TEXTO livre,
e esta lista é oferecida como SUGESTÃO na tela (mesmo padrão das
modalidades). Quem precisar guardar algo fora da lista continua podendo.

Não confundir com `documento_exigido` (Core): aquilo é o CHECKLIST de um
serviço -- frases de exigência ("Comprovante de residência fixa atual e
dos últimos 5 anos."), boas para conferir se um processo está completo.
Aqui são NOMES de documento, que é o que serve de rótulo de arquivo
guardado.

**A validade é o que faz este dossiê valer dinheiro.** Documento de CAC
vence, e vencer significa serviço para o despachante: CR de atirador
vale 3 anos, laudo psicológico e de capacidade técnica valem 1 ano,
certidão negativa costuma valer 90 dias. `validade_meses` é uma
SUGESTÃO para a tela pré-preencher, nunca uma regra aplicada sozinha --
a data que vale é a que está impressa no documento, e quem digita é
quem está olhando para ele.
"""

# (chave, nome, grupo, validade sugerida em meses ou None, aceita referência)
#
# `referencia` marca o documento que existe MAIS DE UMA VEZ por pessoa e
# precisa dizer de qual item é -- foi o pedido explícito do usuário:
# "CRAF de tal arma". Sem isso, três CRAFs no dossiê ficam
# indistinguíveis.
DOCUMENTOS = (
    # --- Registro e armas -------------------------------------------
    ("cr", "CR — Certificado de Registro", "Registro e armas", 36, False),
    ("craf", "CRAF — Certificado de Registro de Arma de Fogo",
     "Registro e armas", None, True),
    ("guia_trafego", "Guia de Tráfego", "Registro e armas", None, True),
    ("autorizacao_compra", "Autorização de compra", "Registro e armas", None, True),
    ("nota_fiscal_arma", "Nota fiscal da arma", "Registro e armas", None, True),

    # --- Pessoais ----------------------------------------------------
    ("identidade", "Documento de identidade (RG ou CNH)", "Pessoais", None, False),
    ("cpf", "CPF", "Pessoais", None, False),
    ("comprovante_residencia", "Comprovante de residência", "Pessoais", 3, False),
    ("foto", "Foto 3x4", "Pessoais", None, False),

    # --- Laudos ------------------------------------------------------
    ("laudo_psicologico", "Laudo de aptidão psicológica", "Laudos", 12, False),
    ("laudo_tecnico", "Laudo de capacidade técnica", "Laudos", 12, False),

    # --- Certidões ---------------------------------------------------
    # Separadas uma a uma de propósito: são quatro emissões diferentes,
    # em quatro sites diferentes, e vencem em datas diferentes. Guardar
    # como "certidões negativas" num item só esconderia qual está velha.
    ("certidao_federal", "Certidão negativa — Justiça Federal", "Certidões", 3, False),
    ("certidao_estadual", "Certidão negativa — Justiça Estadual", "Certidões", 3, False),
    ("certidao_militar", "Certidão negativa — Justiça Militar", "Certidões", 3, False),
    ("certidao_eleitoral", "Certidão negativa — Justiça Eleitoral", "Certidões", 3, False),

    # --- Declarações e comprovantes ----------------------------------
    ("ocupacao_licita", "Comprovante de ocupação lícita",
     "Declarações e comprovantes", None, False),
    ("dsa", "Declaração de Segurança do Acervo (DSA)",
     "Declarações e comprovantes", None, False),
    ("filiacao_clube", "Comprovante de filiação a clube de tiro",
     "Declarações e comprovantes", 12, False),
    ("taxa_gru", "Comprovante de pagamento de taxa (GRU)",
     "Declarações e comprovantes", None, True),
)

# Quantos dias antes de vencer o documento já entra como "vencendo". Um
# mês é o que dá tempo de tirar certidão nova sem correria.
DIAS_ALERTA_VALIDADE = 30

# A que acervo a arma do documento pertence (2026-09-01) -- pedido do
# usuário, para separar CRAF/guia de tráfego de arma de tiro esportivo
# das de caça e das de coleção. É a mesma ideia de `aceita_referencia`
# acima ("de qual arma"), só que estruturada: uma pessoa pode ter armas
# em mais de um acervo, e um CRAF é sempre de UM acervo só.
#
# Não confundir com a categoria da PESSOA no CR (Atirador/Caçador/
# Colecionador) nem com `useType` da API do Shooting House (Permitido/
# Restrito) -- conferido em 2026-09-01 contra a especificação pública, e
# nenhum dos dois é "a que acervo esta arma pertence". Esta lista é só a
# etiqueta que o despachante escolhe ao guardar o documento, sugestão de
# tela como o resto deste arquivo -- o Core grava o texto sem validar
# contra ela.
FINALIDADES_ARMA = ("Tiro", "Caça", "Coleção")


def catalogo() -> list:
    """A lista pronta para a tela, agrupada e na ordem definida acima --
    que não é alfabética de propósito: começa pelo que o CAC mais
    procura (o CR) e termina no que ele menos mexe."""
    grupos: dict = {}
    for chave, nome, grupo, validade, referencia in DOCUMENTOS:
        grupos.setdefault(grupo, []).append({
            "chave": chave,
            "nome": nome,
            "validade_meses": validade,
            "aceita_referencia": referencia,
        })
    return [{"grupo": nome, "documentos": itens} for nome, itens in grupos.items()]


def nomes() -> list:
    """Só os nomes, para a lista de sugestões do formulário."""
    return [nome for _, nome, _, _, _ in DOCUMENTOS]


def por_nome(nome: str) -> dict:
    """O item do catálogo com este nome, ou None se for algo que a pessoa
    digitou fora da lista -- o que é permitido."""
    for chave, rotulo, grupo, validade, referencia in DOCUMENTOS:
        if rotulo == nome:
            return {"chave": chave, "nome": rotulo, "grupo": grupo,
                    "validade_meses": validade, "aceita_referencia": referencia}
    return None


if __name__ == "__main__":
    print(f"{len(DOCUMENTOS)} tipos de documento em {len(catalogo())} grupos:\n")
    for grupo in catalogo():
        print(f"  {grupo['grupo']}")
        for documento in grupo["documentos"]:
            validade = (f"vale {documento['validade_meses']} meses"
                        if documento["validade_meses"] else "sem validade padrão")
            referencia = " (pede referência: de qual arma)" if documento["aceita_referencia"] else ""
            print(f"    - {documento['nome']}  [{validade}]{referencia}")
