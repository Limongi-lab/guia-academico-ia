"""Busca textual (tsv), fusão RRF e busca híbrida.

Contrato (guia.recuperacao.busca, junto de buscar_vetorial):

  buscar_textual(conn, consulta, k=5, instituicao=None, vetor=None) -> list[dict]
      Busca por palavras no tsv (português, com radical: "trancamentos" acha "trancamento").
      A consulta é uma PERGUNTA em linguagem natural, então os termos são combinados com OU
      (basta um termo casar; quem casa mais e com termos mais raros fica no topo), e não com E.
      Mesmas colunas de buscar_vetorial (sem embedding e sem tsv) mais:
        pontuacao  float (ts_rank), ordem decrescente (empate: id crescente)
        distancia  float (cosseno contra `vetor`) se `vetor` for passado, senão None
      Só devolve quem casou: consulta sem nenhum termo útil (só palavras vazias como
      "qual o de") ou sem nenhum casamento devolve []. Filtro opcional por instituicao.

  fundir_rrf(listas, k=60, top=None) -> list[dict]      (função pura)
      listas: dict nome -> lista de dicts com "id", cada lista do melhor ao pior.
      Reciprocal Rank Fusion: rrf(id) = soma, sobre as listas em que aparece, de 1/(k + posição),
      posição 1-based. Devolve um dict por id (cópia do primeiro aparecimento, na ordem dos
      nomes e das posições) com "rrf" (float) e "rank_<nome>" para CADA lista (posição ou None).
      Ordem: rrf decrescente; empate: quem apareceu primeiro. `top` limita o tamanho.
      ValueError se k <= 0. Não altera as listas recebidas.

  buscar_hibrida(conn, vetor, consulta, k=5, instituicao=None, k_candidatos=50, rrf_k=60)
      -> list[dict]
      Pega k_candidatos de buscar_vetorial e k_candidatos de buscar_textual (mesmo filtro de
      instituição nas duas), funde com fundir_rrf(nomes "vetorial" e "textual") e devolve os
      k melhores. Todo resultado tem "distancia" (float): quem veio só do textual também recebe
      a distância ao `vetor`. Tem "rrf", "rank_vetorial" e "rank_textual".

Testes de banco usam schema temporário e são pulados sem o Docker (guia-db).
"""
import re
import uuid

import numpy as np
import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.ingestao.carga import DIMENSAO, ingerir_documento
from guia.recuperacao.busca import buscar_hibrida, buscar_textual, buscar_vetorial, fundir_rrf

MODELO = "bge-m3"


# ---------- RRF (sem banco) ----------

def _ids(resultado):
    return [r["id"] for r in resultado]


def test_rrf_soma_os_reciprocos_e_ordena():
    listas = {
        "a": [{"id": "x"}, {"id": "y"}, {"id": "z"}],
        "b": [{"id": "z"}, {"id": "x"}],
    }
    r = fundir_rrf(listas, k=60)
    assert _ids(r) == ["x", "z", "y"]
    por_id = {i["id"]: i for i in r}
    assert por_id["x"]["rrf"] == pytest.approx(1 / 61 + 1 / 62)
    assert por_id["z"]["rrf"] == pytest.approx(1 / 63 + 1 / 61)
    assert por_id["y"]["rrf"] == pytest.approx(1 / 62)
    assert (por_id["x"]["rank_a"], por_id["x"]["rank_b"]) == (1, 2)
    assert (por_id["y"]["rank_a"], por_id["y"]["rank_b"]) == (2, None)
    assert (por_id["z"]["rank_a"], por_id["z"]["rank_b"]) == (3, 1)


def test_rrf_usa_o_k_informado():
    r = fundir_rrf({"a": [{"id": "x"}], "b": [{"id": "x"}]}, k=1)
    assert r[0]["rrf"] == pytest.approx(1 / 2 + 1 / 2)


def test_rrf_com_uma_lista_preserva_a_ordem():
    lista = [{"id": "c"}, {"id": "a"}, {"id": "b"}]
    r = fundir_rrf({"unica": lista})
    assert _ids(r) == ["c", "a", "b"]
    assert [i["rrf"] for i in r] == pytest.approx([1 / 61, 1 / 62, 1 / 63])


def test_rrf_empate_vence_quem_apareceu_primeiro():
    r = fundir_rrf({"a": [{"id": "p"}], "b": [{"id": "q"}]})
    assert _ids(r) == ["p", "q"]
    assert r[0]["rrf"] == pytest.approx(r[1]["rrf"])


