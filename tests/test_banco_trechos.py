"""Banco de trechos (PostgreSQL + pgvector): esquema, carga idempotente e busca vetorial.

Contratos:
  guia.banco
      conectar(dsn=None) -> psycopg.Connection   (autocommit; usa GUIA_DATABASE_URL ou
                                                  postgresql://guia:guia@localhost:5432/guia;
                                                  garante a extensão vector e registra o tipo)
      criar_esquema(conn) -> None                (idempotente; cria no schema corrente)
  guia.ingestao.carga
      DIMENSAO = 1024
      entrada_embedding(trecho) -> str           ("titulo_doc\\ncitacao\\n\\ntexto")
      ingerir_documento(conn, doc, trechos, embedder, modelo, lote=32) -> dict
          estatísticas: inseridos, atualizados, inalterados, removidos, embeddings_gerados
  guia.recuperacao.busca
      buscar_vetorial(conn, vetor, k=5, instituicao=None) -> list[dict]
Os testes usam o PostgreSQL do Docker (guia-db) num schema temporário por teste e são
pulados se o banco não estiver acessível. Um "embedder" é qualquer função que recebe uma
lista de textos e devolve uma lista de vetores de 1024 floats.
"""
import hashlib
import math
import re
import uuid

import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.ingestao.carga import DIMENSAO, entrada_embedding, ingerir_documento
from guia.recuperacao.busca import buscar_vetorial

MODELO = "bge-m3"


# ---------- apoio ----------

def _vetor(texto):
    v = [0.0] * DIMENSAO
    for palavra in re.findall(r"\w+", texto.lower()):
        v[int(hashlib.md5(palavra.encode()).hexdigest(), 16) % DIMENSAO] += 1.0
    norma = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norma for x in v]


class EmbedderFalso:
    def __init__(self):
        self.chamadas = []

    def __call__(self, textos):
        self.chamadas.append(list(textos))
        return [_vetor(t) for t in textos]

    @property
    def total(self):
        return sum(len(c) for c in self.chamadas)


def _doc(doc_id="doc-a", instituicao="ufu", titulo="Documento A", prioridade=1):
    return {
        "id": doc_id,
        "instituicao": instituicao,
        "titulo": titulo,
        "url": f"https://exemplo.edu.br/{doc_id}.pdf",
        "tipo": "pdf",
        "data_ref": "2024-04-18",
        "prioridade": prioridade,
    }


def _trecho(doc, n, texto, citacao=None, **extra):
    citacao = citacao or f"Art. {n}º, p. {n}"
    registro = {
        "id": f"{doc['id']}/art-{n}#1",
        "doc_id": doc["id"],
        "local_id": f"art-{n}#1",
        "tipo_doc": "resolucao",
        "instituicao": doc["instituicao"],
        "titulo_doc": doc["titulo"],
        "url": doc["url"],
        "data_ref": doc["data_ref"],
        "prioridade": doc["prioridade"],
        "paginas": [n],
        "localizacao": {"capitulo": "", "secao": "", "artigo": str(n)},
        "citacao": citacao,
        "texto": texto,
        "pai_id": f"{doc['id']}/art-{n}",
        "parte": 1,
        "total_partes": 1,
        "hash_texto": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        "metadados": {"alteracoes": []},
    }
    registro.update(extra)
    return registro


def _tres(doc=None):
    doc = doc or _doc()
    return doc, [
        _trecho(doc, 1, "O estágio obrigatório tem duração mínima de 300 horas."),
        _trecho(doc, 2, "O trancamento de matrícula deve ser pedido dentro do semestre letivo."),
        _trecho(doc, 3, "O calendário acadêmico define datas e prazos do período letivo."),
    ]


@pytest.fixture
def conn():
    try:
        c = conectar()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL do Docker (guia-db) não está acessível")
    schema = f"teste_{uuid.uuid4().hex[:10]}"
    c.execute(f"CREATE SCHEMA {schema}")
    c.execute(f"SET search_path TO {schema}, public")
    criar_esquema(c)
    try:
        yield c
    finally:
        c.execute(f"DROP SCHEMA {schema} CASCADE")
        c.close()


def _contar(conn, tabela, onde="true", params=()):
    return conn.execute(f"select count(*) from {tabela} where {onde}", params).fetchone()[0]


# ---------- esquema ----------

