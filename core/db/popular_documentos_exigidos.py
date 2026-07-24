"""Popula o checklist detalhado de documentos por serviço (tabela
documento_exigido) com as listas reais que o usuário passou em 2026-07-24
para CR, CRAF, Aquisição de arma, Transferência e Guia de Tráfego.

Cria também os 3 serviços que ainda não existiam (CRAF, Aquisição de
Arma, Guia de Tráfego) -- até aqui só existiam Renovação do CR, Primeiro
CR, Apostilamento e Transferência. Decisões confirmadas com o usuário:
- a lista de "CR" vale igualmente para Renovação do CR e Primeiro CR;
- Apostilamento fica sem checklist por enquanto (não veio na lista dele);
- prazo_estimado_dias/valor_referencia dos 3 serviços novos ficam NULL
  (nunca inventar prazo/valor -- mesmo princípio do Redator) até o
  usuário informar; VW_SERVICO trata NULL com um texto "a confirmar" em
  vez de quebrar.

Idempotente: pode rodar de novo sem duplicar (verifica por service_key
antes de criar serviço, e por servico_id antes de inserir checklist).
"""
from core.conexao import conectar

SERVICOS_NOVOS = [
    # (service_key, nome_servico, descricao, categoria)
    ("craf", "CRAF", "Emissão do CRAF (Certificado de Registro de Arma de Fogo).", "CRAF"),
    ("aquisicao_arma", "Aquisição de Arma", "Aquisição de uma arma de fogo nova.", "Aquisição"),
    ("guia_trafego", "Guia de Tráfego", "Guia de tráfego para transporte da arma entre residência e clube.", "Regularização documental"),
]

# service_key -> resumo curto (semicolon), usado em servico.documentos_obrigatorios
# (mantém o catálogo geral funcionando; a lista completa fica em documento_exigido).
DIGEST_CURTO = {
    "renovacao_cr": "RG; comprovante de residência; comprovante de ocupação lícita; "
        "certidões de antecedentes criminais; declarações de acervo seguro e ausência "
        "de processo; laudo de aptidão psicológica; comprovante de capacidade técnica; "
        "filiação a clube de tiro; taxa federal paga.",
    "primeiro_cr": "RG; comprovante de residência; comprovante de ocupação lícita; "
        "certidões de antecedentes criminais; declarações de acervo seguro e ausência "
        "de processo; laudo de aptidão psicológica; comprovante de capacidade técnica; "
        "filiação a clube de tiro; taxa federal paga.",
    "transferencia_arma": "CR e CRAF válidos (vendedor e comprador); laudos de aptidão "
        "psicológica e capacidade técnica do comprador; declarações de ocupação lícita, "
        "residência fixa e DSA; comprovante de atividade em treinos/competições; taxa de "
        "registro.",
    "craf": "Autorização de compra; nota fiscal da arma; comprovante da GRU; RG; CPF; "
        "comprovante de residência; certidões de antecedentes criminais.",
    "aquisicao_arma": "Autorização de compra; CR válido; laudos de aptidão psicológica e "
        "capacidade técnica; certidões de antecedentes criminais; declarações de ocupação "
        "lícita, residência fixa e DSA; termo de compromisso de treinos.",
    "guia_trafego": "Documento de identificação com foto (RG ou CNH); CPF; CRAF válido da arma.",
}

