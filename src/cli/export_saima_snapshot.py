"""CLI: python -m src.cli.export_saima_snapshot [--date YYYY-MM-DD] [--output PATH | --inbox-dir DIR]"""

from src.analysis.saima_export import main

if __name__ == "__main__":
    raise SystemExit(main())
