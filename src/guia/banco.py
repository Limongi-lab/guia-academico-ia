"""Conexão e criação de esquema para o banco guia (PostgreSQL + pgvector)."""
import os

import psycopg
from pgvector.psycopg import register_vector

_DSN_PADRAO = "postgresql://guia:guia@localhost:5432/guia"


def conectar(dsn: str | None = None) -> psycopg.Connection:
    """Abre conexão com autocommit, habilita a extensão vector e registra o tipo.

    Ordem de precedência: argumento dsn > GUIA_DATABASE_URL > DSN padrão.
    """
    dsn_efetivo = dsn or os.environ.get("GUIA_DATABASE_URL") or _DSN_PADRAO
    conn = psycopg.connect(dsn_efetivo, autocommit=True, connect_timeout=3)
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def criar_esquema(conn: psycopg.Connection) -> None:
    """Cria as tabelas e índices no schema corrente (idempotente)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documentos (
            id          text PRIMARY KEY,
            instituicao text,
            titulo      text,
            url         text,
            tipo        text,
            data_ref    text,
            prioridade  int
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trechos (
            id               text PRIMARY KEY,
            doc_id           text REFERENCES documentos(id) ON DELETE CASCADE,
            local_id         text,
            tipo_doc         text,
            instituicao      text,
            titulo_doc       text,
            url              text,
            data_ref         text,
            prioridade       int,
            paginas          int[],
            localizacao      jsonb,
            citacao          text,
            texto            text,
            pai_id           text,
            parte            int,
            total_partes     int,
            hash_texto       text,
            metadados        jsonb,
            embedding        vector(1024),
            embedding_modelo text,
            hash_entrada     text,
            tsv              tsvector GENERATED ALWAYS AS (
                                 to_tsvector('portuguese', coalesce(citacao, '') || ' ' || coalesce(texto, ''))
                             ) STORED
        )
    """)

    # HNSW em embedding com distância de cosseno — principal índice vetorial
    conn.execute("""
        CREATE INDEX IF NOT EXISTS trechos_embedding_hnsw
        ON trechos USING hnsw (embedding vector_cosine_ops)
    """)

    # GIN em tsv — busca textual em português
    conn.execute("""
        CREATE INDEX IF NOT EXISTS trechos_tsv_gin
        ON trechos USING gin (tsv)
    """)

    # Btree em pai_id e doc_id — filtros frequentes
    conn.execute("""
        CREATE INDEX IF NOT EXISTS trechos_pai_id_btree
        ON trechos (pai_id)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS trechos_doc_id_btree
        ON trechos (doc_id)
    """)
