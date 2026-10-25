"""Carga do corpus no banco: fontes.json + data/processed/trechos/<doc_id>.jsonl.

Contrato (guia.ingestao.corpus):
  ler_corpus(fontes, dir_trechos) -> dict                      (não usa banco nem embedder)
      fontes: lista de dicts de fontes.json (id, instituicao, titulo, url, tipo, data_ref, prioridade)
      dir_trechos: Path ou str; lê <dir_trechos>/<fonte["id"]>.jsonl (UTF-8, um trecho por linha;
                   linhas em branco são ignoradas)
      devolve {
        "documentos": [(fonte, trechos), ...]   só fontes com >= 1 trecho, na ordem de `fontes`
        "sem_trechos": [ids]                    fonte sem arquivo, ou com arquivo vazio
        "sem_fonte": [nomes]                    .jsonl da pasta sem fonte correspondente (ordenado,
                                                nome sem a extensão)
      }
      ValueError (e nada é carregado) se uma linha não for JSON válido (a mensagem traz o nome do
      arquivo e "linha N") ou se algum trecho tiver doc_id diferente do id da fonte (a mensagem
      traz o nome do arquivo e o id do trecho).
  carregar_corpus(conn, fontes, dir_trechos, embedder, modelo, lote=32) -> dict
      chama ler_corpus (valida TUDO antes de gravar qualquer coisa) e depois
      ingerir_documento(conn, fonte, trechos, embedder, modelo, lote) para cada documento.
      devolve {
        "por_documento": {id: stats de ingerir_documento},
        "totais": {inseridos, atualizados, inalterados, removidos, embeddings_gerados} somados,
        "sem_trechos": [...], "sem_fonte": [...]
      }
      Arquivo vazio NÃO apaga os trechos já gravados do documento (vai para sem_trechos).

Contrato novo de guia.ingestao.carga.ingerir_documento: se o embedder devolver número de vetores
diferente do pedido ou vetores com dimensão != DIMENSAO, levanta ValueError antes de abrir a
transação; nada é gravado (nem documento, nem trechos).

Testes de banco usam schema temporário e são pulados sem o Docker (guia-db).
"""
import hashlib
import json
import math
import re
import uuid

import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.ingestao.carga import DIMENSAO, ingerir_documento
from guia.ingestao.corpus import carregar_corpus, ler_corpus

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


def _fonte(doc_id, instituicao="ufu", titulo=None, prioridade=1):
    return {
        "id": doc_id,
        "instituicao": instituicao,
        "titulo": titulo or f"Documento {doc_id}",
        "url": f"https://exemplo.edu.br/{doc_id}.pdf",
        "tipo": "pdf",
        "data_ref": "2024-04-18",
        "prioridade": prioridade,
    }


def _trecho(fonte, n, texto):
    return {
        "id": f"{fonte['id']}/art-{n}#1",
        "doc_id": fonte["id"],
        "local_id": f"art-{n}#1",
        "tipo_doc": "resolucao",
        "instituicao": fonte["instituicao"],
        "titulo_doc": fonte["titulo"],
        "url": fonte["url"],
        "data_ref": fonte["data_ref"],
        "prioridade": fonte["prioridade"],
        "paginas": [n],
        "localizacao": {"artigo": str(n)},
        "citacao": f"Art. {n}º, p. {n}",
        "texto": texto,
        "pai_id": f"{fonte['id']}/art-{n}",
        "parte": 1,
        "total_partes": 1,
        "hash_texto": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        "metadados": {"alteracoes": []},
    }


def _escrever(pasta, doc_id, trechos, extra=""):
    linhas = [json.dumps(t, ensure_ascii=False) for t in trechos]
    (pasta / f"{doc_id}.jsonl").write_text("\n".join(linhas) + "\n" + extra, encoding="utf-8")


@pytest.fixture
def pasta(tmp_path):
    p = tmp_path / "trechos"
    p.mkdir()
    return p


@pytest.fixture
def corpus(pasta):
    """Duas fontes com arquivo (3 e 2 trechos), uma sem arquivo e um arquivo órfão."""
    a, b, c = _fonte("doc-a"), _fonte("doc-b", instituicao="uniube"), _fonte("doc-c")
    _escrever(pasta, "doc-a", [
        _trecho(a, 1, "O estágio obrigatório tem duração mínima de 300 horas."),
        _trecho(a, 2, "O trancamento de matrícula deve ser pedido dentro do semestre letivo."),
        _trecho(a, 3, "Informações sobre avaliação e aprovação: nota mínima 60 pontos."),
    ])
    _escrever(pasta, "doc-b", [
        _trecho(b, 1, "O calendário acadêmico define datas e prazos."),
        _trecho(b, 2, "A colação de grau ocorre em data fixada pela coordenação."),
    ])
    _escrever(pasta, "orfao", [_trecho(_fonte("orfao"), 1, "Sem fonte correspondente.")])
    return [a, b, c], pasta


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


