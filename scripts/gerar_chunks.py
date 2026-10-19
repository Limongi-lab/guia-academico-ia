"""Gera os trechos (chunks) de cada resolução e imprime checagens de sanidade.

Uso:
    uv run python scripts/gerar_chunks.py
    uv run python scripts/gerar_chunks.py --mostrar 50 41 179
"""
import argparse
import json
import re
from pathlib import Path

from guia.ingestao.resolucoes import dividir_em_artigos

RAIZ = Path(__file__).resolve().parent.parent
FONTES = {f["id"]: f for f in json.loads((RAIZ / "fontes.json").read_text(encoding="utf-8"))}
DOCUMENTOS = [
    "ufu-normas-gerais-graduacao",
    "ufu-normas-estagio",
    "uniube-regimento-geral-2015",
]
MARCAS = ("(Redação dada", "(Revogado", "(Incluído", "(Vide", "SEI/UFU", "sei.ufu.br")
TITULO_COLADO = re.compile(r"^\s*(t[íi]tulo|cap[íi]tulo|se[çc][ãa]o|subse[çc][ãa]o)\b", re.I | re.M)
TITULO_CAIXA_ALTA = re.compile(r"^\s*D[OA]S?\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ ,]{6,}$", re.M)


def numero(artigo: str) -> int | None:
    achou = re.match(r"\d+", artigo)
    return int(achou.group()) if achou else None


def checar(doc_id: str, trechos: list[dict]) -> None:
    for t in trechos[:3]:
        print(f"   início: Art. {t['artigo']} -> {' '.join(t['texto'].split())[:90]}")
    nums = [numero(t["artigo"]) for t in trechos]
    validos = [n for n in nums if n is not None]
    print(f"   trechos: {len(trechos)} | maior artigo: {max(validos) if validos else '-'}")

    faltando = sorted(set(range(1, max(validos) + 1)) - set(validos)) if validos else []
    print(f"   artigos faltando na sequência: {faltando[:30] or 'nenhum'}")

    fora_de_ordem = [b for a, b in zip(validos, validos[1:]) if b < a]
    print(f"   artigos fora de ordem: {fora_de_ordem[:20] or 'nenhum'}")

    residuais = [t["artigo"] for t in trechos if any(m in t["texto"] for m in MARCAS)]
    print(f"   com marcação residual: {residuais[:20] or 'nenhum'}")

    coladas = [
        t["artigo"]
        for t in trechos
        if TITULO_COLADO.search(t["texto"][-300:]) or TITULO_CAIXA_ALTA.search(t["texto"][-300:])
    ]
    print(f"   com título/capítulo colado no fim: {coladas[:20] or 'nenhum'} (total {len(coladas)})")

    por_tamanho = sorted(trechos, key=lambda t: len(t["texto"]))
    menores = [(t["artigo"], len(t["texto"])) for t in por_tamanho[:5]]
    maiores = [(t["artigo"], len(t["texto"])) for t in por_tamanho[-5:]]
    print(f"   5 menores (artigo, caracteres): {menores}")
    print(f"   5 maiores (artigo, caracteres): {maiores}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc", default="ufu-normas-gerais-graduacao", help="documento do --mostrar")
    parser.add_argument("--mostrar", nargs="*", default=[], help="artigos para imprimir")
    args = parser.parse_args()

    saida = RAIZ / "data" / "processed" / "chunks"
    saida.mkdir(parents=True, exist_ok=True)

    for doc_id in DOCUMENTOS:
        fonte = FONTES[doc_id]
        arquivo = RAIZ / "data" / "processed" / fonte["instituicao"] / f"{doc_id}.txt"
        trechos = dividir_em_artigos(arquivo.read_text(encoding="utf-8"))

        print(f"\n== {doc_id}")
        checar(doc_id, trechos)

        registros = [
            {
                "id": f"{doc_id}#art-{t['artigo']}",
                "documento_id": doc_id,
                "titulo_documento": fonte["titulo"],
                "instituicao": fonte["instituicao"],
                "prioridade": fonte["prioridade"],
                "data_ref": fonte["data_ref"],
                "url": fonte["url"],
                **t,
            }
            for t in trechos
        ]
        with (saida / f"{doc_id}.jsonl").open("w", encoding="utf-8") as f:
            for r in registros:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

        if doc_id == args.doc:
            for r in registros:
                if r["artigo"] in args.mostrar:
                    print(f"\n--- Art. {r['artigo']} (páginas {r['paginas']}) | {r.get('capitulo', '')} | {r.get('secao', '')}\n{r['texto']}")

    print(f"\nArquivos em {saida}")


if __name__ == "__main__":
    main()