# service_key -> [(grupo|None, item), ...] em ordem de exibição
CHECKLISTS = {
    "cr": [  # aplicado a renovacao_cr E primeiro_cr
        ("Documentos Pessoais e Residenciais", "Documento de identificação pessoal."),
        ("Documentos Pessoais e Residenciais", "Comprovante de residência fixa atual e dos últimos 5 anos."),
        ("Documentos Pessoais e Residenciais", "Comprovante de ocupação lícita (contrato de trabalho, holerite ou declaração de rendimentos)."),
        ("Certidões e Declarações", "Certidões de antecedentes criminais das Justiças Federal, Estadual, Militar e Eleitoral."),
        ("Certidões e Declarações", "Declaração de que não responde a inquérito policial ou processo criminal."),
        ("Certidões e Declarações", "Declaração de segurança do acervo, atestando local seguro ou cofre para guardar as armas."),
        ("Laudos e Comprovantes Específicos", "Laudo de aptidão psicológica emitido por psicólogo credenciado pela Polícia Federal."),
        ("Laudos e Comprovantes Específicos", "Comprovante de capacidade técnica para manuseio de arma emitido por instrutor credenciado."),
        ("Laudos e Comprovantes Específicos", "Comprovante de filiação a clube de tiro ou entidade de caça (obrigatório para atiradores e caçadores)."),
        ("Laudos e Comprovantes Específicos", "Comprovante de pagamento da taxa federal correspondente."),
    ],
    "craf": [
        ("Documentos Necessários", "Autorização de compra: documento prévio que permitiu adquirir o armamento."),
        ("Documentos Necessários", "Nota fiscal: comprovante fiscal emitido pela loja com os dados da arma."),
        ("Documentos Necessários", "Taxa paga: comprovante da Guia de Recolhimento da União (GRU) referente ao registro."),
        ("Documentos Necessários", "Documentos pessoais: RG, CPF e comprovante de residência atualizados."),
        ("Documentos Necessários", "Certidão de Antecedentes: certidões negativas criminais (federal, estadual, eleitoral e militar)."),
        ("Requisitos e Prazos", "Idade mínima: ter pelo menos 25 anos completos para defesa pessoal."),
        ("Requisitos e Prazos", "Laudos obrigatórios: teste psicológico e laudo de capacidade técnica de tiro, ambos emitidos por profissionais credenciados pela Polícia Federal."),
        ("Requisitos e Prazos", "Prazo de validade: o documento vale por 5 anos para defesa residencial/trabalho ou 3 anos para atiradores e colecionadores (CACs)."),
    ],
    "aquisicao_arma": [
        ("Documentos Necessários", "Autorização de compra."),
        ("Documentos Necessários", "CR válido: Certificado de Registro ativo para ambos."),
        ("Documentos Necessários", "Laudos: Aptidão psicológica e capacidade técnica emitidos por credenciados da Polícia Federal."),
        ("Documentos Necessários", "Certidões de antecedentes criminais das Justiças Federal, Estadual, Militar e Eleitoral."),
        ("Documentos Necessários", "Declarações: Comprovação de ocupação lícita, residência fixa, e Declaração de Segurança do Acervo (DSA) sobre o cofre."),
        ("Documentos Necessários", "Termo de compromisso de participação em treinos."),
    ],
    "transferencia_arma": [
        ("Requisitos para o Vendedor e o Comprador", "CR válido: Certificado de Registro ativo para ambos."),
        ("Requisitos para o Vendedor e o Comprador", "CRAF válido: Documento da arma em dia."),
        ("Requisitos para o Vendedor e o Comprador", "Limite do acervo: O comprador não pode ultrapassar o limite de armas do seu nível (1, 2 ou 3)."),
        ("Documentos do Comprador (Adquirente)", "Laudos: Aptidão psicológica e capacidade técnica emitidos por credenciados da Polícia Federal."),
        ("Documentos do Comprador (Adquirente)", "Declarações: Comprovação de ocupação lícita, residência fixa, e Declaração de Segurança do Acervo (DSA) sobre o cofre."),
        ("Documentos do Comprador (Adquirente)", "Atividade: Documento que comprove participação em treinamentos ou competições de tiro desportivo."),
        ("Documentos do Comprador (Adquirente)", "Taxa: Comprovante de pagamento da taxa de registro correspondente (gerada pelo sistema do Exército/PF)."),
    ],
    "guia_trafego": [
        (None, "Documento de identificação pessoal com foto (RG ou CNH) e CPF."),
        (None, "CRAF válido: Documento da arma em dia."),
    ],
}

# checklist "cr" se aplica a estes 2 service_key (mesma lista pros dois,
# decisão confirmada com o usuário).
CHECKLIST_CR_APLICA_A = ["renovacao_cr", "primeiro_cr"]


def _proximo_service_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(service_id, 5) AS INTEGER)) FROM servico"
    ).fetchone()[0] or 0
    return f"SER-{maior + 1:06d}"


def _proximo_dex_id(con) -> str:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(documento_exigido_id, 5) AS INTEGER)) FROM documento_exigido"
    ).fetchone()[0] or 0
    return f"DEX-{maior + 1:06d}"


def _garantir_servicos_novos(con) -> None:
    for service_key, nome, descricao, categoria in SERVICOS_NOVOS:
        existe = con.execute(
            "SELECT 1 FROM servico WHERE service_key = ?", (service_key,)
        ).fetchone()
        if existe:
            continue
        novo_id = _proximo_service_id(con)
        con.execute(
            "INSERT INTO servico VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                novo_id, service_key, nome, descricao, categoria,
                None, None, DIGEST_CURTO[service_key], "Sim", None,
            ),
        )
        print(f"Serviço criado: {novo_id} -- {nome}")


def _atualizar_digest_existentes(con) -> None:
    for service_key in ("renovacao_cr", "primeiro_cr", "transferencia_arma"):
        con.execute(
            "UPDATE servico SET documentos_obrigatorios = ? WHERE service_key = ?",
            (DIGEST_CURTO[service_key], service_key),
        )
    print("Resumo curto (documentos_obrigatorios) atualizado para CR/Transferência.")


def _inserir_checklist(con, service_key: str, itens: list) -> None:
    servico_id = con.execute(
        "SELECT service_id FROM servico WHERE service_key = ?", (service_key,)
    ).fetchone()
    if not servico_id:
        raise ValueError(f"Serviço não encontrado: {service_key}")
    servico_id = servico_id[0]

    ja_tem = con.execute(
        "SELECT 1 FROM documento_exigido WHERE servico_id = ?", (servico_id,)
    ).fetchone()
    if ja_tem:
        print(f"Checklist de {service_key} ({servico_id}) já existe -- pulando.")
        return

    for ordem, (grupo, item) in enumerate(itens, start=1):
        novo_id = _proximo_dex_id(con)
        con.execute(
            "INSERT INTO documento_exigido VALUES (?,?,?,?,?,?)",
            (novo_id, servico_id, grupo, item, ordem, "Sim"),
        )
    print(f"{len(itens)} itens de checklist inseridos para {service_key} ({servico_id}).")


def main():
    con = conectar()
    try:
        _garantir_servicos_novos(con)
        _atualizar_digest_existentes(con)

        for service_key in CHECKLIST_CR_APLICA_A:
            _inserir_checklist(con, service_key, CHECKLISTS["cr"])
        for service_key in ("craf", "aquisicao_arma", "transferencia_arma", "guia_trafego"):
            _inserir_checklist(con, service_key, CHECKLISTS[service_key])

        con.commit()
        print("Concluído.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
