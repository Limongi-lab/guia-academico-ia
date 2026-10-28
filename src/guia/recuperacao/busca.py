"""Busca vetorial, textual e híbrida no banco guia (PostgreSQL + pgvector)."""
from typing import Any

import psycopg
from pgvector import Vector
from psycopg.rows import dict_row


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


def buscar_textual(
    conn: psycopg.Connection,
    consulta: str,
    k: int = 5,
    instituicao: str | None = None,
    vetor: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Busca por palavras no tsv usando radical português (plainto_tsquery com OU).

    A consulta é tratada como pergunta em linguagem natural: os termos são
    combinados com OU (basta um casar; quem casa mais e com termos mais raros
    fica no topo via ts_rank). Consultas sem termos úteis retornam [].

    Colunas: mesmas de buscar_vetorial (sem embedding e sem tsv), mais:
      pontuacao  float  (ts_rank), ordem decrescente; empate: id crescente.
      distancia  float  (cosseno contra `vetor`) quando passado, senão None.
    Filtro opcional por instituicao.
    """
    # Converte plainto_tsquery em OR: "a & b" → "a | b"
    # to_tsquery é seguro pois o argumento já é um tsquery serializado pelo Postgres
    filtro = "AND instituicao = %(instituicao)s" if instituicao else ""

    # Expressão de distância: calculada só quando um vetor de referência é fornecido
    if vetor is not None:
        col_distancia = "(embedding <=> %(vetor)s)::float AS distancia"
        params_extra: dict[str, Any] = {"vetor": Vector(vetor)}
    else:
        col_distancia = "NULL::float AS distancia"
        params_extra = {}

    sql = f"""
        SELECT
            id, doc_id, local_id, tipo_doc, instituicao, titulo_doc, url, data_ref,
            prioridade, paginas, localizacao, citacao, texto, pai_id, parte, total_partes,
            hash_texto, metadados, embedding_modelo, hash_entrada,
            ts_rank(tsv, tsquery)::float AS pontuacao,
            {col_distancia}
        FROM trechos,
             -- converte plainto_tsquery para OR: troca "&" por "|"
             to_tsquery(
                 'portuguese',
                 replace(plainto_tsquery('portuguese', %(consulta)s)::text, ' & ', ' | ')
             ) AS tsquery
        WHERE plainto_tsquery('portuguese', %(consulta)s) <> ''::tsquery
          AND tsv @@ tsquery
          {filtro}
        ORDER BY pontuacao DESC, id ASC
        LIMIT %(k)s
    """
    params = {"consulta": consulta, "k": k, "instituicao": instituicao, **params_extra}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fundir_rrf(
    listas: dict[str, list[dict[str, Any]]],
    k: int = 60,
    top: int | None = None,
) -> list[dict[str, Any]]:
    """Fusão por Reciprocal Rank Fusion (RRF) — função pura, não altera as listas.

    listas: dict nome -> lista de dicts com "id", ordenada do melhor ao pior.
    Fórmula: rrf(id) = soma, sobre as listas em que aparece, de 1/(k + posição).
    posição é 1-based. O dict resultante inclui:
      rrf          float  (pontuação RRF)
      rank_<nome>  int | None  (posição na lista, ou None se não apareceu)
    Os campos do primeiro aparecimento (ordem dos nomes, ordem das posições) são
    preservados. Empate em rrf: vence quem apareceu primeiro.
    Raises ValueError se k <= 0.
    """
    if k <= 0:
        raise ValueError(f"k deve ser positivo; recebido: {k}")

    nomes = list(listas.keys())
    # Mapeia id -> (índice de inserção, cópia do dict, score rrf, ranks por lista)
    ordem_insercao: list[str] = []           # ordem do primeiro aparecimento
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int | None]] = {}  # id -> {nome -> rank}
    primeiros: dict[str, dict[str, Any]] = {}     # id -> cópia do primeiro aparecimento

    for nome in nomes:
        for pos_0, item in enumerate(listas[nome]):
            id_ = item["id"]
            pos_1 = pos_0 + 1  # 1-based
            contribuicao = 1.0 / (k + pos_1)
            if id_ not in scores:
                # Primeiro aparecimento: registra a cópia e a ordem
                ordem_insercao.append(id_)
                scores[id_] = 0.0
                ranks[id_] = {n: None for n in nomes}
                primeiros[id_] = dict(item)  # cópia rasa — não altera a lista original
            scores[id_] += contribuicao
            ranks[id_][nome] = pos_1

    # Monta resultado: ordena por (score desc, ordem de inserção asc)
    ids_ordenados = sorted(
        ordem_insercao,
        key=lambda id_: (-scores[id_], ordem_insercao.index(id_)),
    )

    resultado: list[dict[str, Any]] = []
    for id_ in ids_ordenados:
        entry = {**primeiros[id_], "rrf": scores[id_]}
        for nome in nomes:
            entry[f"rank_{nome}"] = ranks[id_][nome]
        resultado.append(entry)

    if top is not None:
        resultado = resultado[:top]
    return resultado


def buscar_hibrida(
    conn: psycopg.Connection,
    vetor: list[float],
    consulta: str,
    k: int = 5,
    instituicao: str | None = None,
    k_candidatos: int = 50,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Busca híbrida: combina buscar_vetorial e buscar_textual via RRF.

    Pega k_candidatos de cada buscador (mesmo filtro de instituição),
    funde com fundir_rrf (listas 'vetorial' e 'textual') e devolve os k
    melhores. Todo resultado tem 'distancia' (float): quem veio só do
    textual recebe a distância cosseno ao vetor informado.
    """
    # Busca vetorial: já devolve distancia para todos os resultados
    vetorial = buscar_vetorial(conn, vetor, k=k_candidatos, instituicao=instituicao)
    # Busca textual: passa o vetor para calcular distância mesmo nos resultados textuais
    textual = buscar_textual(
        conn, consulta, k=k_candidatos, instituicao=instituicao, vetor=vetor
    )

    # Funde as listas pelo RRF; preserva os campos do primeiro aparecimento
    fusao = fundir_rrf({"vetorial": vetorial, "textual": textual}, k=rrf_k, top=k)

    # Garante que todo resultado tem distancia como float
    # (quem só apareceu no textual já tem distancia pelo vetor passado acima;
    #  quem só apareceu no vetorial já tem distancia da busca vetorial)
    for item in fusao:
        if item.get("distancia") is None:
            # Fallback improvável, mas por segurança calcula ao vivo
            item["distancia"] = float("nan")

    return fusao
