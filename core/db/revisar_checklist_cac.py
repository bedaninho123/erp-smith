"""Revisão das listas de documento exigido por serviço (2026-08-27).

As listas de 2026-07-24 (`popular_documentos_exigidos.py`) vieram do
usuário e continuam sendo a origem desta revisão. Quatro problemas
apareceram usando o sistema:

1. **Guia de Tráfego tinha 2 itens** -- faltava quase tudo.
2. **Apostilamento estava vazio.**
3. **CRAF misturava documento com requisito.** "Idade mínima: 25 anos" e
   "Prazo de validade: 5 anos" não são arquivos que alguém anexa; eram
   itens de checklist que nunca poderiam ser marcados como recebidos, e
   por isso a contagem X/Y de um processo nunca fechava.
4. **Renovação do CR era idêntica ao Primeiro CR.** Foi decisão
   consciente em julho, mas renovação não pede comprovante de residência
   dos últimos 5 anos -- pede habitualidade do período.

A separação que este arquivo introduz, e que é o ponto dele: **grupo
"Requisitos (conferir, não coletar)"**. O que está nesse grupo é
condição a verificar, não arquivo a receber. Sem essa distinção o
checklist de um processo mistura duas coisas que se comportam de forma
diferente -- uma recebe PDF, a outra recebe um "sim, conferi".

ATENÇÃO, e isto não é formalidade: **estas listas são um rascunho para o
despachante revisar.** A regra do CAC muda (Decreto nº 11.615/2023 e
alterações posteriores), varia por SFPC e por nível de CR, e quem faz
isso todo dia é o usuário, não este código. Os itens marcados com
`CONFERIR` no comentário são os que mais mudam.

Idempotente: apaga o checklist ANTIGO dos serviços que revisa e insere o
novo. Não toca em serviço que não está aqui.

    .venv\\Scripts\\python.exe -m core.db.revisar_checklist_cac
"""
import sys

from core.conexao import conectar
from core.motor_empresas import EMPRESA_PADRAO, exigir_empresa

DOCUMENTOS = "Documentos a coletar"
CONFERIR = "Requisitos (conferir, não coletar)"

