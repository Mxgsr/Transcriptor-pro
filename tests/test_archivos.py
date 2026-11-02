# Ubicación: tests/test_archivos.py
# Pruebas de utils/archivos.py: escritura atómica, lectura de JSON que aparta lo dañado y archivos
# y carpetas privados (los permisos se prueban solo en Mac/Linux; en Windows, que nada lance).
import json
import os
import stat
import sys

import pytest

from utils import archivos


def test_escribir_texto_y_json_crean_la_carpeta(tmp_path):
    archivos.escribir_texto(tmp_path / "a" / "b" / "x.txt", "hola ñ")
    archivos.escribir_json(tmp_path / "a" / "y.json", {"k": "ñandú", "l": [1]})
    assert (tmp_path / "a" / "b" / "x.txt").read_bytes() == "hola ñ".encode("utf-8")
    # Mismo formato de siempre: sin escapar tildes y con sangría de 2
    assert (tmp_path / "a" / "y.json").read_text(encoding="utf-8") == \
        json.dumps({"k": "ñandú", "l": [1]}, ensure_ascii=False, indent=2)


def test_si_falla_a_mitad_queda_el_archivo_viejo_y_ningun_temporal(tmp_path, monkeypatch):
    destino = tmp_path / "x.json"
    archivos.escribir_json(destino, {"viejo": True})

    def falla(fd):
        raise OSError("disco lleno")

    monkeypatch.setattr(archivos.os, "fsync", falla)
    with pytest.raises(OSError):
        archivos.escribir_json(destino, {"nuevo": True})
    assert json.loads(destino.read_text(encoding="utf-8")) == {"viejo": True}
    assert os.listdir(tmp_path) == ["x.json"]


