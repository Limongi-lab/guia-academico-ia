"""Busca vetorial agrupada por artigo (pai_id).

Motivo (medido): num artigo longo os trechos irmãos repetem o caput e ficam quase idênticos no
espaço vetorial; na UFU Normas Gerais o Art. 78 chegou a ocupar 4 das 5 primeiras posições
(q035, q055), empurrando para fora o artigo certo. A geração já monta o contexto buscando todos
os trechos do mesmo pai_id, então a unidade útil da recuperação é o ARTIGO.

Contrato (guia.recuperacao.busca):

  deduplicar_por_pai(resultados, k=None) -> list[dict]      (função pura)
      `resultados`: lista de dicts de busca, melhor primeiro (cada um com "id" e, em geral,
      "pai_id"). Mantém só a PRIMEIRA ocorrência de cada pai_id, preservando a ordem. Linha sem
      pai_id (ausente ou None) forma um grupo próprio, identificado pelo seu id. Cada dict
      devolvido é uma cópia da primeira ocorrência mais "ids_irmaos": ids de TODAS as linhas de
      entrada do mesmo grupo, na ordem de entrada (inclui o próprio). `k` corta depois de
      agrupar. Não altera a lista de entrada.

  buscar_vetorial_por_artigo(conn, vetor, k=5, instituicao=None, k_candidatos=30) -> list[dict]
      Pega k_candidatos trechos de buscar_vetorial (mesmo filtro de instituição), agrupa com
      deduplicar_por_pai e devolve até k artigos. Pode devolver MENOS de k se os candidatos
      acabarem (trechos irmãos consumiram o conjunto): é o comportamento esperado, não um erro.
      A "distancia" de cada artigo é a do seu melhor trecho.

Testes de banco usam schema temporário e são pulados sem o Docker (guia-db).
"""
import re
import uuid

import numpy as np
import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.ingestao.carga import DIMENSAO, ingerir_documento
from guia.recuperacao.busca import buscar_vetorial, buscar_vetorial_por_artigo, deduplicar_por_pai

MODELO = "bge-m3"


# ---------- deduplicar_por_pai (sem banco) ----------

def _r(id_, pai, **extra):
    return {"id": id_, "pai_id": pai, **extra}


def test_mantem_a_primeira_ocorrencia_de_cada_pai_na_ordem():
    entrada = [_r("a1", "A", distancia=0.1), _r("a2", "A", distancia=0.2),
               _r("b1", "B", distancia=0.3), _r("a3", "A", distancia=0.4),
               _r("c1", "C", distancia=0.5)]
    r = deduplicar_por_pai(entrada)
    assert [x["id"] for x in r] == ["a1", "b1", "c1"]
    assert r[0]["distancia"] == 0.1


def test_ids_irmaos_traz_todos_do_mesmo_pai_na_ordem_de_entrada():
    entrada = [_r("a1", "A"), _r("b1", "B"), _r("a2", "A"), _r("a3", "A")]
    r = {x["id"]: x for x in deduplicar_por_pai(entrada)}
    assert r["a1"]["ids_irmaos"] == ["a1", "a2", "a3"]
    assert r["b1"]["ids_irmaos"] == ["b1"]


def test_k_corta_depois_de_agrupar():
    entrada = [_r("a1", "A"), _r("a2", "A"), _r("a3", "A"), _r("b1", "B"), _r("c1", "C")]
    assert [x["id"] for x in deduplicar_por_pai(entrada, k=2)] == ["a1", "b1"]
    assert [x["id"] for x in deduplicar_por_pai(entrada, k=10)] == ["a1", "b1", "c1"]


def test_linha_sem_pai_forma_grupo_proprio():
    entrada = [{"id": "x1"}, _r("x2", None), _r("x3", None), _r("a1", "A")]
    r = deduplicar_por_pai(entrada)
    assert [x["id"] for x in r] == ["x1", "x2", "x3", "a1"]
    assert r[0]["ids_irmaos"] == ["x1"]


def test_lista_vazia_e_nao_altera_a_entrada():
    assert deduplicar_por_pai([]) == []
    entrada = [_r("a1", "A"), _r("a2", "A")]
    deduplicar_por_pai(entrada)
    assert entrada == [_r("a1", "A"), _r("a2", "A")]
    assert "ids_irmaos" not in entrada[0]


# ---------- buscar_vetorial_por_artigo (banco) ----------

def _vetor(*indices):
    v = np.zeros(DIMENSAO)
    for i in indices:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


class EmbedderPorMarcador:
    """[v:0+1+2] no texto -> vetor (e0+e1+e2) normalizado."""

    def __call__(self, textos):
        saida = []
        for t in textos:
            m = re.search(r"\[v:([\d+]+)\]", t)
            saida.append(_vetor(*[int(x) for x in m.group(1).split("+")]))
        return saida


