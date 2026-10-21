"""Extrai atividades complementares do HTML bruto da FAGEN e grava JSON estruturado.

Uso:
    uv run python scripts/extrair_atividades.py

Lê:   data/raw/ufu/fagen-gi-atividades-complementares.html  (id da fonte em fontes.json)
Grava: data/processed/estruturados/atividades-fagen-gi.json

Imprime checagens de sanidade:
    - Total de linhas (esperado: 41)
    - Códigos repetidos
    - Distribuição de limite_horas
    - Primeira e última atividade
"""
import json
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "data" / "raw" / "ufu" / "fagen-gi-atividades-complementares.html"
SAIDA = RAIZ / "data" / "processed" / "estruturados" / "atividades-fagen-gi.json"

# Importa depois de garantir que o pacote src está no path
sys.path.insert(0, str(RAIZ / "src"))
from guia.ingestao.atividades_fagen import extrair_atividades


def main() -> None:
    html = ENTRADA.read_text(encoding="utf-8", errors="replace")
    atividades = extrair_atividades(html)

    # ── Grava JSON ──────────────────────────────────────────────────────────
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(
        json.dumps(atividades, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[OK] Gravado: {SAIDA.relative_to(RAIZ)}")

    # -- Checagens de sanidade -------------------------------------------------
    total = len(atividades)
    print("\n-- Sanidade ------------------------------------------")
    print(f"Total de linhas : {total}  (esperado: 41)")

    codigos = [a["codigo"] for a in atividades]
    repetidos = {c: n for c, n in Counter(codigos).items() if n > 1}
    if repetidos:
        print(f"Codigos repetidos: {repetidos}")
    else:
        print("Codigos repetidos: nenhum")

    dist_limites = dict(sorted(Counter(a["limite_horas"] for a in atividades).items()))
    print(f"Limites (horas -> qtd atividades): {dist_limites}")

    primeira = atividades[0]
    ultima = atividades[-1]
    print(
        f"\nPrimeira: {primeira['codigo']}  |  {primeira['limite_horas']} horas  |  {primeira['comprovacao']}"
    )
    print(
        f"Ultima  : {ultima['codigo']}  |  {ultima['limite_horas']} horas  |  {ultima['comprovacao']}"
    )


if __name__ == "__main__":
    main()