def test_rrf_top_e_listas_vazias():
    listas = {"a": [{"id": str(i)} for i in range(10)]}
    assert len(fundir_rrf(listas, top=3)) == 3
    assert len(fundir_rrf(listas)) == 10
    assert fundir_rrf({"a": [], "b": []}) == []
    assert _ids(fundir_rrf({"a": [], "b": [{"id": "x"}]})) == ["x"]


def test_rrf_mantem_os_campos_do_primeiro_aparecimento_e_nao_altera_a_entrada():
    a = [{"id": "x", "texto": "da lista a"}]
    b = [{"id": "x", "texto": "da lista b", "extra": 1}]
    r = fundir_rrf({"a": a, "b": b})
    assert r[0]["texto"] == "da lista a"
    assert "rrf" not in a[0] and "rank_a" not in a[0]


@pytest.mark.parametrize("k", [0, -5])
def test_rrf_k_invalido(k):
    with pytest.raises(ValueError):
        fundir_rrf({"a": [{"id": "x"}]}, k=k)


# ---------- apoio de banco ----------

def _um_hot(*indices):
    v = np.zeros(DIMENSAO)
    for i in indices:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


class EmbedderPorMarcador:
    """O vetor do trecho sai do marcador no texto: [v:0] -> e0, [v:0+5] -> (e0+e5) normalizado."""

    def __call__(self, textos):
        saida = []
        for t in textos:
            m = re.search(r"\[v:(\d+)(?:\+(\d+))?\]", t)
            idx = [int(g) for g in m.groups() if g is not None]
            saida.append(_um_hot(*idx))
        return saida


def _doc(doc_id, instituicao):
    return {"id": doc_id, "instituicao": instituicao, "titulo": f"Doc {doc_id}",
            "url": f"https://exemplo.edu.br/{doc_id}", "tipo": "pdf",
            "data_ref": "2024-04-18", "prioridade": 1}


def _trecho(doc, local, citacao, texto):
    return {"id": f"{doc['id']}/{local}#1", "doc_id": doc["id"], "local_id": f"{local}#1",
            "tipo_doc": "resolucao", "instituicao": doc["instituicao"],
            "titulo_doc": doc["titulo"], "url": doc["url"], "data_ref": doc["data_ref"],
            "prioridade": doc["prioridade"], "paginas": [1], "localizacao": {},
            "citacao": citacao, "texto": texto, "pai_id": f"{doc['id']}/{local}",
            "parte": 1, "total_partes": 1, "hash_texto": f"h-{doc['id']}-{local}",
            "metadados": {}}


UFU, UNIUBE = _doc("d-ufu", "ufu"), _doc("d-uniube", "uniube")
T1 = "d-ufu/t1#1"   # vetor e0, sem os termos da consulta
T2 = "d-ufu/t2#1"   # vetor e5, casamento textual forte (3x trancamento + prazo)
T3 = "d-ufu/t3#1"   # vetor (e0+e5), casamento textual fraco (prazo + trancamento, 1x)
T4 = "d-uniube/t4#1"  # outra instituição: vetor e0 e casamento textual
T5 = "d-ufu/t5#1"   # ruído
T6 = "d-ufu/t6#1"   # ruído
Q_TEXTO = "prazo trancamento"
Q_VETOR = _um_hot(0)


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
    ingerir_documento(conn, UFU, [
        _trecho(UFU, "t1", "Art. 1º", "Disposições gerais sobre matrícula e calendário. [v:0]"),
        _trecho(UFU, "t2", "Art. 2º",
                "O trancamento geral segue o prazo do calendário; o trancamento parcial "
                "e o trancamento especial têm regras próprias. [v:5]"),
        _trecho(UFU, "t3", "Art. 3º",
                "O prazo de entrega é definido pela coordenação, inclusive o trancamento. [v:0+5]"),
        _trecho(UFU, "t5", "Art. 5º", "Frequência mínima de setenta e cinco por cento. [v:9]"),
        _trecho(UFU, "t6", "Art. 6º", "Avaliação final e notas dos estudantes. [v:9]"),
    ], emb, MODELO)
    ingerir_documento(conn, UNIUBE, [
        _trecho(UNIUBE, "t4", "Art. 4º", "O trancamento de matrícula tem prazo de dois anos. [v:0]"),
    ], emb, MODELO)
    return conn


# ---------- buscar_textual ----------

def test_textual_acha_e_ordena_por_pontuacao(banco):
    r = buscar_textual(banco, Q_TEXTO, k=5, instituicao="ufu")
    assert _ids(r) == [T2, T3]
    assert r[0]["pontuacao"] > r[1]["pontuacao"] > 0


def test_textual_usa_radical_do_portugues(banco):
    r = buscar_textual(banco, "trancamentos", k=5, instituicao="ufu")
    assert T2 in _ids(r)


