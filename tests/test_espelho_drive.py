"""Cópia dos documentos numa pasta por cliente no Google Drive.

Nenhum teste fala com o Google: as quatro operações do Drive são
trocadas por um Drive de mentira que só anota o que pediram a ele. O que
se confere é a regra: cada arquivo na pasta do dono certo, nada duas
vezes, nada de outra empresa, e falha de um arquivo não trava a fila.
"""
import pytest

from core.conexao import conectar
from integracoes import espelho_documentos_drive as espelho
from integracoes import google_drive

from tests.conftest import EMPRESA_A


class DriveDeMentira:
    def __init__(self):
        self.pastas = {}          # id -> {"nome", "pai"}
        self.arquivos = {}        # id -> {"nome", "pasta"}
        self.apagadas = set()
        self.falhar_em = set()    # nomes de arquivo que dão erro ao subir
        self._n = 0

    def _id(self, prefixo):
        self._n += 1
        return f"{prefixo}{self._n}"

    def pasta_utilizavel(self, servico, pasta_id):
        return pasta_id in self.pastas and pasta_id not in self.apagadas

    def criar_pasta(self, servico, nome, pai_id=None):
        novo = self._id("pasta")
        self.pastas[novo] = {"nome": nome, "pai": pai_id}
        return novo

    def renomear(self, servico, arquivo_id, nome):
        self.pastas[arquivo_id]["nome"] = nome

    def enviar_arquivo(self, servico, caminho, nome, pasta_id, mimetype):
        if any(trecho in nome for trecho in self.falhar_em):
            raise RuntimeError("Drive recusou")
        novo = self._id("arq")
        self.arquivos[novo] = {"nome": nome, "pasta": pasta_id, "conteudo": caminho.read_bytes()}
        return novo

    def pasta_por_nome(self, nome):
        return next(i for i, p in self.pastas.items() if p["nome"] == nome)

    def arquivos_na(self, nome_pasta):
        pasta = self.pasta_por_nome(nome_pasta)
        return [a for a in self.arquivos.values() if a["pasta"] == pasta]


@pytest.fixture
def drive(banco, monkeypatch):
    falso = DriveDeMentira()
    monkeypatch.setattr(google_drive, "drive_configurado", lambda: True)
    monkeypatch.setattr(google_drive, "servico", lambda: object())
    for nome in ("pasta_utilizavel", "criar_pasta", "renomear", "enviar_arquivo"):
        monkeypatch.setattr(google_drive, nome, getattr(falso, nome))
    return falso


def test_cada_documento_vai_para_a_pasta_do_seu_cliente(drive):
    saida = espelho.espelhar(EMPRESA_A)

    assert saida["enviados"] == 2
    raiz = drive.pasta_por_nome(espelho.PASTA_RAIZ)
    assert drive.pastas[drive.pasta_por_nome("Ana Teste (CLI-000001)")]["pai"] == raiz
    da_ana = drive.arquivos_na("Ana Teste (CLI-000001)")
    do_bruno = drive.arquivos_na("Bruno Teste (CLI-000002)")
    assert [a["conteudo"] for a in da_ana] == [b"%PDF-1.4 conteudo secreto do cliente A"]
    assert [a["conteudo"] for a in do_bruno] == [b"%PDF-1.4 conteudo secreto do cliente B"]
    assert da_ana[0]["nome"] == "2026-07-28 - RG (DOC-000001).pdf"


def test_nada_sobe_duas_vezes(drive):
    espelho.espelhar(EMPRESA_A)

    segunda = espelho.espelhar(EMPRESA_A)

    assert segunda["enviados"] == 0
    assert len(drive.arquivos) == 2
    assert len(drive.pastas) == 3  # raiz + Ana + Bruno, sem pasta repetida


