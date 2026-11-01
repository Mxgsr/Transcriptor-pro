# Ubicación: tests/test_modelos.py
# Pruebas de src/modelos.py con un huggingface_hub falso en sys.modules: sin red ni modelos.
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src import ajustes, config, historial, modelos, plataforma, procesador, transcriber


class ErrorHttp(Exception):
    def __init__(self, codigo):
        super().__init__(f"{codigo} Client Error")
        self.response = SimpleNamespace(status_code=codigo)


class GatedRepoError(Exception):
    pass


class RepositoryNotFoundError(Exception):
    pass


class ConnectionError(Exception):  # mismo nombre de tipo que reconoce errores.sin_internet
    pass


def _repo(repo_id, tamano, hashes=("h1",)):
    return SimpleNamespace(repo_id=repo_id, repo_type="model", size_on_disk=tamano,
                           revisions=[SimpleNamespace(commit_hash=h) for h in hashes])


class HubFalso:
    """Registra lo que se le pide y simula la caché."""

    def __init__(self, repos=()):
        self.repos = list(repos)
        self.descargas = []
        self.borrados = []
        self.ejecutado = False
        self.error_descarga = None
        self.errores_api = {}
        self.llamadas_api = []

    def modulo(self, con_tqdm=True, con_auth_check=True):
        hub = self
        m = types.ModuleType("huggingface_hub")

        def scan_cache_dir():
            informe = SimpleNamespace(repos=hub.repos)

            def delete_revisions(*hashes):
                hub.borrados.append(hashes)
                return SimpleNamespace(expected_freed_size=1234, execute=lambda: setattr(hub, "ejecutado", True))
            informe.delete_revisions = delete_revisions
            return informe

        def snapshot_download(repo_id, token=None, tqdm_class=None):
            hub.descargas.append({"repo": repo_id, "token": token, "tqdm": tqdm_class,
                                  "offline": ajustes.sin_internet_activo()})
            if hub.error_descarga:
                raise hub.error_descarga
            if tqdm_class is not None:
                with tqdm_class(total=100, unit="B") as barra:
                    barra.update(40)
                    barra.update(60)

        def snapshot_sin_tqdm(repo_id, token=None):
            hub.descargas.append({"repo": repo_id, "token": token, "tqdm": None})

        m.scan_cache_dir = scan_cache_dir
        m.snapshot_download = snapshot_download if con_tqdm else snapshot_sin_tqdm

        class HfApi:
            def whoami(self, token=None):
                hub.llamadas_api.append(("whoami", token))
                if "whoami" in hub.errores_api:
                    raise hub.errores_api["whoami"]

            def model_info(self, repo, token=None):
                hub.llamadas_api.append(("model_info", repo))
                if "modelo" in hub.errores_api:
                    raise hub.errores_api["modelo"]

        m.HfApi = HfApi
        if con_auth_check:
            def auth_check(repo, token=None):
                hub.llamadas_api.append(("auth_check", repo))
                if "modelo" in hub.errores_api:
                    raise hub.errores_api["modelo"]
            m.auth_check = auth_check
        return m


@pytest.fixture
def hub(monkeypatch):
    h = HubFalso()
    monkeypatch.setitem(sys.modules, "huggingface_hub", h.modulo())
    return h


@pytest.fixture
def motor_mlx(monkeypatch):
    monkeypatch.setattr(transcriber, "motor", lambda: transcriber.MOTOR_MLX)


@pytest.fixture
def motor_faster(monkeypatch):
    monkeypatch.setattr(transcriber, "motor", lambda: transcriber.MOTOR_FASTER)
    # Sin faster_whisper instalado: se usa la tabla propia
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", None)


# --- repo_de -------------------------------------------------------------------

def test_repo_de_con_mlx(motor_mlx):
    assert modelos.repo_de("turbo") == "mlx-community/whisper-large-v3-turbo"
    assert modelos.repo_de("small") == "mlx-community/whisper-small-mlx"


