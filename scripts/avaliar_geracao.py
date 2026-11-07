"""Avalia a camada de geração sobre o conjunto de perguntas anotadas.

Uso:
    uv run python scripts/avaliar_geracao.py --modelo gemini-2.5-flash
    uv run python scripts/avaliar_geracao.py --modelo gemini-2.5-flash --limite 10
    uv run python scripts/avaliar_geracao.py --modelo gemini-2.5-flash --preco-entrada 0.10 --preco-saida 0.40
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
FONTES_PATH = RAIZ / "fontes.json"
DIR_RESULTADOS = RAIZ / "avaliacao" / "resultados"
_PERGUNTAS_PADRAO = RAIZ / "avaliacao" / "perguntas.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _instituicao_por_pergunta(
    perguntas: list[dict],
    fontes: list[dict],
) -> dict[str, str | None]:
    """Mapeia pergunta_id -> instituicao da primeira fonte esperada.

    Perguntas do tipo recusa recebem None (sem filtro).
    """
    idx_inst = {f["id"]: f.get("instituicao") for f in fontes}
    mapa: dict[str, str | None] = {}
    for p in perguntas:
        if p.get("tipo") == "recusa":
            mapa[p["id"]] = None
        else:
            fonte = p.get("fonte_esperada") or ""
            doc_id = fonte.split(",")[0].split()[0] if fonte else ""
            mapa[p["id"]] = idx_inst.get(doc_id)
    return mapa


def _imprimir_relatorio(
    resultado: dict,
    rotulo: str,
    modelo: str,
    max_artigos: int = 3,
    agrupar: bool = False,
) -> None:
    """Imprime o relatório consolidado da avaliação de geração."""
    print(f"\n{'=' * 65}")
    print(f"Avaliação da Geração: {rotulo} (modelo: {modelo})")
    print(f"{'=' * 65}")

    n_perg = resultado["n_perguntas"]
    n_av = resultado["n_avaliadas"]
    n_pend = len(resultado["pendentes"])
    n_err = resultado["n_erros"]
    print(f"Perguntas : total={n_perg}  avaliadas={n_av}  pendentes={n_pend}  erros={n_err}")
    print(f"Config    : max_artigos={max_artigos}  agrupar={agrupar}")
    if resultado["erros"]:
        print(f"  Erros: {', '.join(resultado['erros'])}")

    print("\n── Taxas ──")
    trc = resultado["taxa_recusa_correta"]
    trc_s = f"{trc * 100:.1f}% ({resultado['n_recusa_correta']}/{resultado['n_recusa']})" if trc is not None else "N/A"
    print(f"  Taxa de recusa correta : {trc_s}")

    tri = resultado["taxa_recusa_indevida"]
    tri_s = f"{tri * 100:.1f}% ({resultado['n_recusa_indevida']}/{resultado['n_validas']})" if tri is not None else "N/A"
    print(f"  Taxa de recusa indevida: {tri_s}")

    tcc = resultado["taxa_citacao_correta"]
    tcc_s = f"{tcc * 100:.1f}% ({resultado['n_citacao_correta']}/{resultado['n_respondidas']})" if tcc is not None else "N/A"
    print(f"  Taxa citação correta   : {tcc_s}")

    aprov = resultado["aproveitamento"]
    aprov_s = f"{aprov * 100:.1f}% ({resultado['n_citacao_correta']}/{resultado['n_validas']})" if aprov is not None else "N/A"
    print(f"  Aproveitamento         : {aprov_s}")

    print("\n── Motivos de Recusa ──")
    motivos = resultado.get("motivos_recusa") or {}
    if motivos:
        for mot, qtd in sorted(motivos.items()):
            print(f"  {mot:<20}: {qtd}")
    else:
        print("  Nenhum")

    print("\n── Recursos (médias sobre chamadas ao LLM) ──")
    ch_llm = resultado["chamadas_llm"]
    print(f"  Chamadas ao LLM   : {ch_llm}")

    ti_m = resultado["tokens_entrada_medio"]
    ti_m_s = f"{ti_m:.1f}" if ti_m is not None else "N/A"
    print(f"  Tokens de entrada : {ti_m_s} (total: {resultado['tokens_entrada_total']})")

    ts_m = resultado["tokens_saida_medio"]
    ts_m_s = f"{ts_m:.1f}" if ts_m is not None else "N/A"
    print(f"  Tokens de saída   : {ts_m_s} (total: {resultado['tokens_saida_total']})")

    lat_m = resultado["latencia_media_s"]
    lat_med = resultado["latencia_mediana_s"]
    lat_max = resultado["latencia_max_s"]
    if lat_m is not None:
        print(f"  Latência média    : {lat_m:.2f}s (mediana: {lat_med:.2f}s, max: {lat_max:.2f}s)")
    else:
        print("  Latência média    : N/A")

    custo = resultado["custo_usd"]
    custo_ch = resultado["custo_usd_por_chamada"]
    if custo is not None:
        c_ch_s = f"${custo_ch:.6f}" if custo_ch is not None else "N/A"
        print(f"  Custo total       : ${custo:.6f} (médio/chamada: {c_ch_s})")
    else:
        print("  Custo             : N/A (preços não informados)")

    print("\n── Por Pergunta ──")
    print(f"  {'id':<18} {'tipo':<18} {'recusou':<9} {'motivo':<16} {'cit_ok':<8} {'erro'}")
    print("  " + "-" * 75)
    for pp in resultado["por_pergunta"]:
        pid = pp["id"]
        tipo = pp["tipo"]
        rec = str(pp["recusou"]) if pp["recusou"] is not None else "-"
        mot = str(pp["motivo_recusa"]) if pp["motivo_recusa"] is not None else "-"
        cok = str(pp["citacao_ok"]) if pp["citacao_ok"] is not None else "-"
        err = str(pp["erro"]) if pp["erro"] is not None else "-"
        print(f"  {pid:<18} {tipo:<18} {rec:<9} {mot:<16} {cok:<8} {err}")
    print()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Avalia a camada de geração com pipeline completo e LLM Gemini."
    )
    parser.add_argument(
        "--modelo",
        required=True,
        help="nome do modelo, veja no Google AI Studio",
    )
    parser.add_argument(
        "--perguntas",
        default=str(_PERGUNTAS_PADRAO),
        help="Caminho para o arquivo de perguntas (padrão: avaliacao/perguntas.jsonl).",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Limite de perguntas não pendentes a avaliar.",
    )
    parser.add_argument(
        "--preco-entrada",
        type=float,
        default=None,
        dest="preco_entrada",
        help="Preço de entrada em USD por milhão de tokens (opcional).",
    )
    parser.add_argument(
        "--preco-saida",
        type=float,
        default=None,
        dest="preco_saida",
        help="Preço de saída em USD por milhão de tokens (opcional).",
    )
    parser.add_argument(
        "--rotulo",
        default="geracao",
        help="Rótulo para identificar este resultado (padrão: geracao).",
    )
    parser.add_argument(
        "--pausa",
        type=float,
        default=0.0,
        help="Segundos de pausa entre perguntas (padrão: 0).",
    )
    parser.add_argument(
        "--max-artigos",
        type=int,
        default=3,
        dest="max_artigos",
        help="Número máximo de artigos consolidados no contexto (padrão: 3).",
    )
    parser.add_argument(
        "--agrupar-artigo",
        action="store_true",
        default=False,
        dest="agrupar_artigo",
        help="Agrupa trechos por artigo antes do rerank.",
    )
    args = parser.parse_args()

    # Importações pesadas apenas na execução do script
    from guia.banco import conectar
    from guia.embeddings import carregar_bge_m3, criar_embedder
    from guia.geracao_avaliacao import avaliar_geracao
    from guia.llm_gemini import ErroLLM, criar_llm_gemini
    from guia.pipeline import perguntar
    from guia.recuperacao.avaliacao import carregar_perguntas, salvar_resultado
    from guia.reranking import carregar_bge_reranker, criar_reranker

    fontes: list[dict] = json.loads(FONTES_PATH.read_text(encoding="utf-8"))
    ids_docs = {f["id"] for f in fontes}

    caminho_perguntas = Path(args.perguntas)
    print(f"Carregando perguntas de {caminho_perguntas} ...")
    todas_perguntas = carregar_perguntas(caminho_perguntas)

    # Aplica o limite sobre perguntas não pendentes, se solicitado
    if args.limite is not None:
        perguntas_filtradas: list[dict] = []
        cont_nao_pendentes = 0
        for p in todas_perguntas:
            if "depende" in p:
                perguntas_filtradas.append(p)
            else:
                if cont_nao_pendentes < args.limite:
                    perguntas_filtradas.append(p)
                    cont_nao_pendentes += 1
        perguntas = perguntas_filtradas
    else:
        perguntas = todas_perguntas

    print(f"  {len(perguntas)} pergunta(s) selecionada(s) para avaliação.")

    inst_map = _instituicao_por_pergunta(perguntas, fontes)

    print(f"Inicializando LLM Gemini ({args.modelo})...")
    llm = criar_llm_gemini(args.modelo)
    print("  LLM pronto.")

    print("Conectando ao banco...")
    conn = conectar()
    print("  Conectado.")

    print("Carregando modelo BGE-M3 (embedder)...")
    modelo_emb = carregar_bge_m3()
    embedder = criar_embedder(modelo_emb)
    print("  Embedder pronto.")

    print("Carregando modelo BGE-Reranker-v2-M3 (reranker)...")
    modelo_rr = carregar_bge_reranker()
    reranker = criar_reranker(modelo_rr)
    print("  Reranker pronto.")

    def responder_fn(pergunta: dict) -> dict:
        inst = inst_map.get(pergunta["id"])
        try:
            resp = perguntar(
                conn,
                pergunta["pergunta"],
                embedder,
                reranker,
                llm,
                instituicao=inst,
                max_artigos=args.max_artigos,
                agrupar_antes_do_rerank=args.agrupar_artigo,
            )
        except ErroLLM as exc:
            resp = {"erro": str(exc)}

        if args.pausa > 0:
            time.sleep(args.pausa)
        return resp

    print("\nExecutando avaliação de geração...")
    resultado = avaliar_geracao(
        perguntas,
        responder_fn,
        ids_docs,
        preco_entrada=args.preco_entrada,
        preco_saida=args.preco_saida,
    )

    destino = DIR_RESULTADOS / f"{args.rotulo}.json"
    salvar_resultado(resultado, destino, args.rotulo)
    print(f"Resultado salvo em {destino}")

    _imprimir_relatorio(
        resultado,
        args.rotulo,
        args.modelo,
        max_artigos=args.max_artigos,
        agrupar=args.agrupar_artigo,
    )

    conn.close()


if __name__ == "__main__":
    main()