def test_documento_de_outra_empresa_nao_entra(drive):
    espelho.espelhar(EMPRESA_A)

    nomes = [p["nome"] for p in drive.pastas.values()]
    assert not any("Carla" in n for n in nomes)
    assert all(a["conteudo"] != b"%PDF-1.4 conteudo secreto da empresa B" for a in drive.arquivos.values())


def test_nome_do_cliente_mudou_a_pasta_e_renomeada(drive, painel):
    espelho.espelhar(EMPRESA_A)
    pasta_ana = drive.pasta_por_nome("Ana Teste (CLI-000001)")
    con = conectar(EMPRESA_A)
    con.execute("UPDATE cliente SET nome = 'Ana Teste Souza' WHERE cliente_id = 'CLI-000001'")
    con.commit()
    con.close()

    # Documento novo da Ana é o que faz a rodada passar pela pasta dela.
    painel.post("/api/casos/CAS-000001/documentos", data={
        "arquivo": (__import__("io").BytesIO(b"%PDF-1.4 novo"), "novo.pdf"),
    }, content_type="multipart/form-data")
    espelho.espelhar(EMPRESA_A)

    assert drive.pastas[pasta_ana]["nome"] == "Ana Teste Souza (CLI-000001)"
    assert len(drive.arquivos_na("Ana Teste Souza (CLI-000001)")) == 2


def test_pasta_apagada_no_drive_e_criada_de_novo(drive, painel):
    espelho.espelhar(EMPRESA_A)
    drive.apagadas.add(drive.pasta_por_nome("Ana Teste (CLI-000001)"))

    painel.post("/api/casos/CAS-000001/documentos", data={
        "arquivo": (__import__("io").BytesIO(b"%PDF-1.4 novo"), "novo.pdf"),
    }, content_type="multipart/form-data")
    espelho.espelhar(EMPRESA_A)

    pastas_da_ana = [i for i, p in drive.pastas.items()
                     if p["nome"] == "Ana Teste (CLI-000001)" and i not in drive.apagadas]
    assert len(pastas_da_ana) == 1


def test_falha_de_um_arquivo_nao_para_os_outros_e_ele_tenta_de_novo(drive):
    drive.falhar_em.add("DOC-000001")

    primeira = espelho.espelhar(EMPRESA_A)
    assert primeira["enviados"] == 1 and primeira["falhas"] == 1

    drive.falhar_em.clear()
    segunda = espelho.espelhar(EMPRESA_A)
    assert segunda["enviados"] == 1
    assert len(drive.arquivos_na("Ana Teste (CLI-000001)")) == 1


def test_linha_sem_arquivo_no_disco_nao_conta_como_falha_do_drive(drive, banco):
    banco["arquivo_a"].unlink()

    saida = espelho.espelhar(EMPRESA_A)

    assert saida == {"enviados": 1, "falhas": 0, "sem_arquivo": 1, "faltando": 0}


def test_apagar_no_painel_nao_apaga_a_copia_no_drive(drive, painel):
    """A cópia é de segurança: um clique errado no painel não leva junto."""
    espelho.espelhar(EMPRESA_A)

    assert painel.post("/api/documentos/DOC-000001/excluir").status_code == 200

    assert len(drive.arquivos_na("Ana Teste (CLI-000001)")) == 1
    con = conectar(EMPRESA_A)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM drive_documento WHERE documento_id = 'DOC-000001'"
        ).fetchone()[0] == 1
    finally:
        con.close()


def test_sem_drive_autorizado_a_rodada_avisa(banco, monkeypatch):
    monkeypatch.setattr(google_drive, "drive_configurado", lambda: False)

    with pytest.raises(RuntimeError):
        espelho.espelhar(EMPRESA_A)


def test_modulo_nao_tem_comando_de_terminal():
    """Rodado no PC, mandaria os documentos do banco LOCAL para o mesmo
    Drive da produção, misturando os dois."""
    from pathlib import Path

    codigo = Path(espelho.__file__).read_text(encoding="utf-8")
    assert '__name__ == "__main__"' not in codigo
