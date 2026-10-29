"""The PyNet2Plan graphical interface (Tkinter + Matplotlib).

Start it with ``python -m pynet2plan`` or ``python main.py``.
"""


def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        raise SystemExit("Tkinter is not available in this Python installation, so the GUI "
                         "cannot start.\nOn Linux install it with: sudo apt install python3-tk\n"
                         "(the command line still works: python -m pynet2plan --help)")
    from .app import main as _main
    _main()
