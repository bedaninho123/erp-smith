"""Backup de produção levado ao Google Drive (2026-10-14).

O backup do Railway ficava no mesmo volume do banco, e sem os documentos
dos clientes: perder o volume era perder tudo, backup incluído. O que
este arquivo guarda: (1) o .zip leva bancos, documentos e fotos; (2) a
rotação apaga só o que passou de 14, e só DEPOIS de o novo subir; (3)
sem autorização, nada é tentado. Nenhum teste fala com o Google -- o
Drive aqui é de mentira.
"""
import zipfile
from pathlib import Path

import pytest

from core.db import backup as modulo_backup
from integracoes import google_drive


def test_zip_leva_bancos_documentos_e_fotos(tmp_path, monkeypatch):
    bancos = tmp_path / "20261014_030000"
    bancos.mkdir()
    (bancos / "erp_smith.db").write_bytes(b"banco do core")
    documentos = tmp_path / "documentos"
    (documentos / "CAS-000001").mkdir(parents=True)
    (documentos / "CAS-000001" / "cr.pdf").write_bytes(b"pdf do cliente")
    fotos = tmp_path / "fotos"
    fotos.mkdir()
    (fotos / "anuncio.jpg").write_bytes(b"foto")
    monkeypatch.setattr(modulo_backup, "DOCUMENTOS_DIR", documentos)

    arquivo = modulo_backup.empacotar_para_envio(bancos, tmp_path / "saida.zip", pasta_anuncios=fotos)

    with zipfile.ZipFile(arquivo) as zip_:
        nomes = set(zip_.namelist())
        assert zip_.read("documentos_recebidos/CAS-000001/cr.pdf") == b"pdf do cliente"
    assert nomes == {
        "bancos/erp_smith.db",
        "documentos_recebidos/CAS-000001/cr.pdf",
        "marketplace_fotos/anuncio.jpg",
    }


def test_zip_sem_pasta_de_documentos_nao_quebra(tmp_path, monkeypatch):
    """Instalação nova, nenhum documento recebido ainda: o backup dos
    bancos tem que sair mesmo assim."""
    bancos = tmp_path / "b"
    bancos.mkdir()
    (bancos / "erp_smith.db").write_bytes(b"x")
    monkeypatch.setattr(modulo_backup, "DOCUMENTOS_DIR", tmp_path / "nao_existe")

    arquivo = modulo_backup.empacotar_para_envio(bancos, tmp_path / "s.zip", pasta_anuncios=tmp_path / "nada")

    assert zipfile.ZipFile(arquivo).namelist() == ["bancos/erp_smith.db"]


# --------------------------------------------------------------------
# Rotação no Drive, contra um Drive de mentira
# --------------------------------------------------------------------

class _Chamada:
    def __init__(self, resultado):
        self._resultado = resultado

    def execute(self):
        return self._resultado


class _DriveFalso:
    """Só o pedaço da API que o módulo usa. `existentes` vem do mais novo
    para o mais antigo, como o orderBy='createdTime desc' devolveria."""

    def __init__(self, existentes):
        self.arquivos = list(existentes)
        self.apagados = []
        self.falhar_envio = False

    def files(self):
        return self

    def list(self, q, **_):
        if "mimeType" in q:
            return _Chamada({"files": [{"id": "PASTA"}]})
        return _Chamada({"files": [{"id": n, "name": n} for n in self.arquivos]})

    def create(self, body, media_body=None, fields=None):
        if self.falhar_envio:
            raise ConnectionError("caiu no meio do envio")
        self.arquivos.insert(0, body["name"])
        return _Chamada({"id": body["name"], "size": "2048"})

    def delete(self, fileId):
        self.apagados.append(fileId)
        self.arquivos.remove(fileId)
        return _Chamada({})


@pytest.fixture
def drive_falso(monkeypatch):
    def _instalar(existentes):
        falso = _DriveFalso(existentes)
        monkeypatch.setattr(google_drive, "_servico", lambda: falso)
        monkeypatch.setattr(google_drive, "MediaFileUpload", lambda *a, **k: None)
        return falso
    return _instalar


def test_guarda_os_14_mais_novos_e_apaga_o_resto(drive_falso, tmp_path):
    antigos = [f"backup_{i:02d}.zip" for i in range(14)]  # 00 = mais novo
    falso = drive_falso(antigos)

    saida = google_drive.enviar_backup(tmp_path / "backup_novo.zip", manter_ultimos=14)

    assert falso.arquivos[0] == "backup_novo.zip"
    assert len(falso.arquivos) == 14
    assert saida["apagados"] == ["backup_13.zip"]


