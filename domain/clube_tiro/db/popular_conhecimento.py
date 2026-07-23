"""Popula a base de conhecimento (FAQ institucional) do Domínio Clube de
Tiro com perguntas frequentes. Conteúdo legal/regulatório sensível -- por
isso todas as entradas nascem com aprovado='Não'. O sistema só usa
conhecimento aprovado (ver motor_ia/consultor.py), então nada disso
chega a um cliente real até alguém do clube revisar e aprovar cada
entrada (ver domain/clube_tiro/db/aprovar_conhecimento.py).
"""
import sqlite3
from datetime import datetime, timezone

DB_PATH = "domain/clube_tiro/db/dominio_clube_tiro.db"


def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


PERGUNTAS = [
    ("CR", "O que é o CR?",
     "O CR (Certificado de Registro) é o documento que autoriza uma pessoa a "
     "possuir e manter armas de fogo em sua residência ou local de trabalho, "
     "conforme os requisitos previstos na legislação vigente."),
    ("CR", "Por quanto tempo o CR é válido?",
     "O prazo de validade do CR varia conforme a categoria (caçador, atirador "
     "ou colecionador) e a legislação vigente no momento da emissão ou "
     "renovação. Consulte nossa equipe para confirmar o prazo aplicável ao "
     "seu caso."),
    ("CR", "Quais categorias de CR existem?",
     "As categorias mais comuns são Colecionador, Atirador e Caçador (CAC), "
     "cada uma com requisitos e finalidades específicas. Fale com nossa "
     "equipe para entender qual se aplica ao seu perfil."),
    ("CRAF", "O que é o CRAF?",
     "O CRAF (Certificado de Registro de Arma de Fogo) é o documento que "
     "registra formalmente uma arma de fogo específica em nome do seu "
     "proprietário -- diferente do CR, que autoriza a pessoa, não a arma."),
    ("Habitualidade", "O que é habitualidade e por que ela é exigida?",
     "Habitualidade é a comprovação de que o atirador pratica tiro com a "
     "regularidade mínima exigida pela legislação, geralmente através de "
     "registros de participação em treinos e competições no clube. Costuma "
     "ser exigida para renovação do CR na categoria de atirador."),
    ("Habitualidade", "Como faço para comprovar minha habitualidade?",
     "A comprovação é feita através dos registros de participação em eventos "
     "e treinos registrados pelo clube. Nossa equipe pode te ajudar a "
     "consultar seu histórico de participações."),
    ("Aquisição", "Como funciona o processo de aquisição de uma arma de fogo?",
     "O processo de aquisição envolve autorização prévia junto ao órgão "
     "competente, apresentação de documentação pessoal e comprovação de "
     "capacidade técnica e psicológica, entre outros requisitos. Nossa "
     "equipe acompanha esse processo com você."),
    ("Transferência", "Posso transferir uma arma para outra pessoa?",
     "Sim, é possível transferir a propriedade de uma arma de fogo para "
     "outra pessoa habilitada, mediante processo formal de transferência "
     "junto ao órgão competente, com documentação de ambas as partes."),
    ("Guias", "O que é a guia de tráfego de arma de fogo?",
     "A guia de tráfego é o documento que autoriza o transporte da arma de "
     "fogo desmuniciada entre a residência do proprietário e locais como "
     "clubes de tiro, para a prática de atividades autorizadas."),
    ("Legislação", "A legislação sobre armas de fogo muda com frequência?",
     "Sim, a legislação sobre posse e propriedade de armas de fogo no Brasil "
     "pode sofrer alterações por decretos e normativas. Recomendamos sempre "
     "confirmar informações atualizadas com nossa equipe antes de tomar "
     "decisões."),
]


def main():
    con = sqlite3.connect(DB_PATH)
    try:
        maior = con.execute(
            "SELECT MAX(CAST(SUBSTR(conhecimento_id, 5) AS INTEGER)) FROM conhecimento"
        ).fetchone()[0] or 0

        agora = _agora_iso()
        linhas = [
            (f"KNW-{maior + i + 1:06d}", categoria, pergunta, resposta, "Não", "Sim", agora)
            for i, (categoria, pergunta, resposta) in enumerate(PERGUNTAS)
        ]
        con.executemany(
            "INSERT INTO conhecimento VALUES (?,?,?,?,?,?,?)", linhas
        )
        con.commit()
        print(f"{len(linhas)} perguntas inseridas, todas com aprovado='Não'.")
        print("Revise o conteúdo e aprove cada uma antes do sistema usá-las "
              "com clientes reais (ver domain/clube_tiro/db/aprovar_conhecimento.py).")
    finally:
        con.close()


if __name__ == "__main__":
    main()
