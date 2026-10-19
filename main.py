"""Punto de entrada: python main.py"""

import sys


def principal() -> int:
    try:
        from src.gui import App
    except ImportError as error:
        print(f"Falta una dependencia: {error}.\n"
              "Instala los requisitos con:  pip install -r requirements.txt", file=sys.stderr)
        return 1
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(principal())
