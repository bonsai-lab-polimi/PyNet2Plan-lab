"""``python -m pynet2plan`` starts the GUI; ``python -m pynet2plan <command>`` runs the CLI."""

import sys


def _main():
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        sys.exit(cli_main(sys.argv[1:]))
    from .gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    _main()
