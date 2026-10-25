"""Carrega o corpus (fontes.json + data/processed/trechos/) no banco.

Uso:
    uv run python scripts/carregar_banco.py [--dry-run]

Opcoes:
    --dry-run   Valida e imprime estatísticas sem carregar modelo nem abrir banco.

Saída e arquivos em UTF-8 (sys.stdout.reconfigure).
"""
import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
FONTES_PATH = RAIZ / "fontes.json"
DIR_TRECHOS = RAIZ / "data" / "processed" / "trechos"


def main() -> None:
    parser = argparse.ArgumentParser(description="Carga do corpus no banco guia.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida e imprime resumo sem carregar modelo nem abrir banco.",
    )
    args = parser.parse_args()

    # Le fontes.json
    fontes: list[dict] = json.loads(FONTES_PATH.read_text(encoding="utf-8"))

    if args.dry_run:
        _executar_dry_run(fontes)
    else:
        _executar_carga(fontes)


def _executar_dry_run(fontes: list[dict]) -> None:
    """Valida o corpus e imprime estatísticas sem gravar nada."""
    from guia.ingestao.corpus import ler_corpus

    print("=== Dry-run: validando corpus ===\n")
    try:
        resultado = ler_corpus(fontes, DIR_TRECHOS)
    except ValueError as erro:
        print(f"[ERRO de validacao] {erro}")
        sys.exit(1)

    for fonte, trechos in resultado["documentos"]:
        print(f"  {fonte['id']:40s}  {len(trechos):5d} trecho(s)")

    print()
    if resultado["sem_trechos"]:
        print(f"Sem trechos ({len(resultado['sem_trechos'])}): {resultado['sem_trechos']}")
    if resultado["sem_fonte"]:
        print(f"Sem fonte   ({len(resultado['sem_fonte'])}): {resultado['sem_fonte']}")

    total = sum(len(ts) for _, ts in resultado["documentos"])
    print(f"\nTotal: {len(resultado['documentos'])} documento(s), {total} trecho(s).")
    print("\n(dry-run concluido: nenhum dado foi gravado)")


def _executar_carga(fontes: list[dict]) -> None:
    """Carrega o corpus no banco com embeddings reais."""
    # Importacoes pesadas so acontecem aqui (torch, sentence_transformers)
    from guia.banco import conectar, criar_esquema
    from guia.embeddings import NOME_MODELO, carregar_bge_m3, criar_embedder
    from guia.ingestao.corpus import carregar_corpus

    print("=== Carga do corpus ===\n")
    print("Conectando ao banco...")
    conn = conectar()
    criar_esquema(conn)
    print("Esquema verificado.\n")

    print(f"Carregando modelo {NOME_MODELO}...")
    modelo_st = carregar_bge_m3()
    embedder = criar_embedder(modelo_st)
    print("Modelo pronto.\n")

    print("Carregando corpus...")
    try:
        resultado = carregar_corpus(
            conn,
            fontes,
            DIR_TRECHOS,
            embedder,
            modelo=NOME_MODELO,
        )
    except ValueError as erro:
        print(f"[ERRO de validacao] {erro}")
        conn.close()
        sys.exit(1)

    # Imprime estatísticas por documento
    print(f"\n{'Documento':<40} {'ins':>5} {'atu':>5} {'ina':>5} {'rem':>5} {'emb':>5}")
    print("-" * 65)
    for doc_id, stats in resultado["por_documento"].items():
        print(
            f"  {doc_id:<38} "
            f"{stats['inseridos']:>5} "
            f"{stats['atualizados']:>5} "
            f"{stats['inalterados']:>5} "
            f"{stats['removidos']:>5} "
            f"{stats['embeddings_gerados']:>5}"
        )

    # Totais
    t = resultado["totais"]
    print("-" * 65)
    print(
        f"  {'TOTAL':<38} "
        f"{t['inseridos']:>5} "
        f"{t['atualizados']:>5} "
        f"{t['inalterados']:>5} "
        f"{t['removidos']:>5} "
        f"{t['embeddings_gerados']:>5}"
    )

    print()
    if resultado["sem_trechos"]:
        print(f"Sem trechos ({len(resultado['sem_trechos'])}): {resultado['sem_trechos']}")
    if resultado["sem_fonte"]:
        print(f"Sem fonte   ({len(resultado['sem_fonte'])}): {resultado['sem_fonte']}")

    conn.close()
    print("\nCarga concluida.")


if __name__ == "__main__":
    main()
