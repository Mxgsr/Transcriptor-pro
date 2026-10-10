# Ubicación: main.py
# Mantiene funcionando `python main.py ...`. El comando instalado es `transcriptor`;
# la interfaz está en src/cli.py y el flujo de trabajo en src/procesador.py.
from src.cli import app


def main():
    app()


if __name__ == "__main__":
    main()
