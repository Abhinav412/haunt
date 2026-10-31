"""Allow `python -m haunt` (used by installed git hooks without a PATH-visible CLI)."""

from haunt.cli import app

if __name__ == "__main__":
    app()