# ---------- ler_corpus (sem banco) ----------

def test_ler_corpus_separa_documentos_sem_trechos_e_sem_fonte(corpus):
    fontes, pasta = corpus
    r = ler_corpus(fontes, pasta)
    assert [f["id"] for f, _ in r["documentos"]] == ["doc-a", "doc-b"]
    assert [len(ts) for _, ts in r["documentos"]] == [3, 2]
    assert r["sem_trechos"] == ["doc-c"]
    assert r["sem_fonte"] == ["orfao"]


def test_ler_corpus_mantem_a_ordem_de_fontes_e_aceita_str(corpus):
    fontes, pasta = corpus
    r = ler_corpus(list(reversed(fontes)), str(pasta))
    assert [f["id"] for f, _ in r["documentos"]] == ["doc-b", "doc-a"]


def test_ler_corpus_preserva_acentos_e_ignora_linhas_em_branco(pasta):
    a = _fonte("doc-a")
    t = _trecho(a, 1, "Avaliação de aprendizagem: não é permitida a reprovação sem ciência.")
    (pasta / "doc-a.jsonl").write_text(
        "\n" + json.dumps(t, ensure_ascii=False) + "\n\n   \n", encoding="utf-8"
    )
    r = ler_corpus([a], pasta)
    assert r["documentos"][0][1] == [t]


def test_arquivo_vazio_vira_sem_trechos(pasta):
    a = _fonte("doc-a")
    (pasta / "doc-a.jsonl").write_text("\n\n", encoding="utf-8")
    r = ler_corpus([a], pasta)
    assert r["documentos"] == [] and r["sem_trechos"] == ["doc-a"]


def test_json_invalido_levanta_valueerror_com_arquivo_e_linha(pasta):
    a = _fonte("doc-a")
    _escrever(pasta, "doc-a", [_trecho(a, 1, "ok")], extra="{isto nao e json\n")
    with pytest.raises(ValueError) as erro:
        ler_corpus([a], pasta)
    msg = str(erro.value)
    assert "doc-a.jsonl" in msg and "linha 2" in msg


def test_doc_id_diferente_da_fonte_levanta_valueerror(pasta):
    a, outro = _fonte("doc-a"), _fonte("doc-x")
    _escrever(pasta, "doc-a", [_trecho(a, 1, "ok"), _trecho(outro, 2, "de outro documento")])
    with pytest.raises(ValueError) as erro:
        ler_corpus([a], pasta)
    msg = str(erro.value)
    assert "doc-a.jsonl" in msg and "doc-x/art-2#1" in msg


# ---------- carregar_corpus (banco) ----------

def test_carrega_documentos_e_trechos_com_metadados_da_fonte(conn, corpus):
    fontes, pasta = corpus
    emb = EmbedderFalso()
    r = carregar_corpus(conn, fontes, pasta, emb, MODELO)
    assert set(r["por_documento"]) == {"doc-a", "doc-b"}
    assert r["por_documento"]["doc-a"]["inseridos"] == 3
    assert r["por_documento"]["doc-b"]["inseridos"] == 2
    assert r["totais"] == {
        "inseridos": 5, "atualizados": 0, "inalterados": 0, "removidos": 0, "embeddings_gerados": 5,
    }
    assert r["sem_trechos"] == ["doc-c"] and r["sem_fonte"] == ["orfao"]
    assert _contar(conn, "documentos") == 2
    assert _contar(conn, "trechos") == 5
    assert _contar(conn, "trechos", "embedding is not null and embedding_modelo = %s", (MODELO,)) == 5
    inst, prio = conn.execute(
        "select instituicao, prioridade from documentos where id = 'doc-b'"
    ).fetchone()
    assert (inst, prio) == ("uniube", 1)
    # fonte sem arquivo e arquivo órfão não entram no banco
    assert _contar(conn, "documentos", "id in ('doc-c', 'orfao')") == 0


