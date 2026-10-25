"""Ingestão de documentos e trechos no banco guia (carga idempotente com embeddings)."""
import hashlib
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

DIMENSAO = 1024  # dimensão esperada dos vetores de embedding


def entrada_embedding(trecho: dict) -> str:
    """Texto usado como entrada para gerar o embedding de um trecho.

    Formato: "{titulo_doc}\\n{citacao}\\n\\n{texto}"
    """
    return f"{trecho['titulo_doc']}\n{trecho['citacao']}\n\n{trecho['texto']}"


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def ingerir_documento(
    conn: psycopg.Connection,
    doc: dict,
    trechos: list[dict],
    embedder: Callable[[list[str]], list[list[float]]],
    modelo: str,
    lote: int = 32,
) -> dict[str, int]:
    """Faz upsert de doc + trechos, gerando embeddings apenas quando necessário.

    Retorna dict com: inseridos, atualizados, inalterados, removidos, embeddings_gerados.

    Estratégia:
    - Calcula hash_entrada (sha256 da string de entrada do embedding) para cada trecho.
    - Compara com o que já está no banco: se hash_entrada e modelo coincidem → inalterado
      (reutiliza embedding existente); caso contrário → atualizado (novo embedding).
    - Trechos cujo id não existe → inseridos (precisam de embedding).
    - Pede embeddings em lotes ANTES de abrir a transação; se o embedder lançar exceção,
      nada é gravado.
    """
    ids_novos = [t["id"] for t in trechos]

    # Lê estado atual dos trechos deste documento no banco
    linhas_banco: dict[str, tuple[str, str]] = {}  # id -> (hash_entrada, embedding_modelo)
    if ids_novos:
        rows = conn.execute(
            "SELECT id, hash_entrada, embedding_modelo FROM trechos WHERE doc_id = %s",
            (doc["id"],),
        ).fetchall()
        linhas_banco = {r[0]: (r[1], r[2]) for r in rows}

    # Classifica cada trecho e coleta os que precisam de novo embedding
    precisa_embed: list[int] = []  # índices em `trechos`
    for i, t in enumerate(trechos):
        h = _sha256(entrada_embedding(t))
        banco = linhas_banco.get(t["id"])
        if banco is None:
            precisa_embed.append(i)  # novo trecho
        elif banco[0] != h or banco[1] != modelo:
            precisa_embed.append(i)  # conteúdo ou modelo mudou

    # Pede embeddings ANTES da transação — se falhar, não grava nada
    textos_para_embed = [entrada_embedding(trechos[i]) for i in precisa_embed]
    vetores: list[list[float]] = []
    if textos_para_embed:
        for inicio in range(0, len(textos_para_embed), lote):
            fatia = textos_para_embed[inicio : inicio + lote]
            vetores.extend(embedder(fatia))  # pode lançar exceção → aborta tudo

    # Valida o que o embedder devolveu ANTES de abrir a transacao
    if len(vetores) != len(precisa_embed):
        raise ValueError(
            f"O embedder devolveu {len(vetores)} vetor(es) "
            f"para {len(precisa_embed)} texto(s) solicitados."
        )
    for k, v in enumerate(vetores):
        if len(v) != DIMENSAO:
            raise ValueError(
                f"Vetor {k} retornado pelo embedder tem dimensao {len(v)}, "
                f"esperado {DIMENSAO}."
            )

    # Mapa índice-em-precisa_embed → vetor
    novo_vetor: dict[int, list[float]] = {precisa_embed[k]: vetores[k] for k in range(len(vetores))}

    # Busca embeddings existentes para trechos inalterados
    ids_inalterados = [t["id"] for i, t in enumerate(trechos) if i not in novo_vetor]
    emb_existente: dict[str, Any] = {}
    if ids_inalterados:
        rows2 = conn.execute(
            "SELECT id, embedding FROM trechos WHERE id = ANY(%s)",
            (ids_inalterados,),
        ).fetchall()
        emb_existente = {r[0]: r[1] for r in rows2}

    # ---------- transação única ----------
    inseridos = atualizados = inalterados = 0

    with conn.transaction():
        # Upsert documento
        conn.execute(
            """
            INSERT INTO documentos (id, instituicao, titulo, url, tipo, data_ref, prioridade)
            VALUES (%(id)s, %(instituicao)s, %(titulo)s, %(url)s, %(tipo)s, %(data_ref)s, %(prioridade)s)
            ON CONFLICT (id) DO UPDATE SET
                instituicao = EXCLUDED.instituicao,
                titulo      = EXCLUDED.titulo,
                url         = EXCLUDED.url,
                tipo        = EXCLUDED.tipo,
                data_ref    = EXCLUDED.data_ref,
                prioridade  = EXCLUDED.prioridade
            """,
            doc,
        )

        # Upsert trechos
        for i, t in enumerate(trechos):
            h = _sha256(entrada_embedding(t))
            if i in novo_vetor:
                vetor = novo_vetor[i]
                h_entrada = h
            else:
                vetor = emb_existente.get(t["id"])
                h_entrada = h  # mantém hash atual mesmo sem novo embedding

            banco = linhas_banco.get(t["id"])
            if banco is None:
                inseridos += 1
            elif banco[0] != h or banco[1] != modelo:
                atualizados += 1
            else:
                inalterados += 1

            conn.execute(
                """
                INSERT INTO trechos (
                    id, doc_id, local_id, tipo_doc, instituicao, titulo_doc, url, data_ref,
                    prioridade, paginas, localizacao, citacao, texto, pai_id, parte, total_partes,
                    hash_texto, metadados, embedding, embedding_modelo, hash_entrada
                ) VALUES (
                    %(id)s, %(doc_id)s, %(local_id)s, %(tipo_doc)s, %(instituicao)s,
                    %(titulo_doc)s, %(url)s, %(data_ref)s, %(prioridade)s, %(paginas)s,
                    %(localizacao)s, %(citacao)s, %(texto)s, %(pai_id)s, %(parte)s,
                    %(total_partes)s, %(hash_texto)s, %(metadados)s, %(embedding)s,
                    %(embedding_modelo)s, %(hash_entrada)s
                )
                ON CONFLICT (id) DO UPDATE SET
                    doc_id           = EXCLUDED.doc_id,
                    local_id         = EXCLUDED.local_id,
                    tipo_doc         = EXCLUDED.tipo_doc,
                    instituicao      = EXCLUDED.instituicao,
                    titulo_doc       = EXCLUDED.titulo_doc,
                    url              = EXCLUDED.url,
                    data_ref         = EXCLUDED.data_ref,
                    prioridade       = EXCLUDED.prioridade,
                    paginas          = EXCLUDED.paginas,
                    localizacao      = EXCLUDED.localizacao,
                    citacao          = EXCLUDED.citacao,
                    texto            = EXCLUDED.texto,
                    pai_id           = EXCLUDED.pai_id,
                    parte            = EXCLUDED.parte,
                    total_partes     = EXCLUDED.total_partes,
                    hash_texto       = EXCLUDED.hash_texto,
                    metadados        = EXCLUDED.metadados,
                    embedding        = EXCLUDED.embedding,
                    embedding_modelo = EXCLUDED.embedding_modelo,
                    hash_entrada     = EXCLUDED.hash_entrada
                """,
                {
                    **t,
                    "paginas": t.get("paginas"),
                    "localizacao": Jsonb(t.get("localizacao")),
                    "metadados": Jsonb(t.get("metadados")),
                    "embedding": vetor,
                    "embedding_modelo": modelo,
                    "hash_entrada": h_entrada,
                },
            )

        # Remove trechos do documento que não estão mais na lista
        ids_set = ids_novos or []
        removidos_rows = conn.execute(
            """
            DELETE FROM trechos
            WHERE doc_id = %s AND id != ALL(%s)
            RETURNING id
            """,
            (doc["id"], ids_set),
        ).fetchall()
        removidos = len(removidos_rows)

    return {
        "inseridos": inseridos,
        "atualizados": atualizados,
        "inalterados": inalterados,
        "removidos": removidos,
        "embeddings_gerados": len(vetores),
    }