def _doc(doc_id, instituicao):
    return {"id": doc_id, "instituicao": instituicao, "titulo": f"Doc {doc_id}",
            "url": f"https://exemplo.edu.br/{doc_id}", "tipo": "pdf",
            "data_ref": "2024-04-18", "prioridade": 1}


def _trecho(doc, artigo, parte, total, texto):
    return {"id": f"{doc['id']}/art-{artigo}#{parte}", "doc_id": doc["id"],
            "local_id": f"art-{artigo}#{parte}", "tipo_doc": "resolucao",
            "instituicao": doc["instituicao"], "titulo_doc": doc["titulo"], "url": doc["url"],
            "data_ref": doc["data_ref"], "prioridade": doc["prioridade"], "paginas": [1],
            "localizacao": {}, "citacao": f"Art. {artigo}", "texto": texto,
            "pai_id": f"{doc['id']}/art-{artigo}", "parte": parte, "total_partes": total,
            "hash_texto": f"h-{doc['id']}-{artigo}-{parte}", "metadados": {}}


UFU, UNIUBE = _doc("d-ufu", "ufu"), _doc("d-uniube", "uniube")
A1, A2, A3 = "d-ufu/art-78#1", "d-ufu/art-78#2", "d-ufu/art-78#3"
B1, C1, D1 = "d-ufu/art-127#1", "d-ufu/art-5#1", "d-uniube/art-50#1"
Q = _vetor(0)


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


@pytest.fixture
def banco(conn):
    emb = EmbedderPorMarcador()
    # distâncias ao vetor e0: A1 0 | A2 0,29 | A3 0,42 | B1 0,50 | C1 1,0 ; D1 (UNIUBE) 0
    ingerir_documento(conn, UFU, [
        _trecho(UFU, 78, 1, 3, "Caput do artigo setenta e oito, inciso um. [v:0]"),
        _trecho(UFU, 78, 2, 3, "Caput do artigo setenta e oito, inciso dois. [v:0+1]"),
        _trecho(UFU, 78, 3, 3, "Caput do artigo setenta e oito, inciso três. [v:0+1+2]"),
        _trecho(UFU, 127, 1, 1, "Aprovação exige sessenta pontos e frequência. [v:0+1+2+3]"),
        _trecho(UFU, 5, 1, 1, "Disposição qualquer. [v:5]"),
    ], emb, MODELO)
    ingerir_documento(conn, UNIUBE, [
        _trecho(UNIUBE, 50, 1, 1, "Frequência mínima de setenta e cinco por cento. [v:0]"),
    ], emb, MODELO)
    return conn


def _ids(r):
    return [x["id"] for x in r]


def test_sem_agrupar_o_artigo_longo_ocupa_as_primeiras_posicoes(banco):
    # prova do problema: com a busca por trecho, o artigo 78 ocupa 3 das 3 primeiras vagas
    r = buscar_vetorial(banco, Q, 3, "ufu")
    assert _ids(r) == [A1, A2, A3]


def test_por_artigo_devolve_um_trecho_por_artigo_o_melhor(banco):
    r = buscar_vetorial_por_artigo(banco, Q, k=3, instituicao="ufu")
    assert _ids(r) == [A1, B1, C1]
    assert r[0]["distancia"] == pytest.approx(0.0, abs=1e-4)
    assert r[1]["distancia"] == pytest.approx(0.5, abs=1e-4)


def test_por_artigo_traz_os_ids_dos_trechos_irmaos(banco):
    r = {x["id"]: x for x in buscar_vetorial_por_artigo(banco, Q, k=3, instituicao="ufu")}
    assert r[A1]["ids_irmaos"] == [A1, A2, A3]
    assert r[B1]["ids_irmaos"] == [B1]


def test_por_artigo_respeita_k_e_o_filtro_de_instituicao(banco):
    assert _ids(buscar_vetorial_por_artigo(banco, Q, k=2, instituicao="ufu")) == [A1, B1]
    so_uniube = buscar_vetorial_por_artigo(banco, Q, k=5, instituicao="uniube")
    assert _ids(so_uniube) == [D1]
    sem_filtro = _ids(buscar_vetorial_por_artigo(banco, Q, k=5))
    assert D1 in sem_filtro and A1 in sem_filtro


def test_por_artigo_pode_devolver_menos_de_k_se_os_candidatos_acabarem(banco):
    # só 2 candidatos (A1 e A2, irmãos): sobra 1 artigo
    r = buscar_vetorial_por_artigo(banco, Q, k=3, instituicao="ufu", k_candidatos=2)
    assert _ids(r) == [A1]
    assert r[0]["ids_irmaos"] == [A1, A2]


def test_por_artigo_mantem_as_colunas_da_busca_vetorial(banco):
    x = buscar_vetorial_por_artigo(banco, Q, k=1, instituicao="ufu")[0]
    for coluna in ("id", "doc_id", "citacao", "texto", "pai_id", "instituicao", "distancia"):
        assert coluna in x
    assert "embedding" not in x and "tsv" not in x
