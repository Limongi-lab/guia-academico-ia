"""Extrai o texto das fontes baixadas e gera um relatório para inspeção manual.

Uso:
    uv run python scripts/inspecionar_texto.py
"""
import json
from collections import Counter
from pathlib import Path

import pymupdf
import trafilatura

RAIZ = Path(__file__).resolve().parent.parent
MANIFESTO = RAIZ / "data" / "raw" / "manifest.json"
SAIDA = RAIZ / "data" / "processed"
LIMITE_PAGINA_MAGRA = 200  # páginas com menos caracteres que isso são suspeitas


def extrair_pdf(caminho: Path) -> list[str]:
    with pymupdf.open(caminho) as doc:
        return [pagina.get_text() for pagina in doc]


def extrair_html(caminho: Path) -> str:
    html = caminho.read_text(encoding="utf-8", errors="replace")
    texto = trafilatura.extract(html, include_tables=True, include_comments=False)
    return texto or ""


def linhas_repetidas(paginas: list[str]) -> list[tuple[str, int]]:
    """Linhas que aparecem em muitas páginas (provável cabeçalho ou rodapé)."""
    contagem: Counter[str] = Counter()
    for texto in paginas:
        contagem.update({l.strip() for l in texto.splitlines() if l.strip()})
    limite = max(3, len(paginas) // 2)
    return [(l, n) for l, n in contagem.most_common(10) if n >= limite]


def main() -> None:
    fontes = json.loads(MANIFESTO.read_text(encoding="utf-8"))

    for fonte in fontes:
        if "arquivo" not in fonte:
            print(f"- {fonte['id']}: sem arquivo baixado, pulando")
            continue

        origem = RAIZ / fonte["arquivo"]
        destino = SAIDA / fonte["instituicao"] / f"{fonte['id']}.txt"
        destino.parent.mkdir(parents=True, exist_ok=True)

        print(f"\n== {fonte['id']} ({fonte['tipo']})")

        if fonte["tipo"] == "pdf":
            paginas = extrair_pdf(origem)
            magras = [i + 1 for i, p in enumerate(paginas) if len(p.strip()) < LIMITE_PAGINA_MAGRA]
            texto = "\n\n".join(
                f"=== página {i + 1} ===\n{p}" for i, p in enumerate(paginas)
            )
            print(f"   páginas: {len(paginas)} | caracteres: {sum(len(p) for p in paginas)}")
            print(f"   páginas com pouco texto (possível imagem/scan): {magras or 'nenhuma'}")
            for linha, n in linhas_repetidas(paginas):
                print(f"   repetida em {n} páginas: {linha[:90]}")
        else:
            texto = extrair_html(origem)
            print(f"   caracteres: {len(texto)}")

        destino.write_text(texto, encoding="utf-8")

    print(f"\nTextos salvos em {SAIDA}")


if __name__ == "__main__":
    main()