def test_repo_de_con_faster_whisper(motor_faster):
    assert modelos.repo_de("small") == "Systran/faster-whisper-small"
    assert modelos.repo_de("large") == "Systran/faster-whisper-large-v3"
    assert modelos.repo_de("turbo") == "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


def test_repo_de_faster_usa_la_tabla_propia_y_faster_whisper_solo_para_lo_desconocido(monkeypatch):
    # La tabla propia va primero: importar faster_whisper al abrir el menú tarda segundos
    monkeypatch.setattr(transcriber, "motor", lambda: transcriber.MOTOR_FASTER)
    utils = types.ModuleType("faster_whisper.utils")
    utils._MODELS = {"tiny": "otro/repo-tiny", "distil-large-v3": "Systran/faster-distil-whisper-large-v3"}
    monkeypatch.setitem(sys.modules, "faster_whisper", types.ModuleType("faster_whisper"))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    assert modelos.repo_de("tiny") == "Systran/faster-whisper-tiny"
    assert modelos.repo_de("distil-large-v3") == "Systran/faster-distil-whisper-large-v3"


def test_repo_de_hablantes(motor_mlx):
    assert modelos.repo_de(modelos.HABLANTES) == config.DIARIZATION_MODEL


# --- estado / descargado / eliminar --------------------------------------------

def test_estado_marca_descargados_con_su_peso_real(hub, motor_mlx):
    hub.repos = [_repo("mlx-community/whisper-small-mlx", 480_123_456)]
    por_clave = {m.clave: m for m in modelos.estado()}
    assert por_clave["small"].descargado and por_clave["small"].bytes == 480_123_456
    assert not por_clave["tiny"].descargado and por_clave["tiny"].bytes is None
    assert por_clave["hablantes"].nombre == "Identificar hablantes"
    assert modelos.descargado("small") and not modelos.descargado("tiny")


def test_estado_ignora_repos_que_no_son_modelos(hub, motor_mlx):
    r = _repo("mlx-community/whisper-small-mlx", 5)
    r.repo_type = "dataset"
    hub.repos = [r]
    assert not modelos.descargado("small")


def test_estado_sin_hablantes_si_no_hay_en_este_computador(hub, motor_mlx, monkeypatch):
    monkeypatch.setattr(plataforma, "hablantes_disponible", lambda: False)
    assert "hablantes" not in [m.clave for m in modelos.estado()]


def test_estado_sin_huggingface_hub_no_lanza(monkeypatch, motor_mlx):
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    assert all(not m.descargado for m in modelos.estado())


def test_estado_si_la_cache_da_error_no_lanza(hub, motor_mlx, monkeypatch):
    def falla():
        raise OSError("sin caché")
    monkeypatch.setattr(sys.modules["huggingface_hub"], "scan_cache_dir", falla)
    assert all(not m.descargado for m in modelos.estado())


def test_eliminar_borra_todas_las_revisiones(hub, motor_mlx):
    hub.repos = [_repo("mlx-community/whisper-small-mlx", 10, ("a", "b")), _repo("otro/repo", 5)]
    assert modelos.eliminar("small") == 1234
    assert hub.borrados == [("a", "b")] and hub.ejecutado


def test_eliminar_un_modelo_que_no_estaba(hub, motor_mlx):
    assert modelos.eliminar("tiny") == 0
    assert hub.borrados == []


# --- texto_peso ----------------------------------------------------------------

@pytest.mark.parametrize("bytes_,texto", [
    (1_600_000_000, "1,6 GB"), (3_100_000_000, "3,1 GB"), (480_000_000, "480 MB"),
    (30_000_000, "30 MB"), (500_000, "500 KB"),
])
def test_texto_peso(bytes_, texto):
    assert modelos.texto_peso(bytes_) == texto


# --- con_internet --------------------------------------------------------------

