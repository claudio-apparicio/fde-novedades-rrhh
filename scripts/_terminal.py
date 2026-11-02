"""Copia todo lo que sale por la terminal (stdout y logs) a un archivo, para usarlo como evidencia."""
from __future__ import annotations

import contextlib
import io
import logging
import sys
from pathlib import Path


class _Tee(io.TextIOBase):
    def __init__(self, *destinos):
        self.destinos = destinos

    def write(self, s):
        for d in self.destinos:
            d.write(s)
        return len(s)

    def flush(self):
        for d in self.destinos:
            d.flush()


@contextlib.contextmanager
def grabar_terminal(ruta: Path):
    ruta.parent.mkdir(exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as archivo:
        sys.stdout = _Tee(sys.__stdout__, archivo)
        sys.stderr = _Tee(sys.__stderr__, archivo)
        try:
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            for h in logging.root.handlers[:]:
                logging.root.removeHandler(h)
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
