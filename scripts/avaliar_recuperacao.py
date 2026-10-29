"""Avalia a qualidade da recuperação do guia-acadêmico (vetorial, textual ou híbrida).

Uso:
    uv run python scripts/avaliar_recuperacao.py [--rotulo ROTULO] [--profundidade K]
                                                  [--busca {vetorial,textual,hibrida}]
                                                  [--perguntas CAMINHO]
                                                  [--rrf-k INT] [--k-candidatos INT]
                                                  [--agrupar-artigo] [--instituicao-da-fonte]
                                                  [--rerank]
    uv run python scripts/avaliar_recuperacao.py --comparar A.json B.json
    uv run python scripts/avaliar_recuperacao.py --varredura

Modo normal:
    Conecta ao banco, carrega o modelo BGE-M3 uma única vez, avalia todas
    as perguntas de avaliacao/perguntas.jsonl e salva o resultado em
    avaliacao/resultados/<rotulo>.json.

Modo --comparar:
    Carrega dois resultados gravados anteriormente, imprime o delta e termina
    sem abrir banco nem carregar modelo.

Modo --varredura:
    Carrega o modelo UMA vez e roda busca híbrida para todas as combinações de
    rrf_k em (10, 30, 60) e k_candidatos em (10, 20, 50). Salva cada resultado
    em avaliacao/resultados/hibrida-rrf{K}-c{N}.json e imprime uma tabela
    compacta no final. Inclui também a linha vetorial para referência.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
FONTES_PATH = RAIZ / "fontes.json"
DIR_RESULTADOS = RAIZ / "avaliacao" / "resultados"

_PERGUNTAS_PADRAO = RAIZ / "avaliacao" / "perguntas.jsonl"

# Combinações usadas no --varredura
_VARREDURA_RRF_K = (10, 30, 60)
_VARREDURA_K_CAND = (10, 20, 50)


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

def _instituicao_por_pergunta(
    perguntas: list[dict],
    fontes: list[dict],
) -> dict[str, str | None]:
    """Devolve um dict {pergunta_id -> instituicao} para --instituicao-da-fonte.

    Para cada pergunta que não seja recusa, extrai o doc_id do primeiro token
    de fonte_esperada (antes de vírgula ou espaço) e busca a instituição
    correspondente em fontes.json. Perguntas de recusa ficam mapeadas para None
    (sem filtro). Doc_ids não encontrados em fontes.json também ficam None.
    """
    # Índice doc_id -> instituicao
    idx = {f["id"]: f["instituicao"] for f in fontes}

    mapa: dict[str, str | None] = {}
    for p in perguntas:
        if p.get("tipo") == "recusa":
            mapa[p["id"]] = None
            continue
        fonte = p.get("fonte_esperada") or ""
        # O doc_id é tudo antes da primeira vírgula ou espaço
        doc_id = fonte.split(",")[0].split()[0] if fonte else ""
        mapa[p["id"]] = idx.get(doc_id)
    return mapa


def _modo_normal(
    rotulo: str,
    profundidade: int,
    busca: str,
    perguntas_path: Path,
    rrf_k: int,
    k_candidatos: int,
    agrupar_artigo: bool,
    instituicao_da_fonte: bool,
    rerank: bool,
) -> None:
    """Avalia a recuperação e salva o resultado."""
    # Importações pesadas apenas no modo que precisa delas
    from guia.banco import conectar
    from guia.embeddings import carregar_bge_m3, criar_embedder
    from guia.recuperacao.avaliacao import (
        avaliar_recuperacao,
        carregar_perguntas,
        salvar_resultado,
    )
    from guia.recuperacao.busca import (
        buscar_com_rerank,
        buscar_hibrida,
        buscar_textual,
        buscar_vetorial,
        buscar_vetorial_por_artigo,
    )

    # Carrega ids e mapa de instituições de fontes.json
    fontes: list[dict] = json.loads(FONTES_PATH.read_text(encoding="utf-8"))
    ids_docs = {f["id"] for f in fontes}

    # Carrega perguntas
    print(f"Carregando perguntas de {perguntas_path} ...")
    perguntas = carregar_perguntas(perguntas_path)
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

    # Carrega o reranker UMA vez (apenas com --rerank)
    reranker = None
    usar_rerank = rerank and busca == "vetorial"
    if usar_rerank:
        from guia.reranking import carregar_bge_reranker, criar_reranker
        print("Carregando reranker BGE-Reranker-v2-M3...")
        modelo_reranker = carregar_bge_reranker()
        reranker = criar_reranker(modelo_reranker)
        print("  Reranker pronto.")

    # Mapa texto_da_pergunta -> instituicao (usado apenas com --instituicao-da-fonte).
    # avaliar_recuperacao chama buscar(pergunta_texto, k), então indexamos pelo texto.
    inst_por_texto: dict[str, str | None] = {}
    if instituicao_da_fonte:
        inst_por_id = _instituicao_por_pergunta(perguntas, fontes)
        inst_por_texto = {p["pergunta"]: inst_por_id[p["id"]] for p in perguntas}
        n_inst = sum(1 for v in inst_por_id.values() if v)
        print(f"  Filtro de instituição ativo: {n_inst}/{len(perguntas)} perguntas com filtro.")

    # Função de busca conforme o modo e as opções escolhidas
    if usar_rerank:
        # Reranking vetorial com sigmoid quando score fora de [0,1]
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            inst = inst_por_texto.get(pergunta) if instituicao_da_fonte else None
            resultados = buscar_com_rerank(
                conn, vetor, pergunta, reranker,
                k=k, instituicao=inst, k_candidatos=k_candidatos,
            )
            # Converte score_rerank em "distancia" = 1 - sigmoid(score) se necessário
            for res in resultados:
                s = res["score_rerank"]
                # Aplica sigmoid se o score estiver fora de [0, 1]
                if s < 0 or s > 1:
                    s = 1.0 / (1.0 + math.exp(-s))
                res["distancia"] = 1.0 - s
            return resultados

    elif busca == "vetorial" and agrupar_artigo:
        # Vetorial agrupada por artigo, com filtro de instituição opcional
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            inst = inst_por_texto.get(pergunta) if instituicao_da_fonte else None
            return buscar_vetorial_por_artigo(
                conn, vetor, k=k, instituicao=inst, k_candidatos=k_candidatos
            )

    elif busca == "vetorial":
        # Comportamento original: embeda e chama buscar_vetorial;
        # com --instituicao-da-fonte usa o filtro por pergunta
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            inst = inst_por_texto.get(pergunta) if instituicao_da_fonte else None
            return buscar_vetorial(conn, vetor, k=k, instituicao=inst)

    elif busca == "textual":
        # Embeda para calcular distância e chama buscar_textual
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            return buscar_textual(conn, pergunta, k, vetor=vetor)

    else:  # hibrida
        # Embeda e chama buscar_hibrida com os parâmetros configurados
        def buscar(pergunta: str, k: int) -> list[dict]:
            vetor = embedder([pergunta])[0]
            return buscar_hibrida(
                conn,
                vetor,
                pergunta,
                k=k,
                rrf_k=rrf_k,
                k_candidatos=k_candidatos,
            )

    # Avalia
    print(f"\nAvaliando (profundidade={profundidade})...")
    if usar_rerank:
        print("  Nota: distâncias = 1 − score do reranker (com sigmoid se score fora de [0,1]).")
    t0 = time.monotonic()
    resultado = avaliar_recuperacao(
        perguntas,
        buscar,
        ids_docs,
        ks=(1, 3, 5, 10),
        profundidade=profundidade,
    )
    elapsed = time.monotonic() - t0
    print(f"  Tempo total de avaliação: {elapsed:.1f}s")

    # Salva
    destino = DIR_RESULTADOS / f"{rotulo}.json"
    salvar_resultado(resultado, destino, rotulo)
    print(f"Resultado salvo em {destino}")

    # Imprime resumo
    _imprimir_resumo(resultado, rotulo)

    conn.close()


# ---------------------------------------------------------------------------
# Modo --varredura
# ---------------------------------------------------------------------------

def _modo_varredura(perguntas_path: Path, profundidade: int) -> None:
    """Carrega o modelo UMA vez e roda busca híbrida para todas as combinações
    de rrf_k × k_candidatos, depois imprime tabela compacta com referência vetorial.
    """
    from guia.banco import conectar
    from guia.embeddings import carregar_bge_m3, criar_embedder
    from guia.recuperacao.avaliacao import (
        avaliar_recuperacao,
        carregar_perguntas,
        salvar_resultado,
    )
    from guia.recuperacao.busca import buscar_hibrida, buscar_vetorial

    # Carrega ids de fontes.json
    fontes: list[dict] = json.loads(FONTES_PATH.read_text(encoding="utf-8"))
    ids_docs = {f["id"] for f in fontes}

    # Carrega perguntas
    print(f"Carregando perguntas de {perguntas_path} ...")
    perguntas = carregar_perguntas(perguntas_path)
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

    DIR_RESULTADOS.mkdir(parents=True, exist_ok=True)

    # Estrutura para acumular linhas da tabela: (rotulo, resultado)
    linhas: list[tuple[str, dict]] = []

    # ── Referência vetorial ──────────────────────────────────────────────────
    print("\n[varredura] Avaliando referência vetorial...")

    def _buscar_vetorial(pergunta: str, k: int) -> list[dict]:
        vetor = embedder([pergunta])[0]
        return buscar_vetorial(conn, vetor, k=k, instituicao=None)

    res_vet = avaliar_recuperacao(
        perguntas,
        _buscar_vetorial,
        ids_docs,
        ks=(1, 3, 5, 10),
        profundidade=profundidade,
    )
    rotulo_vet = "vetorial"
    salvar_resultado(res_vet, DIR_RESULTADOS / f"{rotulo_vet}.json", rotulo_vet)
    linhas.append((rotulo_vet, res_vet))

    # ── Grade híbrida ────────────────────────────────────────────────────────
    for rrf_k in _VARREDURA_RRF_K:
        for k_cand in _VARREDURA_K_CAND:
            rotulo = f"hibrida-rrf{rrf_k}-c{k_cand}"
            print(f"[varredura] {rotulo} ...")

            def _buscar_hibrida(
                pergunta: str,
                k: int,
                _rrf_k: int = rrf_k,
                _k_cand: int = k_cand,
            ) -> list[dict]:
                vetor = embedder([pergunta])[0]
                return buscar_hibrida(
                    conn,
                    vetor,
                    pergunta,
                    k=k,
                    rrf_k=_rrf_k,
                    k_candidatos=_k_cand,
                )

            resultado = avaliar_recuperacao(
                perguntas,
                _buscar_hibrida,
                ids_docs,
                ks=(1, 3, 5, 10),
                profundidade=profundidade,
            )
            destino = DIR_RESULTADOS / f"{rotulo}.json"
            salvar_resultado(resultado, destino, rotulo)
            linhas.append((rotulo, resultado))

    conn.close()

    # ── Tabela compacta ──────────────────────────────────────────────────────
    col_cfg = 28
    print()
    print(
        f"{'configuração':<{col_cfg}} "
        f"{'ht@1':>7} {'ht@3':>7} {'ht@5':>7} {'ht@10':>7} {'MRR_doc':>8}"
    )
    print("-" * (col_cfg + 1 + 7 + 1 + 7 + 1 + 7 + 1 + 7 + 1 + 8))
    for rot, res in linhas:
        ht = res["hit_trecho"]
        mrr = res["mrr_doc"]

        def _fmt(v: float | None) -> str:
            return f"{v:.4f}" if v is not None else "  None"

        print(
            f"{rot:<{col_cfg}} "
            f"{_fmt(ht.get('1')):>7} "
            f"{_fmt(ht.get('3')):>7} "
            f"{_fmt(ht.get('5')):>7} "
            f"{_fmt(ht.get('10')):>7} "
            f"{mrr:>8.4f}"
        )
    print()


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
    parser.add_argument(
        "--perguntas",
        default=str(_PERGUNTAS_PADRAO),
        metavar="CAMINHO",
        help="Caminho para o arquivo de perguntas JSONL (padrão: avaliacao/perguntas.jsonl).",
    )
    parser.add_argument(
        "--rrf-k",
        type=int,
        default=60,
        dest="rrf_k",
        help="Parâmetro k do RRF para busca híbrida (padrão: 60).",
    )
    parser.add_argument(
        "--k-candidatos",
        type=int,
        default=50,
        dest="k_candidatos",
        help="Número de candidatos por buscador na busca híbrida (padrão: 50).",
    )
    parser.add_argument(
        "--varredura",
        action="store_true",
        help=(
            "Roda busca híbrida para todas as combinações de rrf_k × k_candidatos "
            "e imprime tabela compacta."
        ),
    )
    parser.add_argument(
        "--agrupar-artigo",
        action="store_true",
        dest="agrupar_artigo",
        help=(
            "Usa buscar_vetorial_por_artigo: deduplica trechos por pai_id antes de "
            "devolver resultados (vale para --busca vetorial)."
        ),
    )
    parser.add_argument(
        "--instituicao-da-fonte",
        action="store_true",
        dest="instituicao_da_fonte",
        help=(
            "Filtra a busca vetorial pela instituição do primeiro documento citado "
            "em fonte_esperada de cada pergunta (simula perfil do usuário no app)."
        ),
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help=(
            "Aplica reranking com BGE-Reranker-v2-M3 após a busca vetorial "
            "(vale para --busca vetorial; combina com --instituicao-da-fonte). "
            "O reranker é carregado UMA vez. distâncias = 1 − score do reranker."
        ),
    )
    args = parser.parse_args()

    perguntas_path = Path(args.perguntas)

    if args.comparar:
        _modo_comparar(args.comparar[0], args.comparar[1])
    elif args.varredura:
        _modo_varredura(perguntas_path, args.profundidade)
    else:
        _modo_normal(
            args.rotulo,
            args.profundidade,
            args.busca,
            perguntas_path,
            args.rrf_k,
            args.k_candidatos,
            args.agrupar_artigo,
            args.instituicao_da_fonte,
            args.rerank,
        )


if __name__ == "__main__":
    main()
