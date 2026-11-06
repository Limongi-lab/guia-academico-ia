"""Pipeline de ponta a ponta do guia acadêmico.

Conecta a camada de recuperação (embedding, busca vetorial com filtro de instituição,
reranking com cross-encoder) e a camada de geração (montagem de contexto por artigo,
consulta ao LLM com verificação de citação).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import psycopg

from guia.geracao import montar_contexto, responder
from guia.recuperacao.busca import buscar_com_rerank


def perguntar(
    conn: psycopg.Connection,
    pergunta: str,
    embedder: Callable[[list[str]], list[list[float]]],
    reranker: Any,
    llm: Callable[[str, str], dict[str, Any]],
    instituicao: str | None = None,
    k_candidatos: int = 30,
    k_recuperacao: int = 10,
    max_artigos: int = 3,
    relogio: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Executa o pipeline completo para responder a uma pergunta.

    Passos:
      1. Gera o embedding da pergunta com o embedder.
      2. Executa busca vetorial filtrada e reranking com o reranker.
      3. Monta blocos de contexto consolidados por artigo.
      4. Gera a resposta com o LLM e valida citações/recusa.

    Retorna o dicionário de guia.geracao.responder acrescido de:
      - recuperacao_s: tempo dos passos 1 a 3.
      - total_s: recuperacao_s + latencia_s da geração.
      - blocos: lista de blocos de contexto montados.
      - recuperados_ids: lista com os ids dos trechos recuperados na ordem do ranking.
    """
    t_inicio = relogio()

    vetor = embedder([pergunta])[0]
    recuperados = buscar_com_rerank(
        conn,
        vetor,
        pergunta,
        reranker,
        k=k_recuperacao,
        instituicao=instituicao,
        k_candidatos=k_candidatos,
    )
    blocos = montar_contexto(conn, recuperados, max_artigos=max_artigos)

    t_fim_recup = relogio()
    recuperacao_s = float(t_fim_recup - t_inicio)

    resposta = responder(pergunta, blocos, llm, relogio=relogio)
    total_s = float(recuperacao_s + resposta.get("latencia_s", 0.0))

    return {
        **resposta,
        "recuperacao_s": recuperacao_s,
        "total_s": total_s,
        "blocos": blocos,
        "recuperados_ids": [r["id"] for r in recuperados],
    }

