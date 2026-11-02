# Ubicación: tests/test_sistema.py
# Pruebas de src/sistema.py: abrir archivos y páginas según el sistema operativo (sin abrir nada de verdad).
from src import sistema


def test_abrir_en_windows(monkeypatch, tmp_path):
    archivo = tmp_path / "charla.blocks.txt"
    abiertos, comandos = [], []
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setattr(sistema.os, "startfile", abiertos.append, raising=False)
    monkeypatch.setattr(sistema.subprocess, "run", lambda comando, **kw: comandos.append(comando))

    sistema.abrir(archivo)
    sistema.abrir(archivo, revelar=True)

    assert abiertos == [str(archivo)]
    # explorer.exe con su ruta completa: uno dejado en la carpeta actual no se ejecuta
    assert comandos == [f'"C:\\Windows\\explorer.exe" /select,"{archivo}"']


def test_abrir_en_mac_y_linux_no_cambia(monkeypatch, tmp_path):
    archivo = tmp_path / "charla.blocks.txt"
    comandos = []
    monkeypatch.setattr(sistema.subprocess, "run", lambda comando, **kw: comandos.append(comando))

    monkeypatch.setattr("sys.platform", "darwin")
    sistema.abrir(archivo, revelar=True)
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr(sistema.shutil, "which", lambda c: "/usr/bin/" + c)
    sistema.abrir(archivo, revelar=True)

    assert comandos == [["open", "-R", str(archivo)], ["xdg-open", str(tmp_path)]]


def test_abrir_no_hereda_el_token(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_TOKEN", "hf_secreto")
    monkeypatch.setenv("VARIABLE_NORMAL", "se_queda")
    entornos = []
    monkeypatch.setattr(sistema.subprocess, "run", lambda comando, **kw: entornos.append(kw["env"]))
    monkeypatch.setattr("sys.platform", "darwin")
    sistema.abrir(tmp_path / "charla.blocks.txt")
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    sistema.abrir(tmp_path / "charla.blocks.txt", revelar=True)
    assert len(entornos) == 2
    assert all("HF_TOKEN" not in e and e["VARIABLE_NORMAL"] == "se_queda" for e in entornos)


def test_abrir_pagina_retorna_si_se_pudo(monkeypatch):
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda url: True)
    assert sistema.abrir_pagina("https://ejemplo.org") is True
    monkeypatch.setattr(webbrowser, "open", lambda url: False)
    assert sistema.abrir_pagina("https://ejemplo.org") is False


def test_abrir_pagina_no_lanza_errores(monkeypatch):
    import webbrowser

    def falla(url):
        raise RuntimeError("sin navegador")

    monkeypatch.setattr(webbrowser, "open", falla)
    assert sistema.abrir_pagina("https://ejemplo.org") is False
