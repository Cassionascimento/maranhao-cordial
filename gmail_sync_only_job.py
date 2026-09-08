"""Entrada nova: imagens anteriores não podem executar o fluxo antigo ao retomar."""
from gmail_sync_job import main

if __name__ == '__main__':
    raise SystemExit(main())
