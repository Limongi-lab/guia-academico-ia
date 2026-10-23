import copy
import hashlib
import re
from typing import Optional

_DATA_RE = re.compile(r'^\d{4}(-\d{2}(-\d{2})?)?$')


def _validar_data_ref(valor) -> Optional[str]:
    if valor and isinstance(valor, str) and _DATA_RE.match(valor):
        return valor
    return None


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def formatar_paginas(paginas: list) -> str:
    uniq = sorted(set(paginas))
    if not uniq:
        return ''
    grupos = []
    inicio = uniq[0]
    fim = uniq[0]
    for n in uniq[1:]:
        if n == fim + 1:
            fim = n
        else:
            grupos.append((inicio, fim))
            inicio = fim = n
    grupos.append((inicio, fim))
    partes = [str(a) if a == b else f'{a}-{b}' for a, b in grupos]
    return 'p. ' + ', '.join(partes)