def test_textual_combina_termos_com_ou_para_perguntas_longas(banco):
    pergunta = "qual é o prazo para o trancamento de matrícula geral no semestre letivo?"
    r = buscar_textual(banco, pergunta, k=5, instituicao="ufu")
    assert r and r[0]["id"] == T2  # nenhum trecho tem todos os termos; com E voltaria vazio


def test_textual_respeita_k(banco):
    assert len(buscar_textual(banco, Q_TEXTO, k=1, instituicao="ufu")) == 1


def test_textual_filtra_por_instituicao(banco):
    assert _ids(buscar_textual(banco, Q_TEXTO, k=10, instituicao="uniube")) == [T4]
    sem_filtro = _ids(buscar_textual(banco, Q_TEXTO, k=10))
    assert T4 in sem_filtro and T2 in sem_filtro


@pytest.mark.parametrize("consulta", ["xyzzy plugh", "qual o de", ""])
def test_textual_sem_casamento_ou_so_palavras_vazias_devolve_lista_vazia(banco, consulta):
    assert buscar_textual(banco, consulta, k=5) == []


def test_textual_colunas_e_distancia(banco):
    sem = buscar_textual(banco, Q_TEXTO, k=5, instituicao="ufu")[0]
    for coluna in ("id", "doc_id", "citacao", "texto", "pai_id", "instituicao", "pontuacao"):
        assert coluna in sem
    assert "embedding" not in sem and "tsv" not in sem
    assert sem["distancia"] is None
    com = {r["id"]: r for r in buscar_textual(banco, Q_TEXTO, k=5, instituicao="ufu", vetor=Q_VETOR)}
    assert com[T3]["distancia"] == pytest.approx(1 - 1 / np.sqrt(2), abs=1e-4)
    assert com[T2]["distancia"] == pytest.approx(1.0, abs=1e-4)
    assert all(isinstance(r["distancia"], float) for r in com.values())


# ---------- buscar_hibrida ----------

def test_hibrida_junta_o_que_so_um_dos_buscadores_acha(banco):
    r = buscar_hibrida(banco, Q_VETOR, Q_TEXTO, k=3, instituicao="ufu")
    # T2 e T3 aparecem nas duas listas e ganham de T1 (só vetorial) e dos ruídos
    assert set(_ids(r)[:2]) == {T2, T3}
    assert _ids(r)[2] == T1
    t1 = r[2]
    assert t1["rank_vetorial"] == 1 and t1["rank_textual"] is None


def test_hibrida_traz_trecho_so_textual_com_distancia(banco):
    # só 2 candidatos vetoriais (T1 e T3): T2 só entra pelo textual, mas ainda traz distância
    r = buscar_hibrida(banco, Q_VETOR, Q_TEXTO, k=5, instituicao="ufu", k_candidatos=2)
    por_id = {x["id"]: x for x in r}
    assert _ids(r)[0] == T3
    assert por_id[T2]["rank_vetorial"] is None and por_id[T2]["rank_textual"] == 1
    assert por_id[T2]["distancia"] == pytest.approx(1.0, abs=1e-4)
    assert set(por_id) == {T1, T2, T3}


def test_hibrida_filtra_instituicao_nos_dois_buscadores(banco):
    r = buscar_hibrida(banco, Q_VETOR, Q_TEXTO, k=10, instituicao="ufu")
    assert T4 not in _ids(r)
    assert all(x["instituicao"] == "ufu" for x in r)
    sem_filtro = buscar_hibrida(banco, Q_VETOR, Q_TEXTO, k=10)
    assert T4 in _ids(sem_filtro)


def test_hibrida_respeita_k_e_ordena_por_rrf(banco):
    r = buscar_hibrida(banco, Q_VETOR, Q_TEXTO, k=2)
    assert len(r) == 2
    rrfs = [x["rrf"] for x in buscar_hibrida(banco, Q_VETOR, Q_TEXTO, k=10)]
    assert rrfs == sorted(rrfs, reverse=True)


def test_hibrida_com_consulta_sem_termos_uteis_vira_busca_vetorial(banco):
    r = buscar_hibrida(banco, Q_VETOR, "qual o de", k=2, instituicao="ufu")
    assert _ids(r) == [T1, T3]
    assert all(x["rank_textual"] is None for x in r)
    vetorial = buscar_vetorial(banco, Q_VETOR, 2, "ufu")
    assert [x["id"] for x in vetorial] == _ids(r)


def test_hibrida_todo_resultado_tem_distancia_float(banco):
    for x in buscar_hibrida(banco, Q_VETOR, Q_TEXTO, k=10):
        assert isinstance(x["distancia"], float)
