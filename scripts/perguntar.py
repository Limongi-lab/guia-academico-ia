"""Executa o pipeline completo para responder a uma pergunta acadêmica.

Uso:
    uv run python scripts/perguntar.py "Qual a nota mínima para aprovação?" --modelo gemini-2.5-flash --instituicao ufu
"""
from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Responde a uma pergunta sobre normas acadêmicas com base em documentos institucionais."
    )
    parser.add_argument(
        "pergunta",
        help="Pergunta sobre as normas acadêmicas.",
    )
    parser.add_argument(
        "--modelo",
        required=True,
        help="Nome do modelo, veja no Google AI Studio (ex: gemini-2.5-flash).",
    )
    parser.add_argument(
        "--instituicao",
        default=None,
        help="Sigla da instituição de ensino para filtrar (ex: ufu, uniube).",
    )
    args = parser.parse_args()

    from guia.banco import conectar
    from guia.embeddings import carregar_bge_m3, criar_embedder
    from guia.llm_gemini import criar_llm_gemini
    from guia.pipeline import perguntar
    from guia.reranking import carregar_bge_reranker, criar_reranker

    print("Conectando ao banco...")
    conn = conectar()

    print("Carregando modelos (embedder e reranker)...")
    modelo_emb = carregar_bge_m3()
    embedder = criar_embedder(modelo_emb)

    modelo_rr = carregar_bge_reranker()
    reranker = criar_reranker(modelo_rr)

    print(f"Inicializando LLM Gemini ({args.modelo})...\n")
    llm = criar_llm_gemini(args.modelo)

    print(f"Pergunta: {args.pergunta}")
    if args.instituicao:
        print(f"Instituição: {args.instituicao}")
    print(f"Modelo: {args.modelo}\n")

    resp = perguntar(
        conn,
        args.pergunta,
        embedder,
        reranker,
        llm,
        instituicao=args.instituicao,
    )

    print("── Resposta ──")
    print(f"{resp['resposta']}\n")

    citacoes = resp.get("citacoes") or []
    if citacoes:
        print("── Citações ──")
        for c in citacoes:
            print(f"  [{c['indice']}] {c['citacao']} — {c['titulo_doc']}")
            if c.get("url"):
                print(f"      {c['url']}")
        print()

    print("── Métricas ──")
    rec_s = resp.get("recuperacao_s", 0.0)
    lat_s = resp.get("latencia_s", 0.0)
    tot_s = resp.get("total_s", 0.0)
    print(f"  Tempos: recuperação={rec_s:.2f}s | geração={lat_s:.2f}s | total={tot_s:.2f}s")

    ti = resp.get("tokens_entrada")
    ts = resp.get("tokens_saida")
    ti_str = str(ti) if ti is not None else "N/A"
    ts_str = str(ts) if ts is not None else "N/A"
    print(f"  Tokens: entrada={ti_str} | saída={ts_str}\n")

    conn.close()


if __name__ == "__main__":
    main()

