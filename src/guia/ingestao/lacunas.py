from __future__ import annotations

from typing import Any

PREFIXO_LACUNA: str = "[conteúdo não extraído"


def aplicar_lacunas(
    artigos: list[dict[str, Any]],
    lacunas: list[dict[str, Any]],
    doc_id: str,
) -> list[dict[str, Any]]:
    copias = [dict(a) for a in artigos]
    mapa = {str(a["artigo"]): a for a in copias}
    for lac in lacunas:
        if lac.get("doc_id") != doc_id:
            continue
        num = str(lac["artigo"])
        if num not in mapa:
            raise ValueError(f"Documento '{doc_id}', artigo '{num}' não encontrado.")
        art = mapa[num]
        ancora = lac["ancora"]
        marca = lac["marca"]
        qtd = art["texto"].count(ancora)
        if qtd != 1:
            raise ValueError(
                f"Documento '{doc_id}', artigo '{num}': âncora '{ancora}' encontrada {qtd} vezes."
            )
        art["texto"] = art["texto"].replace(ancora, ancora + "\n" + marca, 1)
    return copias

