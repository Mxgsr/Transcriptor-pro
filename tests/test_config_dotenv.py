# Ubicación: tests/test_config_dotenv.py
# Qué .env lee src/config.py. Cada caso corre config.py en un subproceso, copiado dentro de una
# carpeta temporal que imita el proyecto: así no se contamina os.environ de las demás pruebas
# ni se depende del .env real de quien ejecute los tests.
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG = Path(__file__).resolve().parent.parent / "src" / "config.py"

# Corre config.py como archivo (runpy fija __file__) y devuelve las variables que interesan.
_SCRIPT = """
import json, os, runpy, sys
runpy.run_path(sys.argv[1])
print(json.dumps({n: os.environ.get(n) for n in ("VARIABLE_ARRIBA", "VARIABLE_PROYECTO", "VARIABLE_CASA", "VARIABLE_COMUN")}))
"""


def _montar(tmp_path: Path, env_proyecto: str = None) -> Path:
    """arriba/.env (carpeta superior) > arriba/proyecto/src/config.py, con o sin proyecto/.env."""
    arriba = tmp_path / "arriba"
    src = arriba / "proyecto" / "src"
    src.mkdir(parents=True)
    shutil.copy(CONFIG, src / "config.py")
    (arriba / ".env").write_text("VARIABLE_ARRIBA=si\nVARIABLE_COMUN=arriba\n", encoding="utf-8")
    if env_proyecto is not None:
        (arriba / "proyecto" / ".env").write_text(env_proyecto, encoding="utf-8")
    return src / "config.py"


def _correr(config: Path, tmp_path: Path, extra: dict = None) -> dict:
    casa = tmp_path / "casa"
    casa.mkdir(exist_ok=True)
    entorno = {k: v for k, v in os.environ.items() if not k.startswith("VARIABLE_")}
    entorno["TRANSCRIPTOR_HOME"] = str(casa)
    entorno.update(extra or {})
    # cwd en la carpeta del proyecto falso: aunque se buscara desde ahí, el .env de arriba no debe leerse
    resultado = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(config)],
        cwd=config.parent, env=entorno, capture_output=True, text=True, timeout=60,
    )
    assert resultado.returncode == 0, resultado.stderr
    return json.loads(resultado.stdout.strip().splitlines()[-1])


def test_no_lee_el_env_de_una_carpeta_superior(tmp_path):
    variables = _correr(_montar(tmp_path), tmp_path)
    assert variables["VARIABLE_ARRIBA"] is None
    assert variables["VARIABLE_COMUN"] is None


def test_lee_el_env_del_proyecto_y_el_de_transcriptor_home(tmp_path):
    config = _montar(tmp_path, "VARIABLE_PROYECTO=si\nVARIABLE_COMUN=proyecto\n")
    (tmp_path / "casa").mkdir()
    (tmp_path / "casa" / ".env").write_text("VARIABLE_CASA=si\nVARIABLE_COMUN=casa\n", encoding="utf-8")
    variables = _correr(config, tmp_path)
    assert variables["VARIABLE_PROYECTO"] == "si"
    assert variables["VARIABLE_CASA"] == "si"
    assert variables["VARIABLE_ARRIBA"] is None
    # El del proyecto va primero y lo ya definido no se pisa
    assert variables["VARIABLE_COMUN"] == "proyecto"


def test_el_entorno_real_manda_sobre_los_env(tmp_path):
    config = _montar(tmp_path, "VARIABLE_COMUN=proyecto\n")
    (tmp_path / "casa").mkdir()
    (tmp_path / "casa" / ".env").write_text("VARIABLE_CASA=casa\n", encoding="utf-8")
    variables = _correr(config, tmp_path, {"VARIABLE_COMUN": "real", "VARIABLE_CASA": "real"})
    assert variables["VARIABLE_COMUN"] == "real"
    assert variables["VARIABLE_CASA"] == "real"


def test_sin_env_del_proyecto_solo_lee_transcriptor_home(tmp_path):
    config = _montar(tmp_path)
    (tmp_path / "casa").mkdir()
    (tmp_path / "casa" / ".env").write_text("VARIABLE_CASA=si\n", encoding="utf-8")
    variables = _correr(config, tmp_path)
    assert variables["VARIABLE_CASA"] == "si"
    assert variables["VARIABLE_ARRIBA"] is None