def test_con_internet_apaga_y_restaura(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with modelos.con_internet():
        assert not ajustes.sin_internet_activo()
    assert ajustes.sin_internet_activo()


def test_con_internet_restaura_si_hay_error(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    with pytest.raises(KeyError):
        with modelos.con_internet():
            raise KeyError("x")
    assert ajustes.sin_internet_activo()


def test_con_internet_no_toca_si_no_estaba_activo(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    with modelos.con_internet():
        assert not ajustes.sin_internet_activo()
    assert not ajustes.sin_internet_activo()


# --- descargar -----------------------------------------------------------------

def test_descargar_whisper_mlx_no_pasa_el_token(hub, motor_mlx, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    modelos.descargar("small")
    assert hub.descargas[0]["repo"] == "mlx-community/whisper-small-mlx"
    assert hub.descargas[0]["token"] is None


def test_descargar_hablantes_pasa_el_token(hub, motor_mlx, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    modelos.descargar(modelos.HABLANTES)
    assert hub.descargas[0]["repo"] == config.DIARIZATION_MODEL
    assert hub.descargas[0]["token"] == "hf_secreto"


def test_descargar_informa_el_progreso_en_bytes(hub, motor_mlx):
    avances = []
    modelos.descargar("small", progreso=lambda hecho, total: avances.append((hecho, total)))
    assert avances[-1] == (100, 100)
    assert (40, 100) in avances


def test_progreso_como_lo_informa_huggingface_hub_2():
    # huggingface_hub 2.x crea con tqdm_class dos barras de bytes de toda la descarga (recibidos y
    # escritos) con total=0, les sube el total asignando .total y actualiza las dos con cada trozo.
    # Antes se informaba (8000, 0): el doble de bytes y sin total.
    avances = []
    clase = modelos._clase_tqdm(lambda hecho, total: avances.append((hecho, total)))
    recibidos = clase(total=0, initial=0, unit="B", unit_scale=True, desc="Downloading bytes")
    escritos = clase(total=0, initial=0, unit="B", unit_scale=True, desc="Reconstructing")
    archivos = clase(total=2, desc="Fetching 2 files")  # por cantidad de archivos: no cuenta
    for tamano in (1000, 3000):
        escritos.total = (escritos.total or 0) + tamano
        recibidos.total = (recibidos.total or 0) + tamano
    for _ in range(8):
        escritos.update(500)
        recibidos.update(500)
        archivos.update(0)
    archivos.update(2)
    assert avances[-1] == (4000, 4000)
    assert all(hecho <= total for hecho, total in avances if total)


def test_descargar_sin_tqdm_class_funciona_sin_progreso(hub, monkeypatch, motor_mlx):
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub.modulo(con_tqdm=False))
    modelos.descargar("small", progreso=lambda *a: None)
    assert hub.descargas[0]["tqdm"] is None


def test_descargar_apaga_sin_internet_solo_mientras_descarga(hub, motor_mlx, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    modelos.descargar("small")
    assert hub.descargas[0]["offline"] is False
    assert ajustes.sin_internet_activo()


def test_descargar_faster_usa_download_model(monkeypatch, hub):
    monkeypatch.setattr(transcriber, "motor", lambda: transcriber.MOTOR_FASTER)
    utils = types.ModuleType("faster_whisper.utils")
    utils._MODELS = {}
    utils.download_model = MagicMock()
    monkeypatch.setitem(sys.modules, "faster_whisper", types.ModuleType("faster_whisper"))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", utils)
    modelos.descargar("large")
    utils.download_model.assert_called_once_with("large-v3")
    assert hub.descargas == []


def test_descargar_sin_internet_da_mensaje_simple(hub, motor_mlx):
    hub.error_descarga = ConnectionError("Max retries exceeded")
    with pytest.raises(RuntimeError, match="No hay conexión a internet para descargar el modelo"):
        modelos.descargar("small")


@pytest.mark.parametrize("error", [GatedRepoError("x"), ErrorHttp(401), ErrorHttp(403)])
def test_descargar_hablantes_con_clave_mala_da_mensaje_simple(hub, motor_mlx, error):
    hub.error_descarga = error
    with pytest.raises(RuntimeError, match="La clave de Hugging Face no sirve"):
        modelos.descargar(modelos.HABLANTES)


def test_descargar_whisper_deja_subir_otros_errores(hub, motor_mlx):
    hub.error_descarga = ErrorHttp(403)
    with pytest.raises(ErrorHttp):
        modelos.descargar("small")


# --- comprobar_token -----------------------------------------------------------

def test_comprobar_token_ok(hub):
    assert modelos.comprobar_token("hf_x") == "ok"
    assert ("auth_check", config.DIARIZATION_MODEL) in hub.llamadas_api


def test_comprobar_token_ok_sin_auth_check_usa_model_info(hub, monkeypatch):
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub.modulo(con_auth_check=False))
    assert modelos.comprobar_token("hf_x") == "ok"
    assert ("model_info", config.DIARIZATION_MODEL) in hub.llamadas_api


def test_comprobar_token_invalida(hub):
    hub.errores_api["whoami"] = ErrorHttp(401)
    assert modelos.comprobar_token("hf_x") == "invalida"


@pytest.mark.parametrize("error", [GatedRepoError("x"), ErrorHttp(403), RepositoryNotFoundError("x")])
def test_comprobar_token_sin_acceso(hub, error):
    hub.errores_api["modelo"] = error
    assert modelos.comprobar_token("hf_x") == "sin_acceso"


def test_comprobar_token_sin_internet(hub):
    hub.errores_api["whoami"] = ConnectionError("fallo")
    assert modelos.comprobar_token("hf_x") == "sin_internet"


def test_comprobar_token_desconocido(hub):
    hub.errores_api["whoami"] = RuntimeError("raro")
    assert modelos.comprobar_token("hf_x") == "desconocido"


def test_comprobar_token_no_registra_el_token(hub, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    hub.errores_api["whoami"] = ErrorHttp(401)
    modelos.comprobar_token("hf_MUY_SECRETO")
    assert "hf_MUY_SECRETO" not in caplog.text


# --- guardar_token -------------------------------------------------------------

def test_guardar_token_agrega_y_crea_la_carpeta(historial_temporal, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.setattr(config, "HF_TOKEN", None)
    ruta = modelos.guardar_token("hf_nuevo")
    assert ruta == historial_temporal / ".env"
    assert ruta.read_text(encoding="utf-8") == "HF_TOKEN=hf_nuevo\n"
    assert not ruta.read_bytes().startswith(b"\xef\xbb\xbf")
    assert modelos.token_guardado() == "hf_nuevo" and config.HF_TOKEN == "hf_nuevo"


def test_guardar_token_reemplaza_sin_perder_otras_lineas(historial_temporal, monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", None)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    historial_temporal.mkdir(parents=True)
    (historial_temporal / ".env").write_text("A=1\nHF_TOKEN=viejo\nDEFAULT_MODEL=small\n", encoding="utf-8")
    ruta = modelos.guardar_token("hf_nuevo")
    assert ruta.read_text(encoding="utf-8") == "A=1\nHF_TOKEN=hf_nuevo\nDEFAULT_MODEL=small\n"


def test_guardar_token_agrega_al_final_si_no_estaba(historial_temporal, monkeypatch):
    monkeypatch.setattr(config, "HF_TOKEN", None)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    historial_temporal.mkdir(parents=True)
    (historial_temporal / ".env").write_text("A=1", encoding="utf-8")
    assert modelos.guardar_token("hf_n").read_text(encoding="utf-8") == "A=1\nHF_TOKEN=hf_n\n"


def test_guardar_token_no_lo_escribe_en_el_registro(historial_temporal, monkeypatch, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(config, "HF_TOKEN", None)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    modelos.guardar_token("hf_MUY_SECRETO")
    assert "hf_MUY_SECRETO" not in caplog.text


def test_guardar_token_vacio_no_se_acepta(historial_temporal):
    with pytest.raises(ValueError):
        modelos.guardar_token("   ")


def test_token_guardado_lee_el_entorno_en_el_momento(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert modelos.token_guardado() is None
    monkeypatch.setenv("HF_TOKEN", "hf_z")
    assert modelos.token_guardado() == "hf_z"


# --- necesita_preparacion ------------------------------------------------------

@pytest.fixture
def preparado(hub, motor_mlx, monkeypatch):
    """Modelo por defecto descargado, pyannote instalado, clave y modelo de hablantes presentes."""
    monkeypatch.setattr(ajustes, "valor", lambda clave: "small")
    hub.repos = [_repo("mlx-community/whisper-small-mlx", 1), _repo(config.DIARIZATION_MODEL, 1)]
    monkeypatch.setenv("HF_TOKEN", "hf_x")
    monkeypatch.setattr(modelos, "_pyannote_instalado", lambda: True)
    return hub


def test_no_necesita_preparacion_si_todo_esta(preparado):
    assert modelos.necesita_preparacion() is False


def test_necesita_preparacion_si_falta_el_modelo_por_defecto(preparado):
    preparado.repos = [r for r in preparado.repos if "whisper" not in r.repo_id]
    assert modelos.necesita_preparacion() is True


def test_necesita_preparacion_si_falta_la_clave(preparado, monkeypatch):
    monkeypatch.delenv("HF_TOKEN")
    assert modelos.necesita_preparacion() is True


def test_necesita_preparacion_si_falta_el_modelo_de_hablantes(preparado):
    preparado.repos = [r for r in preparado.repos if "whisper" in r.repo_id]
    assert modelos.necesita_preparacion() is True


def test_no_pide_hablantes_si_pyannote_no_esta_instalado(preparado, monkeypatch):
    monkeypatch.setattr(modelos, "_pyannote_instalado", lambda: False)
    monkeypatch.delenv("HF_TOKEN")
    assert modelos.necesita_preparacion() is False


def test_no_pide_hablantes_si_no_hay_en_este_computador(preparado, monkeypatch):
    monkeypatch.setattr(plataforma, "hablantes_disponible", lambda: False)
    monkeypatch.delenv("HF_TOKEN")
    assert modelos.necesita_preparacion() is False


def test_necesita_preparacion_nunca_lanza(monkeypatch):
    def falla(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(modelos, "descargado", falla)
    assert modelos.necesita_preparacion() is False


# --- procesador usa la clave nueva ----------------------------------------------

def test_procesador_usa_la_clave_guardada_sin_reiniciar(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "HF_TOKEN", "hf_viejo")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    historial_ok = modelos.guardar_token("hf_nuevo")
    assert historial_ok.exists()
    cargar = MagicMock(side_effect=RuntimeError("parar aquí"))
    monkeypatch.setattr(procesador, "cargar_pipeline", cargar)
    with pytest.raises(RuntimeError, match="parar aquí"):
        procesador.procesar_entrada(str(tmp_path / "a.mp3"), "tiny", diarizar=True)
    assert cargar.call_args.args[0] == "hf_nuevo"


def test_preparar_no_insiste_si_eligio_seguir_sin_clave(monkeypatch):
    monkeypatch.setattr(modelos, "descargado", lambda clave: True)
    monkeypatch.setattr(modelos.plataforma, "hablantes_disponible", lambda: True)
    monkeypatch.setattr(modelos, "_pyannote_instalado", lambda: True)
    monkeypatch.setattr(modelos, "token_guardado", lambda: None)
    assert modelos.necesita_preparacion()
    historial.guardar_preferencias(**{modelos.SIN_CLAVE_ELEGIDO: True})
    assert not modelos.necesita_preparacion()


def test_preparar_no_pide_clave_si_nunca_identifica_hablantes(monkeypatch):
    monkeypatch.setattr(modelos, "descargado", lambda clave: True)
    monkeypatch.setattr(modelos.plataforma, "hablantes_disponible", lambda: True)
    monkeypatch.setattr(modelos, "_pyannote_instalado", lambda: True)
    monkeypatch.setattr(modelos, "token_guardado", lambda: None)
    ajustes.guardar(modo_hablantes=ajustes.NUNCA)
    assert not modelos.necesita_preparacion()