def test_si_falla_y_no_existia_no_queda_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(archivos.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        archivos.escribir_texto(tmp_path / "nuevo.txt", "hola")
    assert os.listdir(tmp_path) == []


def test_el_temporal_es_unico_y_esta_en_la_misma_carpeta(tmp_path, monkeypatch):
    vistos = []
    real = archivos.os.replace

    def espia(origen, destino):
        vistos.append(origen)
        real(origen, destino)

    monkeypatch.setattr(archivos.os, "replace", espia)
    archivos.escribir_texto(tmp_path / "x.txt", "1")
    archivos.escribir_texto(tmp_path / "x.txt", "2")
    assert len(set(vistos)) == 2
    assert all(os.path.dirname(v) == str(tmp_path) for v in vistos)
    assert os.listdir(tmp_path) == ["x.txt"]


def test_leer_json_inexistente_da_el_valor_por_defecto(tmp_path):
    assert archivos.leer_json(tmp_path / "no.json", {"a": 1}) == {"a": 1}
    assert archivos.leer_json(tmp_path / "no.json") is None


def test_leer_json_con_bom(tmp_path):
    ruta = tmp_path / "bom.json"
    ruta.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": "ñ"}).encode("utf-8"))
    assert archivos.leer_json(ruta, {}) == {"a": "ñ"}
    assert ruta.exists()


def test_json_invalido_se_aparta_como_corrupto(tmp_path):
    ruta = tmp_path / "d.json"
    ruta.write_text("{roto", encoding="utf-8")
    assert archivos.leer_json(ruta, {"defecto": 1}) == {"defecto": 1}
    assert not ruta.exists()
    assert (tmp_path / "d.json.corrupto").read_text(encoding="utf-8") == "{roto"


def test_un_segundo_corrupto_no_pisa_al_primero(tmp_path):
    ruta = tmp_path / "d.json"
    for texto in ("uno{", "dos{", "tres{"):
        ruta.write_text(texto, encoding="utf-8")
        archivos.leer_json(ruta, {})
    assert (tmp_path / "d.json.corrupto").read_text(encoding="utf-8") == "uno{"
    assert (tmp_path / "d.json.corrupto.2").read_text(encoding="utf-8") == "dos{"
    assert (tmp_path / "d.json.corrupto.3").read_text(encoding="utf-8") == "tres{"


def test_bytes_que_no_son_utf8_tambien_se_apartan(tmp_path):
    ruta = tmp_path / "d.json"
    ruta.write_bytes(b"\xff\xfe\x00{")
    assert archivos.leer_json(ruta, []) == []
    assert (tmp_path / "d.json.corrupto").exists()


def test_escribir_a_traves_de_un_enlace_conserva_el_enlace(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("{}", encoding="utf-8")
    enlace = tmp_path / "enlace.json"
    try:
        enlace.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("este sistema no deja crear enlaces")
    archivos.escribir_json(enlace, {"a": 1})
    assert enlace.is_symlink()
    assert json.loads(real.read_text(encoding="utf-8")) == {"a": 1}


def test_reemplazar_reintenta_en_windows_si_el_destino_esta_en_uso(tmp_path, monkeypatch):
    # El antivirus o OneDrive pueden tener el archivo abierto un instante: PermissionError y luego funciona
    llamadas = []
    real_replace = os.replace

    def replace_ocupado(origen, destino):
        llamadas.append(1)
        if len(llamadas) < 3:
            raise PermissionError("en uso")
        return real_replace(origen, destino)

    monkeypatch.setattr(archivos, "_es_windows", lambda: True)
    monkeypatch.setattr(archivos.os, "replace", replace_ocupado)
    monkeypatch.setattr(archivos.time, "sleep", lambda s: None)
    archivos.escribir_texto(tmp_path / "a.txt", "hola")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hola"
    assert len(llamadas) == 3


# --- Archivos y carpetas privados (~/.transcriptor) -----------------------------------------------
# Los bits de permiso solo existen en Mac/Linux; en Windows se comprueba aparte que nada lanza.
solo_posix = pytest.mark.skipif(sys.platform == "win32", reason="en Windows no hay permisos POSIX")


@pytest.fixture
def umask():
    """Pone un umask para la prueba (y recalcula los permisos normales, que se leen al importar)."""
    anterior = os.umask(0o022)
    os.umask(anterior)

    def poner(valor, monkeypatch):
        os.umask(valor)
        monkeypatch.setattr(archivos, "_PERMISOS_NUEVO", 0o666 & ~valor)

    yield poner
    os.umask(anterior)


def _modo(ruta):
    return stat.S_IMODE(os.stat(ruta).st_mode)


@solo_posix
def test_carpeta_privada_nueva_queda_0700(tmp_path, umask, monkeypatch):
    umask(0o022, monkeypatch)
    ruta = archivos.crear_carpeta_privada(tmp_path / "a" / "datos")
    assert ruta.is_dir() and _modo(ruta) == 0o700


@solo_posix
def test_carpeta_privada_existente_abierta_se_aprieta(tmp_path):
    ruta = tmp_path / "datos"
    ruta.mkdir()
    os.chmod(ruta, 0o755)
    archivos.crear_carpeta_privada(ruta)
    assert _modo(ruta) == 0o700
    # Ya cerrada: no cambia nada ni lanza
    archivos.crear_carpeta_privada(ruta)
    assert _modo(ruta) == 0o700


@solo_posix
def test_carpeta_privada_no_toca_la_carpeta_personal_ni_las_de_otro_dueno(tmp_path, monkeypatch):
    os.chmod(tmp_path, 0o755)
    llamadas = []
    monkeypatch.setattr(archivos.os, "chmod", lambda *a, **k: llamadas.append(a))
    monkeypatch.setattr(archivos.Path, "home", classmethod(lambda cls: tmp_path))
    archivos.crear_carpeta_privada(tmp_path)
    otra = tmp_path / "ajena"
    otra.mkdir()
    monkeypatch.setattr(archivos.os, "getuid", lambda: os.stat(otra).st_uid + 1)
    archivos.crear_carpeta_privada(otra)
    assert llamadas == []


def test_carpeta_privada_tolera_que_chmod_falle(tmp_path, monkeypatch):
    def falla(*a, **k):
        raise PermissionError("no")

    monkeypatch.setattr(archivos.os, "chmod", falla)
    assert archivos.crear_carpeta_privada(tmp_path / "nueva").is_dir()
    assert archivos.crear_carpeta_privada(tmp_path / "nueva").is_dir()


def test_en_windows_carpeta_y_archivo_privados_no_lanzan(tmp_path, monkeypatch):
    # En Windows os.chmod no hace nada útil: no se llama, y aunque fallara nada debe romperse
    monkeypatch.setattr(archivos, "_es_windows", lambda: True)
    monkeypatch.delattr(archivos.os, "getuid", raising=False)
    monkeypatch.setattr(archivos.os, "chmod", lambda *a, **k: None)
    ruta = archivos.crear_carpeta_privada(tmp_path / "datos")
    archivos.escribir_json(ruta / "x.json", {"a": "ñ"}, privado=True)
    archivos.escribir_texto(tmp_path / "otra" / "y.txt", "hola", privado=True)
    assert json.loads((ruta / "x.json").read_text(encoding="utf-8")) == {"a": "ñ"}
    assert (tmp_path / "otra" / "y.txt").read_text(encoding="utf-8") == "hola"


@solo_posix
def test_archivo_privado_queda_0600_aunque_el_umask_sea_022(tmp_path, umask, monkeypatch):
    umask(0o022, monkeypatch)
    archivos.escribir_json(tmp_path / "x.json", {"a": 1}, privado=True)
    assert _modo(tmp_path / "x.json") == 0o600
    # Mismo contenido que sin privado
    assert (tmp_path / "x.json").read_text(encoding="utf-8") == json.dumps({"a": 1}, ensure_ascii=False, indent=2)


@solo_posix
def test_archivo_privado_reemplaza_uno_que_estaba_abierto(tmp_path):
    ruta = tmp_path / "x.txt"
    ruta.write_text("viejo", encoding="utf-8")
    os.chmod(ruta, 0o644)
    archivos.escribir_texto(ruta, "nuevo", privado=True)
    assert _modo(ruta) == 0o600 and ruta.read_text(encoding="utf-8") == "nuevo"


@solo_posix
def test_archivo_privado_en_carpeta_nueva_la_crea_privada(tmp_path, umask, monkeypatch):
    umask(0o022, monkeypatch)
    archivos.escribir_texto(tmp_path / "nueva" / "x.txt", "hola", privado=True)
    assert _modo(tmp_path / "nueva") == 0o700


@solo_posix
def test_archivo_privado_nunca_se_crea_con_permisos_mas_abiertos(tmp_path, monkeypatch):
    modos = []
    real_open, real_chmod = os.open, os.chmod

    def espia_open(ruta, flags, mode=0o777, *a, **k):
        if flags & os.O_CREAT:
            modos.append(mode)
        return real_open(ruta, flags, mode, *a, **k)

    def espia_chmod(ruta, mode, *a, **k):
        modos.append(mode)
        return real_chmod(ruta, mode, *a, **k)

    monkeypatch.setattr(os, "open", espia_open)
    monkeypatch.setattr(os, "chmod", espia_chmod)
    archivos.escribir_texto(tmp_path / "x.txt", "secreto", privado=True)
    assert modos and all(m & 0o077 == 0 for m in modos)


@solo_posix
@pytest.mark.parametrize("valor, esperado", [(0o022, 0o644), (0o077, 0o600)])
def test_archivos_normales_siguen_el_umask(tmp_path, umask, monkeypatch, valor, esperado):
    # Los .txt/.json junto al audio: el Grabador y Obsidian los leen, no se vuelven privados
    umask(valor, monkeypatch)
    archivos.escribir_texto(tmp_path / "a.blocks.txt", "hola")
    archivos.escribir_json(tmp_path / "a.blocks.json", {"a": 1})
    assert _modo(tmp_path / "a.blocks.txt") == esperado
    assert _modo(tmp_path / "a.blocks.json") == esperado
