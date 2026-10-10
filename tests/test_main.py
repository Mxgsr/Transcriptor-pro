# Ubicación: tests/test_main.py
import sys

import main
from src.cli import app


def test_main_py_usa_la_cli(monkeypatch, capsys):
    """`python main.py ...` sigue funcionando: delega en la misma app que el comando `transcriptor`."""
    assert main.app is app
    monkeypatch.setattr(sys, "argv", ["main.py", "--help"])

    try:
        main.main()
    except SystemExit as e:
        assert e.code == 0

    assert "transcribir" in capsys.readouterr().out
