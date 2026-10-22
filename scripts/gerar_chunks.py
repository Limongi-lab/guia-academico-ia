"""Gera os trechos (chunks) de cada resolução e imprime checagens de sanidade.

Uso:
    uv run python scripts/gerar_chunks.py
    uv run python scripts/gerar_chunks.py --mostrar 50 41 179
"""
import argparse
import json
import re
from pathlib import Path

from guia.ingestao.divisao import dividir_artigo
from guia.ingestao.procedimentos import dividir_passos
from guia.ingestao.resolucoes import dividir_em_artigos

RAIZ = Path(__file__).resolve().parent.parent
FONTES = {f["id"]: f for f in json.loads((RAIZ / "fontes.json").read_text(encoding="utf-8"))}
DOCUMENTOS = [
    "ufu-normas-gerais-graduacao",
    "ufu-normas-estagio",
    "uniube-regimento-geral-2015",
]
PROCEDIMENTOS = [
    "fagen-gi-estagio-passo-a-passo",
    "fagen-gi-tcc-passo-a-passo",
]
MARCAS = ("(Redação dada", "(Revogado", "(Incluído", "(Vide", "SEI/UFU", "sei.ufu.br")
TITULO_COLADO = re.compile(r"^\s*(t[íi]tulo|cap[íi]tulo|se[çc][ãa]o|subse[çc][ãa]o)\b", re.I | re.M)
TITULO_CAIXA_ALTA = re.compile(r"^\s*D[OA]S?\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ ,]{6,}$", re.M)


def numero(artigo: str) -> int | None:
    achou = re.match(r"\d+", artigo)
    return int(achou.group()) if achou else None


def checar(doc_id: str, artigos: list[dict], trechos: list[dict]) -> None:
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

    # --- métricas de divisão ---
    divididos = sum(1 for a in artigos if a.get("total_partes", 1) > 1)
    maior_trecho = max((len(t["texto"]) for t in trechos), default=0)
    acima_limite = sum(1 for t in trechos if len(t["texto"]) > 1500)
    print(f"   total de trechos (após divisão): {len(trechos)}")
    print(f"   artigos divididos: {divididos}")
    print(f"   maior trecho (caracteres): {maior_trecho}")
    print(f"   trechos > 1.500 chars: {acima_limite}")

    # --- checagem (a): artigos divididos com 2+ páginas onde algum trecho tem TODAS ---
    divididos_multipagina = [
        a for a in artigos
        if a.get("total_partes", 1) > 1 and len(a.get("paginas", [])) >= 2
    ]
    trechos_com_todas = sum(
        1
        for a in divididos_multipagina
        for t in trechos
        if t["artigo"] == a["artigo"] and set(a["paginas"]) <= set(t.get("paginas", []))
    )
    print(
        f"   [a] artigos divididos c/ 2+ págs: {len(divididos_multipagina)}"
        f" | trechos com TODAS as págs do artigo: {trechos_com_todas}"
    )

    # --- checagem (b): artigos onde a 1ª marca de página está fora de "paginas" ---
    fora_da_1a_marca = [
        a["artigo"]
        for a in artigos
        if a.get("marcas_pagina")
        and a["marcas_pagina"][0][1] not in a.get("paginas", [])
    ]
    print(
        f"   [b] artigos com 1ª marca fora de 'paginas': "
        f"{fora_da_1a_marca[:20] or 'nenhum'} (total {len(fora_da_1a_marca)})"
    )


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
        artigos = dividir_em_artigos(arquivo.read_text(encoding="utf-8"))

        # Divide cada artigo longo em trechos menores e anota total_partes no artigo
        trechos: list[dict] = []
        for art in artigos:
            partes = dividir_artigo(art)
            # Propaga total_partes de volta ao dict do artigo (para a métrica checar)
            art["total_partes"] = len(partes)
            trechos.extend(partes)

        print(f"\n== {doc_id}")
        checar(doc_id, artigos, trechos)

        registros = [
            {
                # Usa o id único do trecho (inclui #parte para artigos divididos)
                "id": f"{doc_id}#{t['id']}",
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
                    print(
                        f"\n--- Art. {r['artigo']} (páginas {r['paginas']}) "
                        f"parte {r.get('parte', 1)}/{r.get('total_partes', 1)}"
                        f" | {r.get('capitulo', '')} | {r.get('secao', '')}\n{r['texto']}"
                    )

    print(f"\nArquivos em {saida}")

    # --- Documentos de procedimento (passo a passo) ---
    for doc_id in PROCEDIMENTOS:
        fonte = FONTES.get(doc_id)
        if fonte is None:
            print(f"\n[AVISO] {doc_id} não encontrado em fontes.json, pulando.")
            continue
        arquivo = RAIZ / "data" / "processed" / fonte["instituicao"] / f"{doc_id}.txt"
        if not arquivo.exists():
            print(f"\n[AVISO] {arquivo} não existe, pulando.")
            continue

        passos = dividir_passos(arquivo.read_text(encoding="utf-8"))

        print(f"\n== {doc_id} (procedimento)")
        print(f"   passos: {len(passos)}")

        # Sanidade: passos fora de sequencia
        numeros = [p["passo"] for p in passos]
        fora_seq = [n for a, n in zip(numeros, numeros[1:]) if n != a + 1]
        print(f"   fora de sequencia: {fora_seq or 'nenhum'}")

        # Sanidade: passos com texto curto
        curtos = [(p["passo"], len(p["texto"])) for p in passos if len(p["texto"]) < 40]
        print(f"   passos com < 40 chars: {curtos or 'nenhum'}")

        registros = [
            {
                "id": f"{doc_id}#passo-{p['passo']}",
                "pai_id": doc_id,
                "passo": p["passo"],
                "ator": p["ator"],
                "texto": p["texto"],
                "paginas": p["paginas"],
                "titulo_doc": p["titulo_doc"],
            }
            for p in passos
        ]
        with (saida / f"{doc_id}.jsonl").open("w", encoding="utf-8") as f:
            for r in registros:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()