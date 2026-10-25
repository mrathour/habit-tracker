"""Entry point of the PyInstaller build: the same as the ``habit-tracker`` command."""

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