# service_key -> [(grupo, item), ...]
CHECKLISTS = {
    # ------------------------------------------------------------------
    "renovacao_cr": [
        (DOCUMENTOS, "Documento de identidade com foto (RG ou CNH) e CPF."),
        (DOCUMENTOS, "Comprovante de residência atual."),
        (DOCUMENTOS, "Comprovante de ocupação lícita (holerite, contrato, declaração de rendimentos ou contrato social)."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Federal."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Estadual."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Militar."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Eleitoral."),
        (DOCUMENTOS, "Laudo de aptidão psicológica emitido por psicólogo credenciado pela Polícia Federal."),
        # CONFERIR: em parte dos SFPC a capacidade técnica é dispensada na
        # renovação quando há habitualidade comprovada no período.
        (DOCUMENTOS, "Laudo de capacidade técnica emitido por instrutor credenciado."),
        (DOCUMENTOS, "Declaração de habitualidade emitida pelo clube, com as participações do período."),
        (DOCUMENTOS, "Comprovante de filiação ao clube de tiro (declaração de vínculo ativo)."),
        (DOCUMENTOS, "Declaração de Segurança do Acervo (DSA), atestando cofre ou local seguro."),
        (DOCUMENTOS, "Comprovante de pagamento da taxa (GRU)."),
        (DOCUMENTOS, "Requerimento de renovação preenchido e assinado."),
        (CONFERIR, "CR ainda dentro da validade — renovar antes de vencer evita reentrada do processo."),
        (CONFERIR, "Habitualidade mínima do nível do CR cumprida no período."),
        (CONFERIR, "Acervo dentro do limite do nível (1, 2 ou 3)."),
        (CONFERIR, "CRAFs do acervo em dia — arma irregular trava a renovação."),
    ],
    # ------------------------------------------------------------------
    "primeiro_cr": [
        (DOCUMENTOS, "Documento de identidade com foto (RG ou CNH) e CPF."),
        (DOCUMENTOS, "Comprovante de residência fixa atual."),
        (DOCUMENTOS, "Comprovante de ocupação lícita (holerite, contrato, declaração de rendimentos ou contrato social)."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Federal."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Estadual."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Militar."),
        (DOCUMENTOS, "Certidão negativa criminal da Justiça Eleitoral."),
        (DOCUMENTOS, "Declaração de que não responde a inquérito policial ou processo criminal."),
        (DOCUMENTOS, "Laudo de aptidão psicológica emitido por psicólogo credenciado pela Polícia Federal."),
        (DOCUMENTOS, "Laudo de capacidade técnica emitido por instrutor credenciado."),
        (DOCUMENTOS, "Comprovante de filiação ao clube de tiro (declaração de vínculo ativo)."),
        (DOCUMENTOS, "Declaração de Segurança do Acervo (DSA), atestando cofre ou local seguro."),
        (DOCUMENTOS, "Comprovante de pagamento da taxa (GRU)."),
        (DOCUMENTOS, "Foto 3x4 recente."),
        (DOCUMENTOS, "Requerimento de registro preenchido e assinado."),
        (CONFERIR, "Idade mínima cumprida."),
        (CONFERIR, "Nível de CR pretendido definido — ele decide limite de acervo e habitualidade exigida."),
    ],
    # ------------------------------------------------------------------
    "craf": [
        (DOCUMENTOS, "CR do adquirente, válido."),
        (DOCUMENTOS, "Documento de identidade com foto (RG ou CNH) e CPF."),
        (DOCUMENTOS, "Comprovante de residência atual."),
        (DOCUMENTOS, "Autorização de compra que permitiu adquirir o armamento."),
        (DOCUMENTOS, "Nota fiscal da arma, com marca, modelo, calibre e número de série."),
        # CONFERIR: doação, herança e transferência entram aqui no lugar
        # da nota fiscal -- o documento de origem muda conforme o caso.
        (DOCUMENTOS, "Documento de origem, quando não houver nota fiscal (doação, herança ou transferência)."),
        (DOCUMENTOS, "Comprovante de pagamento da taxa (GRU) do registro."),
        (DOCUMENTOS, "Termo de responsabilidade assinado."),
        (CONFERIR, "Acervo dentro do limite do nível do CR."),
        (CONFERIR, "Calibre permitido para o nível do CR do adquirente."),
        (CONFERIR, "Dados da arma conferem entre nota fiscal, autorização e requerimento — divergência de número de série reprova."),
    ],
    # ------------------------------------------------------------------
    "guia_trafego": [
        (DOCUMENTOS, "CR válido."),
        (DOCUMENTOS, "CRAF válido de cada arma que vai trafegar."),
        (DOCUMENTOS, "Documento de identidade com foto (RG ou CNH) e CPF."),
        (DOCUMENTOS, "Comprovante de filiação ao clube de tiro (declaração de vínculo ativo)."),
        (DOCUMENTOS, "Declaração de habitualidade do clube, quando o trajeto for para treino."),
        (DOCUMENTOS, "Requerimento com origem, destino e período do trânsito."),
        (DOCUMENTOS, "Comprovante de pagamento da taxa (GRU), quando aplicável."),
        (DOCUMENTOS, "Comprovante de inscrição no campeonato, quando o trajeto for para competição."),
        (CONFERIR, "Guia é POR ARMA — conferir se todas as armas do trajeto estão no pedido."),
        (CONFERIR, "Trajeto e período declarados cobrem a viagem inteira, ida e volta."),
        (CONFERIR, "CRAF de cada arma dentro da validade na data do trânsito."),
    ],
    # ------------------------------------------------------------------
    "transferencia_arma": [
        ("Documentos do vendedor", "CR do vendedor, válido."),
        ("Documentos do vendedor", "CRAF da arma, válido e em nome do vendedor."),
        ("Documentos do vendedor", "Documento de identidade com foto (RG ou CNH) e CPF."),
        ("Documentos do vendedor", "Autorização de transferência assinada pelo vendedor."),
        ("Documentos do comprador", "CR do comprador, válido."),
        ("Documentos do comprador", "Documento de identidade com foto (RG ou CNH) e CPF."),
        ("Documentos do comprador", "Comprovante de residência atual."),
        ("Documentos do comprador", "Comprovante de ocupação lícita."),
        ("Documentos do comprador", "Certidões negativas criminais (Federal, Estadual, Militar e Eleitoral)."),
        ("Documentos do comprador", "Laudo de aptidão psicológica dentro da validade."),
        ("Documentos do comprador", "Laudo de capacidade técnica dentro da validade."),
        ("Documentos do comprador", "Declaração de Segurança do Acervo (DSA)."),
        ("Documentos do comprador", "Comprovante de pagamento da taxa (GRU) da transferência."),
        (CONFERIR, "Acervo do comprador dentro do limite do nível dele."),
        (CONFERIR, "Calibre permitido para o nível do CR do comprador."),
        (CONFERIR, "Arma sem restrição, penhora ou registro de ocorrência."),
        (CONFERIR, "Número de série confere entre CRAF, autorização e requerimento."),
    ],
    # ------------------------------------------------------------------
    "aquisicao_arma": [
        (DOCUMENTOS, "CR válido."),
        (DOCUMENTOS, "Documento de identidade com foto (RG ou CNH) e CPF."),
        (DOCUMENTOS, "Comprovante de residência atual."),
        (DOCUMENTOS, "Comprovante de ocupação lícita."),
        (DOCUMENTOS, "Certidões negativas criminais (Federal, Estadual, Militar e Eleitoral)."),
        (DOCUMENTOS, "Laudo de aptidão psicológica dentro da validade."),
        (DOCUMENTOS, "Laudo de capacidade técnica dentro da validade."),
        (DOCUMENTOS, "Declaração de Segurança do Acervo (DSA)."),
        (DOCUMENTOS, "Declaração de habitualidade do clube."),
        (DOCUMENTOS, "Comprovante de pagamento da taxa (GRU)."),
        (DOCUMENTOS, "Requerimento de autorização de compra, com marca, modelo e calibre pretendidos."),
        (CONFERIR, "Acervo dentro do limite do nível — aquisição que estoura o limite é indeferida."),
        (CONFERIR, "Calibre pretendido permitido para o nível do CR."),
        (CONFERIR, "Habitualidade em dia, quando o nível exigir."),
    ],
    # ------------------------------------------------------------------
    # Apostilamento estava sem checklist desde julho. É a averbação de
    # alteração no CRAF (mudança de característica da arma, correção de
    # dado, mudança de acervo).
    "apostilamento": [
        (DOCUMENTOS, "CR válido."),
        (DOCUMENTOS, "CRAF atual da arma."),
        (DOCUMENTOS, "Documento de identidade com foto (RG ou CNH) e CPF."),
        (DOCUMENTOS, "Requerimento indicando exatamente o que deve ser alterado ou corrigido."),
        (DOCUMENTOS, "Documento que comprova a alteração (nota fiscal da peça, laudo técnico ou documento com o dado correto)."),
        (DOCUMENTOS, "Comprovante de pagamento da taxa (GRU), quando aplicável."),
        (CONFERIR, "A alteração pretendida é permitida para o nível do CR."),
        (CONFERIR, "Dado a corrigir confere com o documento de origem da arma."),
    ],
}


def _proximo_numero(con) -> int:
    maior = con.execute(
        "SELECT MAX(CAST(SUBSTR(documento_exigido_id, 5) AS INTEGER)) FROM documento_exigido"
    ).fetchone()[0] or 0
    return maior + 1


def revisar(empresa_id: str) -> dict:
    con = conectar(empresa_id)
    try:
        saida = {"servicos": [], "nao_encontrados": [], "itens": 0}
        numero = _proximo_numero(con)

        for chave, itens in CHECKLISTS.items():
            servico = con.execute(
                "SELECT service_id, nome_servico FROM servico "
                "WHERE empresa_id = ? AND service_key = ?",
                (empresa_id, chave),
            ).fetchone()
            if not servico:
                saida["nao_encontrados"].append(chave)
                continue

            antes = con.execute(
                "SELECT COUNT(*) FROM documento_exigido WHERE empresa_id = ? AND servico_id = ?",
                (empresa_id, servico["service_id"]),
            ).fetchone()[0]
            # Apaga o checklist antigo DESTE serviço e insere o revisado.
            # É o que torna o script idempotente -- rodar duas vezes deixa
            # o mesmo resultado, em vez de duplicar 18 itens.
            con.execute(
                "DELETE FROM documento_exigido WHERE empresa_id = ? AND servico_id = ?",
                (empresa_id, servico["service_id"]),
            )
            for ordem, (grupo, item) in enumerate(itens, start=1):
                con.execute(
                    "INSERT INTO documento_exigido (documento_exigido_id, empresa_id, "
                    "servico_id, grupo, item, ordem, ativo) VALUES (?,?,?,?,?,?,'Sim')",
                    (f"DEX-{numero:06d}", empresa_id, servico["service_id"],
                     grupo, item, ordem),
                )
                numero += 1

            saida["servicos"].append({
                "nome": servico["nome_servico"], "antes": antes, "depois": len(itens),
                "coletar": sum(1 for g, _ in itens if g != CONFERIR),
                "conferir": sum(1 for g, _ in itens if g == CONFERIR),
            })
            saida["itens"] += len(itens)

        con.commit()
        return saida
    finally:
        con.close()


def main() -> int:
    empresa_id = sys.argv[1] if len(sys.argv) > 1 else EMPRESA_PADRAO
    exigir_empresa(empresa_id)

    saida = revisar(empresa_id)
    print(f"Checklist revisado para {empresa_id}:\n")
    for servico in saida["servicos"]:
        print(f"  {servico['nome']:<24} {servico['antes']:>2} -> {servico['depois']:>2} itens "
              f"({servico['coletar']} a coletar, {servico['conferir']} a conferir)")
    if saida["nao_encontrados"]:
        print(f"\n  Serviços não encontrados nesta empresa: {saida['nao_encontrados']}")
    print(f"\n  Total: {saida['itens']} itens.")
    print()
    print("  ESTAS LISTAS SÃO UM RASCUNHO PARA VOCÊ REVISAR. A regra do CAC muda,")
    print("  varia por SFPC e por nível de CR -- quem faz isso todo dia é você.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
