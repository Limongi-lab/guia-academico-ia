"""Busca vetorial no banco guia (PostgreSQL + pgvector)."""
from typing import Any

import psycopg
from psycopg.rows import dict_row
from pgvector import Vector


def buscar_vetorial(
    conn: psycopg.Connection,
    vetor: list[float],
    k: int = 5,
    instituicao: str | None = None,
) -> list[dict[str, Any]]:
    """Retorna os k trechos mais próximos do vetor por distância de cosseno.

    Colunas retornadas: todas menos embedding e tsv, mais "distancia" (float).
    Ordem: crescente por distância (mais próximo primeiro).
    Filtro opcional por instituicao.
    """
    filtro = "AND instituicao = %(instituicao)s" if instituicao else ""
    sql = f"""
        SELECT
            id, doc_id, local_id, tipo_doc, instituicao, titulo_doc, url, data_ref,
            prioridade, paginas, localizacao, citacao, texto, pai_id, parte, total_partes,
            hash_texto, metadados, embedding_modelo, hash_entrada,
            (embedding <=> %(vetor)s)::float AS distancia
        FROM trechos
        WHERE embedding IS NOT NULL
        {filtro}
        ORDER BY embedding <=> %(vetor)s
        LIMIT %(k)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"vetor": Vector(vetor), "k": k, "instituicao": instituicao})
        return cur.fetchall()
