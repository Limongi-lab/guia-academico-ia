"""Reranking de candidatos da busca usando cross-encoder.

Importar este módulo NÃO carrega torch nem sentence-transformers;
o import pesado acontece apenas dentro de carregar_bge_reranker.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Constantes públicas
# ---------------------------------------------------------------------------

NOME_RERANKER: str = "bge-reranker-v2-m3"
RERANKER_HF: str = "BAAI/bge-reranker-v2-m3"


# ---------------------------------------------------------------------------
# criar_reranker
# ---------------------------------------------------------------------------

def criar_reranker(
    modelo: Any,
    lote: int = 8,
) -> Callable[[str, list[str]], list[float]]:
    """Cria uma função de reranking a partir de qualquer modelo compatível.

    O `modelo` precisa ter `.predict(pares, batch_size=...) -> array | list`
    onde `pares` = [[pergunta, texto], ...].

    A função retornada tem assinatura:
        reranker(pergunta: str, textos: list[str]) -> list[float]

    Garante:
      - Lista vazia retorna [] sem chamar o modelo.
      - Um float Python por texto, na mesma ordem.
      - ValueError se o modelo devolver quantidade errada ou valor não finito.
    """
    def reranker(pergunta: str, textos: list[str]) -> list[float]:
        # Lista vazia: evita chamada ao modelo
        if not textos:
            return []

        # Monta os pares [[pergunta, texto], ...]
        pares = [[pergunta, t] for t in textos]

        # Chama o modelo com o tamanho de lote configurado
        saida = modelo.predict(pares, batch_size=lote)

        # Converte para lista de floats Python
        pontuacoes = [float(v) for v in saida]

        # Valida quantidade
        if len(pontuacoes) != len(textos):
            raise ValueError(
                f"Modelo devolveu {len(pontuacoes)} pontuações para "
                f"{len(textos)} textos."
            )

        # Valida que todos os valores são finitos
        for v in pontuacoes:
            if not math.isfinite(v):
                raise ValueError(
                    f"Pontuação não finita recebida do modelo: {v!r}"
                )

        return pontuacoes

    return reranker


# ---------------------------------------------------------------------------
# carregar_bge_reranker
# ---------------------------------------------------------------------------

def carregar_bge_reranker(
    dispositivo: str = "cpu",
    max_length: int = 1024,
) -> Any:
    """Carrega o modelo BGE Reranker v2-M3 via sentence-transformers.

    Importa sentence_transformers APENAS aqui, para que importar guia.reranking
    não arraste torch para o processo.

    Retorna o CrossEncoder pronto para uso com criar_reranker.
    """
    # Import pesado: só acontece quando esta função é chamada
    from sentence_transformers import CrossEncoder

    return CrossEncoder(
        RERANKER_HF,
        max_length=max_length,
        device=dispositivo,
    )