def test_envio_que_falha_nao_apaga_nenhum_antigo(drive_falso, tmp_path):
    """A ordem importa: se o novo não subiu, os antigos são o único
    backup que existe."""
    falso = drive_falso([f"backup_{i:02d}.zip" for i in range(14)])
    falso.falhar_envio = True

    with pytest.raises(ConnectionError):
        google_drive.enviar_backup(tmp_path / "backup_novo.zip", manter_ultimos=14)

    assert falso.apagados == []
    assert len(falso.arquivos) == 14


def test_sem_autorizacao_o_drive_nao_e_tentado(tmp_path, monkeypatch):
    monkeypatch.setattr(google_drive, "TOKEN_PATH", tmp_path / "drive_token.json")
    monkeypatch.delenv("ERP_DRIVE_TOKEN_JSON", raising=False)

    assert google_drive.drive_configurado() is False
    assert google_drive.listar_backups() is None


def test_token_chega_pelo_ambiente_e_vira_arquivo(tmp_path, monkeypatch):
    """É assim que a autorização chega ao Railway sem cópia por SSH. E um
    arquivo que já existe nunca é sobrescrito: ele pode ter sido renovado
    depois, e o da variável seria o velho."""
    destino = tmp_path / "volume" / "drive_token.json"
    monkeypatch.setattr(google_drive, "TOKEN_PATH", destino)
    monkeypatch.setenv("ERP_DRIVE_TOKEN_JSON", '{"token": "do-ambiente"}')

    assert google_drive.drive_configurado() is True
    assert destino.read_text(encoding="utf-8") == '{"token": "do-ambiente"}'

    destino.write_text('{"token": "renovado"}', encoding="utf-8")
    google_drive.drive_configurado()
    assert destino.read_text(encoding="utf-8") == '{"token": "renovado"}'


def test_rotina_do_servidor_nao_cai_sem_drive(tmp_path, monkeypatch, capsys):
    """Sem autorização a rotina diária registra e segue -- o backup local
    da rodada já foi salvo antes."""
    from webapp import servir

    monkeypatch.setattr(google_drive, "TOKEN_PATH", tmp_path / "drive_token.json")
    monkeypatch.delenv("ERP_DRIVE_TOKEN_JSON", raising=False)

    servir._enviar_backup_ao_drive(tmp_path)

    assert "Google Drive não autorizado" in capsys.readouterr().out


def _rodada_com(monkeypatch, falha_local=False, falha_envio=False):
    """Prepara _rodada_backup com backup local e envio falsos; devolve as
    listas de chamadas para conferir o que cada tentativa fez."""
    from webapp import servir

    feitos, enviados = [], []

    def main_falso(incluir_documentos):
        if falha_local:
            raise OSError("disco cheio")
        feitos.append(f"pasta{len(feitos) + 1}")
        return feitos[-1]

    def enviar_falso(pasta):
        enviados.append(pasta)
        if falha_envio:
            raise ConnectionError("Drive fora do ar")

    monkeypatch.setattr(modulo_backup, "main", main_falso)
    monkeypatch.setattr(servir, "_enviar_backup_ao_drive", enviar_falso)
    return servir, feitos, enviados


def test_rodada_que_da_certo_espera_um_dia(monkeypatch):
    servir, feitos, enviados = _rodada_com(monkeypatch)
    espera, pendente = servir._rodada_backup()
    assert espera == servir._INTERVALO_BACKUP_SEGUNDOS
    assert pendente is None
    assert enviados == ["pasta1"]


def test_backup_local_que_falha_tenta_de_novo_em_uma_hora(monkeypatch):
    servir, feitos, enviados = _rodada_com(monkeypatch, falha_local=True)
    espera, pendente = servir._rodada_backup()
    assert espera == servir._NOVA_TENTATIVA_BACKUP_SEGUNDOS
    assert pendente is None
    assert enviados == []


def test_envio_que_falha_reenvia_a_mesma_pasta_sem_novo_backup_local(monkeypatch):
    """Uma pasta por hora com o Drive fora do ar apagaria, pela rotação por
    contagem, as duas semanas de histórico local."""
    servir, feitos, enviados = _rodada_com(monkeypatch, falha_envio=True)
    espera, pendente = servir._rodada_backup()
    assert espera == servir._NOVA_TENTATIVA_BACKUP_SEGUNDOS
    assert pendente == "pasta1"

    espera, pendente = servir._rodada_backup(pendente)
    assert feitos == ["pasta1"]
    assert enviados == ["pasta1", "pasta1"]
    assert espera == servir._NOVA_TENTATIVA_BACKUP_SEGUNDOS
