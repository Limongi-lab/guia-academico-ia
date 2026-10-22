"""Extrai páginas de serviço da FAGEN / PROGRAD e grava JSONs em data/processed/paginas/.

Uso:
    uv run python scripts/extrair_paginas_fagen.py

Para cada fonte de tipo "html" dos hosts fagen.ufu.br ou prograd.ufu.br em fontes.json
(exceto as de atividades complementares), lê o HTML bruto em data/raw/,
chama extrair_pagina_fagen com a URL da fonte e grava o resultado em
data/processed/paginas/<id>.json.

Se extrair_pagina_fagen levantar uma exceção (ex.: layout diferente do Drupal FAGEN),
imprime o erro e continua sem abortar.

Ao final, lista os anexos cujas URLs ainda NÃO estão em fontes.json,
para identificar o que falta ingerir.

Decisões:
- Detecta "atividades complementares" pela URL (substring).
- Compara URLs de anexos sem "www." e sem barra final para decidir se já
  estão em fontes.json (mesma lógica de deduplicação do extrator).
- Imprime resumo por página: título, atualizado_em, #seções, #chars, #anexos,
  tem_contato.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
FONTES = RAIZ / "fontes.json"
RAW = RAIZ / "data" / "raw"
SAIDA = RAIZ / "data" / "processed" / "paginas"

sys.path.insert(0, str(RAIZ / "src"))
from guia.ingestao.pagina_fagen import extrair_pagina_fagen  # noqa: E402


def _chave_url(url: str) -> tuple[str, str]:
    """(host sem www., path sem barra final) — mesmo critério do extrator."""
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/")
    return (host, path)


# Hosts aceitos pelo extrator
_HOSTS_HTML = {"fagen.ufu.br", "prograd.ufu.br"}


def _e_html_aceito(fonte: dict) -> bool:
    if fonte.get("tipo") != "html":
        return False
    host = urlparse(fonte.get("url", "")).netloc.lower().removeprefix("www.")
    return host in _HOSTS_HTML


def _e_atividades_complementares(fonte: dict) -> bool:
    return "atividades-complementares" in fonte.get("url", "")


def main() -> int:
    fontes = json.loads(FONTES.read_text(encoding="utf-8"))

    # Conjunto de chaves de URL já presentes em fontes.json
    chaves_fontes: set[tuple[str, str]] = set()
    for f in fontes:
        chaves_fontes.add(_chave_url(f["url"]))

    # Filtra fontes HTML aceitas, exceto atividades complementares
    alvos = [
        f for f in fontes
        if _e_html_aceito(f) and not _e_atividades_complementares(f)
    ]

    if not alvos:
        print("Nenhuma fonte HTML de host aceito (fora atividades complementares) encontrada.")
        return 0

    SAIDA.mkdir(parents=True, exist_ok=True)

    anexos_novos: list[dict] = []
    vistos_anexos: set[tuple[str, str]] = set()

    for fonte in alvos:
        id_ = fonte["id"]
        inst = fonte.get("instituicao", "ufu")
        arquivo_html = RAW / inst / f"{id_}.html"

        if not arquivo_html.exists():
            print(f"[AUSENTE] {id_} — {arquivo_html} não existe, pulando.")
            continue

        html = arquivo_html.read_text(encoding="utf-8", errors="replace")

        try:
            dados = extrair_pagina_fagen(html, fonte["url"])
        except Exception as exc:  # layout diferente do Drupal FAGEN
            print(f"[ERRO] {id_} — {type(exc).__name__}: {exc}")
            continue

        # Grava JSON processado
        saida = SAIDA / f"{id_}.json"
        saida.write_text(
            json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Resumo por página
        total_chars = sum(len(s["texto"]) for s in dados["secoes"])
        tem_contato = dados["contato"] is not None
        print(
            f"[OK] {id_}\n"
            f"     título:      {dados['titulo']}\n"
            f"     atualizado:  {dados['atualizado_em']}\n"
            f"     seções:      {len(dados['secoes'])}\n"
            f"     caracteres:  {total_chars}\n"
            f"     anexos:      {len(dados['anexos'])}\n"
            f"     tem_contato: {tem_contato}\n"
        )

        # Coleta anexos novos (não em fontes.json)
        for anx in dados["anexos"]:
            chave = _chave_url(anx["url"])
            if chave not in chaves_fontes and chave not in vistos_anexos:
                vistos_anexos.add(chave)
                anexos_novos.append(anx)

    # Lista de anexos que ainda não estão em fontes.json
    if anexos_novos:
        print("\n=== Anexos NÃO em fontes.json (candidatos a ingerir) ===")
        for anx in anexos_novos:
            print(f"  [{anx['tipo']:6}] {anx['url']}")
    else:
        print("\n(Todos os anexos já estão em fontes.json)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
