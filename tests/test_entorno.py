# Ubicación: tests/test_entorno.py
# sin_secretos(): el entorno que heredan los programas que lanzamos, sin el token de Hugging Face.
from src.entorno import SECRETOS, sin_secretos


def test_quita_los_secretos_del_entorno_actual(monkeypatch):
    for nombre in SECRETOS:
        monkeypatch.setenv(nombre, "hf_secreto")
    monkeypatch.setenv("VARIABLE_NORMAL", "se_queda")
    entorno = sin_secretos()
    assert not any(nombre in entorno for nombre in SECRETOS)
    assert entorno["VARIABLE_NORMAL"] == "se_queda"


def test_con_base_conserva_las_variables_propias_y_no_toca_la_original():
    base = {"HF_TOKEN": "hf_secreto", "AVISO_TITULO": "Listo", "PATH": "/usr/bin"}
    entorno = sin_secretos(base)
    assert entorno == {"AVISO_TITULO": "Listo", "PATH": "/usr/bin"}
    assert base["HF_TOKEN"] == "hf_secreto"  # es una copia


def test_no_cambia_os_environ(monkeypatch):
    import os

    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    sin_secretos()
    assert os.environ["HF_TOKEN"] == "hf_secreto"
