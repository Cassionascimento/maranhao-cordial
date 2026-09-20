#!/usr/bin/env python3
"""Gera SVG, PNG e PDF dos QRs iniciais em artes/qr/ (fora de maranhao-backend,
portanto não servido pelo site). Os códigos e as frases vêm da migration 029,
que é a fonte única. Uso: python3 scripts/gerar_qr_artes.py"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import qr_arte  # noqa: E402

PADRAO = re.compile(r"\('([a-z0-9]{10})',\s*'([a-z0-9_]+)',\s*'[^']*',\s*'([^']*)'", re.S)


def qrs_iniciais():
    sql = (RAIZ / 'migrations' / '029_qr_rastreaveis.sql').read_text(encoding='utf-8')
    seed = sql[sql.index('INSERT INTO qr_codigos'):]
    return PADRAO.findall(seed)


def main():
    destino = RAIZ / 'artes' / 'qr'
    destino.mkdir(parents=True, exist_ok=True)
    qrs = qrs_iniciais()
    assert len(qrs) == 4, qrs
    for codigo, slug, chamada in qrs:
        for formato in qr_arte.FORMATOS:
            arquivo = destino / f'qr_{slug}.{formato}'
            arquivo.write_bytes(qr_arte.gerar(formato, chamada, codigo))
            print(arquivo.relative_to(RAIZ), qr_arte.url_do_codigo(codigo))


if __name__ == '__main__':
    main()
