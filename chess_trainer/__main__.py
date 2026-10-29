"""Allow ``python -m chess_trainer``."""

import sys

from chess_trainer.cli import main

if __name__ == "__main__":
    sys.exit(main())
