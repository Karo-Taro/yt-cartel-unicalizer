"""Единая точка входа для графического режима (и для сборщика приложений)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unicalizer.gui import main

if __name__ == "__main__":
    main()