def test_segunda_carga_nao_gera_embeddings(conn, corpus):
    fontes, pasta = corpus
    carregar_corpus(conn, fontes, pasta, EmbedderFalso(), MODELO)
    emb2 = EmbedderFalso()
    r = carregar_corpus(conn, fontes, pasta, emb2, MODELO)
    assert emb2.total == 0
    assert r["totais"]["inalterados"] == 5
    assert r["totais"]["inseridos"] == 0 and r["totais"]["embeddings_gerados"] == 0
    assert _contar(conn, "trechos") == 5


def test_trecho_alterado_ou_removido_no_arquivo_e_refletido(conn, corpus):
    fontes, pasta = corpus
    carregar_corpus(conn, fontes, pasta, EmbedderFalso(), MODELO)
    a = fontes[0]
    _escrever(pasta, "doc-a", [
        _trecho(a, 1, "O estágio obrigatório tem duração mínima de 400 horas."),  # mudou
        _trecho(a, 2, "O trancamento de matrícula deve ser pedido dentro do semestre letivo."),
        # art. 3 saiu
    ])
    emb = EmbedderFalso()
    r = carregar_corpus(conn, fontes, pasta, emb, MODELO)
    assert r["por_documento"]["doc-a"] == {
        "inseridos": 0, "atualizados": 1, "inalterados": 1, "removidos": 1, "embeddings_gerados": 1,
    }
    assert emb.total == 1
    assert _contar(conn, "trechos", "doc_id = 'doc-a'") == 2


def test_respeita_o_tamanho_de_lote(conn, pasta):
    a = _fonte("doc-a")
    _escrever(pasta, "doc-a", [_trecho(a, n, f"Texto numero {n} do artigo.") for n in range(1, 6)])
    emb = EmbedderFalso()
    carregar_corpus(conn, [a], pasta, emb, MODELO, lote=2)
    assert [len(c) for c in emb.chamadas] == [2, 2, 1]


def test_arquivo_vazio_nao_apaga_o_que_ja_estava_no_banco(conn, corpus):
    fontes, pasta = corpus
    carregar_corpus(conn, fontes, pasta, EmbedderFalso(), MODELO)
    (pasta / "doc-a.jsonl").write_text("", encoding="utf-8")
    r = carregar_corpus(conn, fontes, pasta, EmbedderFalso(), MODELO)
    assert "doc-a" in r["sem_trechos"] and "doc-a" not in r["por_documento"]
    assert _contar(conn, "trechos", "doc_id = 'doc-a'") == 3


def test_erro_de_validacao_em_qualquer_arquivo_nao_grava_nada(conn, pasta):
    a, b, outro = _fonte("doc-a"), _fonte("doc-b"), _fonte("doc-x")
    _escrever(pasta, "doc-a", [_trecho(a, 1, "tudo certo aqui")])
    _escrever(pasta, "doc-b", [_trecho(outro, 1, "doc_id errado")])
    emb = EmbedderFalso()
    with pytest.raises(ValueError):
        carregar_corpus(conn, [a, b], pasta, emb, MODELO)
    assert emb.total == 0
    assert _contar(conn, "documentos") == 0 and _contar(conn, "trechos") == 0


# ---------- ingerir_documento: validação do que o embedder devolve ----------

def _um_doc():
    a = _fonte("doc-a")
    return a, [_trecho(a, 1, "Primeiro artigo."), _trecho(a, 2, "Segundo artigo.")]


def test_embedder_que_devolve_menos_vetores_levanta_valueerror_e_nao_grava(conn):
    doc, trechos = _um_doc()
    with pytest.raises(ValueError):
        ingerir_documento(conn, doc, trechos, lambda textos: [_vetor(textos[0])], MODELO)
    assert _contar(conn, "documentos") == 0 and _contar(conn, "trechos") == 0


def test_embedder_com_dimensao_errada_levanta_valueerror_e_nao_grava(conn):
    doc, trechos = _um_doc()
    with pytest.raises(ValueError, match="1024"):
        ingerir_documento(conn, doc, trechos, lambda textos: [[0.1, 0.2, 0.3] for _ in textos], MODELO)
    assert _contar(conn, "documentos") == 0 and _contar(conn, "trechos") == 0


def test_embedder_ruim_numa_recarga_nao_altera_o_que_ja_estava_gravado(conn):
    doc, trechos = _um_doc()
    ingerir_documento(conn, doc, trechos, EmbedderFalso(), MODELO)
    trechos[0]["texto"] = "Primeiro artigo, redação nova."
    with pytest.raises(ValueError):
        ingerir_documento(conn, doc, trechos, lambda textos: [], MODELO)
    texto = conn.execute("select texto from trechos where id = 'doc-a/art-1#1'").fetchone()[0]
    assert texto == "Primeiro artigo."