def test_esquema_tem_tabelas_e_indices_e_e_idempotente(conn):
    criar_esquema(conn)  # segunda vez não pode falhar
    tabelas = {
        r[0]
        for r in conn.execute(
            "select table_name from information_schema.tables where table_schema = current_schema()"
        )
    }
    assert {"documentos", "trechos"} <= tabelas
    defs = " ".join(
        r[0] for r in conn.execute("select indexdef from pg_indexes where schemaname = current_schema()")
    )
    assert "hnsw" in defs and "vector_cosine_ops" in defs
    assert "gin" in defs


def test_entrada_do_embedding_junta_titulo_citacao_e_texto():
    doc = _doc(titulo="Normas Gerais")
    t = _trecho(doc, 2, "Texto do artigo.", citacao="Art. 2º, p. 2")
    assert entrada_embedding(t) == "Normas Gerais\nArt. 2º, p. 2\n\nTexto do artigo."


# ---------- carga ----------

def test_primeira_carga_insere_documento_trechos_e_embeddings(conn):
    doc, trechos = _tres()
    emb = EmbedderFalso()
    stats = ingerir_documento(conn, doc, trechos, emb, MODELO)
    assert stats == {
        "inseridos": 3, "atualizados": 0, "inalterados": 0, "removidos": 0, "embeddings_gerados": 3,
    }
    assert _contar(conn, "documentos") == 1
    assert _contar(conn, "trechos") == 3
    linha = conn.execute(
        "select citacao, paginas, localizacao->>'artigo', metadados->'alteracoes', "
        "embedding_modelo, vector_dims(embedding), hash_texto from trechos where id = %s",
        (trechos[0]["id"],),
    ).fetchone()
    assert linha[0] == "Art. 1º, p. 1"
    assert linha[1] == [1]
    assert linha[2] == "1"
    assert linha[3] == []
    assert linha[4] == MODELO
    assert linha[5] == DIMENSAO
    assert linha[6] == trechos[0]["hash_texto"]


def test_recarga_identica_nao_gera_embeddings(conn):
    doc, trechos = _tres()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)
    emb2 = EmbedderFalso()
    stats = ingerir_documento(conn, doc, trechos, emb2, MODELO)
    assert stats == {
        "inseridos": 0, "atualizados": 0, "inalterados": 3, "removidos": 0, "embeddings_gerados": 0,
    }
    assert emb2.chamadas == []
    assert _contar(conn, "trechos") == 3


def test_texto_alterado_regenera_so_o_embedding_daquele_trecho(conn):
    doc, trechos = _tres()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)
    novos = [dict(t) for t in trechos]
    novos[1] = _trecho(doc, 2, "O trancamento de matrícula agora tem outro prazo.")
    emb = EmbedderFalso()
    stats = ingerir_documento(conn, doc, novos, emb, MODELO)
    assert (stats["atualizados"], stats["inalterados"], stats["embeddings_gerados"]) == (1, 2, 1)
    assert emb.total == 1
    texto = conn.execute("select texto from trechos where id = %s", (novos[1]["id"],)).fetchone()[0]
    assert texto == "O trancamento de matrícula agora tem outro prazo."


def test_titulo_do_documento_mudou_regenera_todos(conn):
    doc, trechos = _tres()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)
    doc2 = _doc(titulo="Documento A (nova edição)")
    novos = [dict(t, titulo_doc=doc2["titulo"]) for t in trechos]
    stats = ingerir_documento(conn, doc2, novos, EmbedderFalso(), MODELO)
    assert (stats["atualizados"], stats["embeddings_gerados"]) == (3, 3)
    assert conn.execute("select titulo from documentos where id = %s", (doc["id"],)).fetchone()[0] == (
        "Documento A (nova edição)"
    )


def test_modelo_diferente_regenera_todos(conn):
    doc, trechos = _tres()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)
    stats = ingerir_documento(conn, doc, trechos, EmbedderFalso(), "outro-modelo")
    assert (stats["atualizados"], stats["embeddings_gerados"]) == (3, 3)
    modelos = {r[0] for r in conn.execute("select embedding_modelo from trechos")}
    assert modelos == {"outro-modelo"}


def test_mudanca_so_de_metadados_atualiza_a_linha_sem_novo_embedding(conn):
    doc, trechos = _tres()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)
    doc2 = _doc(prioridade=2)
    novos = [dict(t, prioridade=2, data_ref="2026-01-01") for t in trechos]
    emb = EmbedderFalso()
    stats = ingerir_documento(conn, doc2, novos, emb, MODELO)
    assert (stats["inalterados"], stats["embeddings_gerados"]) == (3, 0)
    assert emb.chamadas == []
    assert {r[0] for r in conn.execute("select prioridade from trechos")} == {2}
    assert {r[0] for r in conn.execute("select data_ref from trechos")} == {"2026-01-01"}
    assert _contar(conn, "trechos", "embedding is not null") == 3


