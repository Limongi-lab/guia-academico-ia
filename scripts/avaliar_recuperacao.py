"""Avalia a qualidade da recuperação do guia-acadêmico (vetorial, textual ou híbrida).

Uso:
    uv run python scripts/avaliar_recuperacao.py [--rotulo ROTULO] [--profundidade K]
                                                  [--busca {vetorial,textual,hibrida}]
    uv run python scripts/avaliar_recuperacao.py --comparar A.json B.json

Modo normal:
    Conecta ao banco, carrega o modelo BGE-M3 uma única vez, avalia todas
    as perguntas de avaliacao/perguntas.jsonl e salva o resultado em
    avaliacao/resultados/<rotulo>.json.

Modo --comparar:
    Carrega dois resultados gravados anteriormente, imprime o delta e termina
    sem abrir banco nem carregar modelo.
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
PERGUNTAS_PATH = RAIZ / "avaliacao" / "perguntas.jsonl"
FONTES_PATH = RAIZ / "fontes.json"
DIR_RESULTADOS = RAIZ / "avaliacao" / "resultados"


# ---------------------------------------------------------------------------
# Helpers de impressão
# ---------------------------------------------------------------------------

def _imprimir_resumo(resultado: dict, rotulo: str) -> None:
    """Imprime o resumo formatado de um resultado de avaliação."""
    n_av = resultado["n_avaliadas"]
    n_rec = resultado["n_recusa"]
    pendentes = resultado["pendentes"]

    print(f"\n{'=' * 60}")
    print(f"Rótulo  : {rotulo}")
    print(f"{'=' * 60}")
    print(f"Avaliadas : {n_av}  |  Recusa : {n_rec}  |  Pendentes : {len(pendentes)}")
    if pendentes:
        print(f"  Pendentes: {', '.join(pendentes)}")

    # Métricas de documento
    print()
    print("── Documento ──")
    hit_doc = resultado["hit_doc"]
    for k, v in sorted(hit_doc.items(), key=lambda x: int(x[0])):
        print(f"  hit_doc@{k:<3} = {v:.4f}")
    print(f"  MRR_doc    = {resultado['mrr_doc']:.4f}")

    # Métricas de trecho
    n_det = resultado["n_com_detalhe"]
    print()
    print(f"── Trecho (n_com_detalhe={n_det}) ──")
    for k, v in sorted(resultado["hit_trecho"].items(), key=lambda x: int(x[0])):
        val = f"{v:.4f}" if v is not None else "None"
        print(f"  hit_trecho@{k:<3} = {val}")

    # Por pergunta
    print()
    print(f"{'id':<20} {'tipo':<20} {'rank_doc':>8} {'rank_trecho':>11} {'dist_top1':>10}")
    print("-" * 75)
    for pp in resultado["por_pergunta"]:
        rd = pp["rank_doc"]
        rt = pp.get("rank_trecho")
        dt = pp["distancia_top1"]
        rd_s = str(rd) if rd is not None else "-"
        rt_s = str(rt) if rt is not None else "-"
        dt_s = f"{dt:.4f}" if dt is not None else "-"
        print(f"  {pp['id']:<18} {pp['tipo']:<20} {rd_s:>8} {rt_s:>11} {dt_s:>10}")

    # Distâncias
    d = resultado["distancias"]
    apl = d["aplicaveis"]
    rec = d["recusa"]
    sep = d["separavel"]
    print()
    print("── Distâncias (top-1) ──")
    apl_min = f"{apl['min']:.4f}" if apl["min"] is not None else "None"
    apl_max = f"{apl['max']:.4f}" if apl["max"] is not None else "None"
    rec_min = f"{rec['min']:.4f}" if rec["min"] is not None else "None"
    rec_max = f"{rec['max']:.4f}" if rec["max"] is not None else "None"
    print(f"  Aplicáveis : min={apl_min}  max={apl_max}")
    print(f"  Recusa     : min={rec_min}  max={rec_max}")
    print(f"  Separável  : {sep}")
    print()


def _imprimir_comparacao(delta: dict, rotulo_a: str, rotulo_b: str) -> None:
    """Imprime o delta entre dois resultados."""
    print(f"\n{'=' * 60}")
    print(f"Comparação: {rotulo_a}  →  {rotulo_b}")
    print(f"{'=' * 60}")
    mrr = delta["mrr_doc"]
    mrr_s = f"{mrr:+.4f}" if mrr is not None else "None"
    print(f"  ΔMRR_doc = {mrr_s}")
    print("  Δhit_doc :")
    for k, v in sorted(delta["hit_doc"].items(), key=lambda x: int(x[0])):
        v_s = f"{v:+.4f}" if v is not None else "None"
        print(f"    @{k:<3} = {v_s}")
    print("  Δhit_trecho :")
    for k, v in sorted(delta["hit_trecho"].items(), key=lambda x: int(x[0])):
        v_s = f"{v:+.4f}" if v is not None else "None"
        print(f"    @{k:<3} = {v_s}")
    print()


# ---------------------------------------------------------------------------
# Modo --comparar
# ---------------------------------------------------------------------------

def _modo_comparar(caminho_a: str, caminho_b: str) -> None:
    """Carrega dois resultados e imprime o delta sem abrir banco nem modelo."""
    from guia.recuperacao.avaliacao import carregar_resultado, comparar

    res_a = carregar_resultado(caminho_a)
    res_b = carregar_resultado(caminho_b)
    rotulo_a = res_a.get("rotulo", caminho_a)
    rotulo_b = res_b.get("rotulo", caminho_b)
    delta = comparar(res_a, res_b)
    _imprimir_comparacao(delta, rotulo_a, rotulo_b)


# ---------------------------------------------------------------------------
# Modo normal
# ---------------------------------------------------------------------------

def _modo_normal(rotulo: str, profundidade: int, busca: str) -> None:
    """Avalia a recuperação e salva o resultado."""
    # Importações pesadas apenas no modo que precisa delas
    from guia.banco import conectar
    from guia.embeddings import carregar_bge_m3, criar_embedder
    from guia.recuperacao.avaliacao import (
        avaliar_recuperacao,
        carregar_perguntas,
        salvar_resultado,
    )
    from guia.recuperacao.busca import buscar_hibrida, buscar_textual, buscar_vetorial

    # Carrega ids de fontes.json
    fontes: list[dict] = json.loads(FONTES_PATH.read_text(encoding="utf-8"))
    ids_docs = {f["id"] for f in fontes}

    # Carrega perguntas
    print(f"Carregando perguntas de {PERGUNTAS_PATH} ...")
    perguntas = carregar_perguntas(PERGUNTAS_PATH)
    print(f"  {len(perguntas)} pergunta(s) carregada(s).")

    # Conecta ao banco
    print("Conectando ao banco...")
    conn = conectar()
    print("  Conectado.")

    # Carrega o modelo UMA vez
    print("Carregando modelo BGE-M3...")
    modelo = carregar_bge_m3()
    embedder = criar_embedder(modelo)
    print("  Modelo pronto.")

    # Função de busca conforme o modo escolhido
    if busca == "vetorial":
        # Comportamento original: embeda e chama buscar_vetorial
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            return buscar_vetorial(conn, vetor, k=k, instituicao=None)
    elif busca == "textual":
        # Embeda para calcular distância e chama buscar_textual
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            return buscar_textual(conn, pergunta, k, vetor=vetor)
    else:  # hibrida
        # Embeda e chama buscar_hibrida
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            return buscar_hibrida(conn, vetor, pergunta, k=profundidade)

    # Avalia
    print(f"\nAvaliando (profundidade={profundidade})...")
    resultado = avaliar_recuperacao(
        perguntas,
        buscar,
        ids_docs,
        ks=(1, 3, 5, 10),
        profundidade=profundidade,
    )

    # Salva
    destino = DIR_RESULTADOS / f"{rotulo}.json"
    salvar_resultado(resultado, destino, rotulo)
    print(f"Resultado salvo em {destino}")

    # Imprime resumo
    _imprimir_resumo(resultado, rotulo)

    conn.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Avalia a recuperação vetorial do guia-acadêmico."
    )
    parser.add_argument(
        "--rotulo",
        default="baseline-vetorial",
        help="Rótulo para identificar este resultado (padrão: baseline-vetorial).",
    )
    parser.add_argument(
        "--profundidade",
        type=int,
        default=10,
        help="Número de resultados pedidos por pergunta (padrão: 10).",
    )
    parser.add_argument(
        "--comparar",
        nargs=2,
        metavar=("A", "B"),
        help="Compara dois arquivos de resultado JSON e imprime o delta.",
    )
    parser.add_argument(
        "--busca",
        choices=["vetorial", "textual", "hibrida"],
        default="vetorial",
        help="Estratégia de busca: vetorial (padrão), textual ou hibrida.",
    )
    args = parser.parse_args()

    if args.comparar:
        _modo_comparar(args.comparar[0], args.comparar[1])
    else:
        _modo_normal(args.rotulo, args.profundidade, args.busca)


if __name__ == "__main__":
    main()