def test_trecho_que_saiu_do_documento_e_removido(conn):
    doc, trechos = _tres()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)
    stats = ingerir_documento(conn, doc, trechos[:2], EmbedderFalso(), MODELO)
    assert (stats["removidos"], stats["inalterados"]) == (1, 2)
    assert _contar(conn, "trechos", "id = %s", (trechos[2]["id"],)) == 0


def test_recarga_de_um_documento_nao_mexe_nos_outros(conn):
    doc_a, trechos_a = _tres(_doc("doc-a"))
    doc_b, trechos_b = _tres(_doc("doc-b", instituicao="uniube", titulo="Documento B"))
    ingerir_documento(conn, doc_a, trechos_a, EmbedderFalso(), MODELO)
    ingerir_documento(conn, doc_b, trechos_b, EmbedderFalso(), MODELO)
    ingerir_documento(conn, doc_a, trechos_a[:1], EmbedderFalso(), MODELO)
    assert _contar(conn, "trechos", "doc_id = 'doc-a'") == 1
    assert _contar(conn, "trechos", "doc_id = 'doc-b'") == 3


def test_embeddings_sao_pedidos_em_lotes(conn):
    doc = _doc()
    trechos = [_trecho(doc, n, f"Texto numero {n} do documento.") for n in range(1, 6)]
    emb = EmbedderFalso()
    ingerir_documento(conn, doc, trechos, emb, MODELO, lote=2)
    assert [len(c) for c in emb.chamadas] == [2, 2, 1]


def test_falha_no_embedder_nao_deixa_o_banco_pela_metade(conn):
    doc, trechos = _tres()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)

    def quebrado(textos):
        raise RuntimeError("modelo indisponível")

    novos = [dict(t) for t in trechos]
    novos[0] = _trecho(doc, 1, "Texto novo que não deve chegar ao banco.")
    with pytest.raises(RuntimeError):
        ingerir_documento(conn, doc, novos, quebrado, MODELO)
    texto = conn.execute("select texto from trechos where id = %s", (trechos[0]["id"],)).fetchone()[0]
    assert texto == "O estágio obrigatório tem duração mínima de 300 horas."
    assert _contar(conn, "trechos") == 3


# ---------- busca vetorial ----------

def _preparar_busca(conn):
    doc_a, trechos_a = _tres(_doc("doc-a", instituicao="ufu"))
    doc_b = _doc("doc-b", instituicao="uniube", titulo="Documento A")
    trechos_b = [_trecho(doc_b, 1, "O estágio obrigatório na UNIUBE exige relatório final.")]
    emb = EmbedderFalso()
    ingerir_documento(conn, doc_a, trechos_a, emb, MODELO)
    ingerir_documento(conn, doc_b, trechos_b, emb, MODELO)
    return emb, trechos_a, trechos_b


def test_busca_devolve_o_mais_proximo_primeiro_com_distancia_crescente(conn):
    emb, trechos_a, _ = _preparar_busca(conn)
    consulta = emb(["quantas horas tem o estágio obrigatório"])[0]
    r = buscar_vetorial(conn, consulta, k=4)
    assert r[0]["id"] == trechos_a[0]["id"]
    distancias = [x["distancia"] for x in r]
    assert distancias == sorted(distancias)
    assert all(isinstance(d, float) for d in distancias)


def test_busca_respeita_k_e_devolve_o_registro_sem_o_vetor(conn):
    emb, trechos_a, _ = _preparar_busca(conn)
    consulta = emb(["trancamento de matrícula"])[0]
    r = buscar_vetorial(conn, consulta, k=2)
    assert len(r) == 2
    primeiro = r[0]
    assert primeiro["id"] == trechos_a[1]["id"]
    assert primeiro["citacao"] == "Art. 2º, p. 2"
    assert primeiro["paginas"] == [2]
    assert primeiro["localizacao"]["artigo"] == "2"
    assert primeiro["titulo_doc"] == "Documento A"
    assert primeiro["texto"] == trechos_a[1]["texto"]
    assert "embedding" not in primeiro and "tsv" not in primeiro


def test_busca_filtra_por_instituicao(conn):
    emb, _, trechos_b = _preparar_busca(conn)
    consulta = emb(["estágio obrigatório"])[0]
    r = buscar_vetorial(conn, consulta, k=10, instituicao="uniube")
    assert [x["id"] for x in r] == [trechos_b[0]["id"]]
    assert {x["instituicao"] for x in buscar_vetorial(conn, consulta, k=10)} == {"ufu", "uniube"}
