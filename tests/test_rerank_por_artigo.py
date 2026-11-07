import re
import uuid

import numpy as np
import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.ingestao.carga import DIMENSAO, ingerir_documento
from guia.pipeline import perguntar
from guia.recuperacao.busca import buscar_com_rerank_por_artigo, buscar_vetorial

MODELO = "bge-m3"


def _vetor(*indices):
    v = np.zeros(DIMENSAO)
    for i in indices:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


class Embedder:
    """Texto com [v:0+1] vira esse vetor; qualquer outro texto (a pergunta) vira e0."""

    def __call__(self, textos):
        saida = []
        for t in textos:
            m = re.search(r"\[v:([\d+]+)\]", t)
            saida.append(_vetor(*[int(x) for x in m.group(1).split("+")]) if m else _vetor(0))
        return saida


class Reranker:
    """Score = primeiro [s:x] do texto; sem marcador, falha (texto errado enviado)."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, pergunta, textos):
        self.chamadas.append((pergunta, list(textos)))
        return [float(re.search(r"\[s:([\d.]+)\]", t).group(1)) for t in textos]


class LLM:
    def __init__(self, texto="Vale [1] e [2]."):
        self.texto = texto

    def __call__(self, system, user):
        return {"texto": self.texto, "tokens_entrada": 300, "tokens_saida": 40}


def _doc(doc_id="d-normas", tipo="pdf"):
    return {"id": doc_id, "instituicao": "ufu", "titulo": "Normas Gerais",
            "url": "https://exemplo.edu.br/normas", "tipo": tipo, "data_ref": "2024",
            "prioridade": 1}


def _trecho(doc, local, pai, parte, total, citacao, paginas, texto, tipo_doc="resolucao"):
    return {"id": f"{doc['id']}/{local}", "doc_id": doc["id"], "local_id": local,
            "tipo_doc": tipo_doc, "instituicao": "ufu", "titulo_doc": doc["titulo"],
            "url": doc["url"], "data_ref": "2024", "prioridade": 1, "paginas": paginas,
            "localizacao": {}, "citacao": citacao, "texto": texto,
            "pai_id": f"{doc['id']}/{pai}", "parte": parte, "total_partes": total,
            "hash_texto": f"h-{local}", "metadados": {}}


CAPUT = "Art. 78. Caput do artigo setenta e oito."


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
    d = _doc()
    # Ordem vetorial (pergunta = e0): 78#2 (1) < 127 (2) < 78#1 (3) < 78#3 (4) < 50 (5).
    # O Art. 78 tem 3 trechos irmaos com score alto cada um; o Art. 127 vem logo abaixo.
    ingerir_documento(conn, d, [
        _trecho(d, "art-78#1", "art-78", 1, 3, "Art. 78, p. 22", [22],
                CAPUT + "\nI - primeiro inciso. [v:0+1+2] [s:0.70]"),
        _trecho(d, "art-78#2", "art-78", 2, 3, "Art. 78, p. 22-23", [22, 23],
                CAPUT + "\nII - segundo inciso. [v:0] [s:0.65]"),
        _trecho(d, "art-78#3", "art-78", 3, 3, "Art. 78, p. 23", [23],
                CAPUT + "\nIII - terceiro inciso. [v:0+1+2+3] [s:0.60]"),
        _trecho(d, "art-127#1", "art-127", 1, 1, "Art. 127, p. 30", [30],
                "Art. 127. Aprovação exige sessenta pontos. [v:0+1] [s:0.55]"),
        _trecho(d, "art-50#1", "art-50", 1, 1, "Art. 50, p. 15", [15],
                "Art. 50. Vagas ociosas. [v:0+1+2+3+4] [s:0.40]"),
    ], Embedder(), MODELO)
    return conn


def _buscar(conn, rr=None, **kw):
    rr = rr or Reranker()
    args = dict(k=10, instituicao="ufu", k_candidatos=30)
    args.update(kw)
    return buscar_com_rerank_por_artigo(conn, _vetor(0), "Qual a nota mínima?", rr, **args), rr


def test_reranker_recebe_um_texto_por_artigo_na_ordem_da_primeira_aparicao(banco):
    _, rr = _buscar(banco)
    assert len(rr.chamadas) == 1
    pergunta, textos = rr.chamadas[0]
    assert pergunta == "Qual a nota mínima?"
    assert len(textos) == 3
    assert textos[0].startswith("Art. 78.") and textos[1].startswith("Art. 127.")
    assert textos[2].startswith("Art. 50.")


def test_texto_da_unidade_e_o_artigo_inteiro_sem_repetir_o_caput(banco):
    _, rr = _buscar(banco)
    art78 = rr.chamadas[0][1][0]
    for trecho in ("I - primeiro inciso", "II - segundo inciso", "III - terceiro inciso"):
        assert trecho in art78
    assert art78.count("Caput do artigo setenta e oito") == 1
    assert art78.index("I - primeiro") < art78.index("II - segundo") < art78.index("III - terceiro")


def test_irmaos_fora_do_pool_entram_no_texto_do_artigo(banco):
    # pool de 3: 78#2, 127, 78#1 -> o inciso III (78#3) nao esta no pool, mas esta no artigo
    _, rr = _buscar(banco, k_candidatos=3)
    textos = rr.chamadas[0][1]
    assert len(textos) == 2
    assert "III - terceiro inciso" in textos[0]


def test_devolve_o_representante_com_score_do_artigo_e_ordem_do_reranker(banco):
    res, _ = _buscar(banco)
    assert [r["id"] for r in res] == ["d-normas/art-78#2", "d-normas/art-127#1",
                                      "d-normas/art-50#1"]
    # score do ARTIGO 78 = primeiro marcador do artigo inteiro (parte 1: 0.70), nao o do
    # representante (0.65)
    assert [r["score_rerank"] for r in res] == pytest.approx([0.70, 0.55, 0.40])
    assert [r["rank_vetorial"] for r in res] == [1, 2, 5]
    assert res[0]["texto"].startswith(CAPUT) and "II - segundo inciso" in res[0]["texto"]
    assert "I - primeiro inciso" not in res[0]["texto"]  # "texto" continua o do representante


def test_distancia_original_e_preservada(banco):
    res, _ = _buscar(banco)
    esperado = {r["id"]: r["distancia"] for r in buscar_vetorial(banco, _vetor(0), k=30,
                                                                 instituicao="ufu")}
    for r in res:
        assert r["distancia"] == pytest.approx(esperado[r["id"]])


def test_reordena_quando_o_artigo_menos_proximo_ganha(conn):
    d = _doc()
    ingerir_documento(conn, d, [
        _trecho(d, "art-1#1", "art-1", 1, 1, "Art. 1, p. 1", [1], "Art. 1. A. [v:0] [s:0.20]"),
        _trecho(d, "art-2#1", "art-2", 1, 1, "Art. 2, p. 2", [2], "Art. 2. B. [v:0+1] [s:0.90]"),
    ], Embedder(), MODELO)
    res, _ = _buscar(conn)
    assert [r["id"] for r in res] == ["d-normas/art-2#1", "d-normas/art-1#1"]
    assert [r["rank_vetorial"] for r in res] == [2, 1]


def test_k_corta_em_unidades_nao_em_trechos(banco):
    res, _ = _buscar(banco, k=2)
    assert [r["id"] for r in res] == ["d-normas/art-78#2", "d-normas/art-127#1"]


def test_empate_mantem_a_ordem_da_primeira_aparicao(conn):
    d = _doc()
    ingerir_documento(conn, d, [
        _trecho(d, "art-1#1", "art-1", 1, 1, "Art. 1, p. 1", [1], "Art. 1. A. [v:0] [s:0.50]"),
        _trecho(d, "art-2#1", "art-2", 1, 1, "Art. 2, p. 2", [2], "Art. 2. B. [v:0+1] [s:0.50]"),
    ], Embedder(), MODELO)
    res, _ = _buscar(conn)
    assert [r["id"] for r in res] == ["d-normas/art-1#1", "d-normas/art-2#1"]


def test_procedimento_nao_agrupa_passos_que_compartilham_pai_id(conn):
    d = _doc("d-proc")
    ingerir_documento(conn, d, [
        _trecho(d, "passo-1", "proc", 1, 2, "Passo 1, p. 1", [1],
                "Passo 1: abrir o processo. [v:0] [s:0.30]", tipo_doc="procedimento"),
        _trecho(d, "passo-2", "proc", 2, 2, "Passo 2, p. 1", [1],
                "Passo 2: anexar o plano. [v:0+1] [s:0.80]", tipo_doc="procedimento"),
    ], Embedder(), MODELO)
    res, rr = _buscar(conn)
    assert rr.chamadas[0][1] == ["Passo 1: abrir o processo. [v:0] [s:0.30]",
                                 "Passo 2: anexar o plano. [v:0+1] [s:0.80]"]
    assert [r["id"] for r in res] == ["d-proc/passo-2", "d-proc/passo-1"]
    assert [r["score_rerank"] for r in res] == pytest.approx([0.80, 0.30])


def test_pagina_continua_sendo_uma_unidade_por_trecho(conn):
    d = _doc("d-pag")
    ingerir_documento(conn, d, [
        _trecho(d, "p#1", "p", 1, 2, "Página, p. 1", [1], "Texto A. [v:0] [s:0.10]",
                tipo_doc="pagina"),
        _trecho(d, "p#2", "p", 2, 2, "Página, p. 1", [1], "Texto B. [v:0+1] [s:0.20]",
                tipo_doc="pagina"),
    ], Embedder(), MODELO)
    res, rr = _buscar(conn)
    assert len(rr.chamadas[0][1]) == 2 and len(res) == 2


def test_misto_resolucao_agrupa_e_procedimento_nao(conn):
    d1, d2 = _doc("d-res"), _doc("d-proc")
    ingerir_documento(conn, d1, [
        _trecho(d1, "art-1#1", "art-1", 1, 2, "Art. 1, p. 1", [1], "Art. 1. X.\nI. [v:0] [s:0.50]"),
        _trecho(d1, "art-1#2", "art-1", 2, 2, "Art. 1, p. 1", [1], "Art. 1. X.\nII. [v:0+1] [s:0.40]"),
    ], Embedder(), MODELO)
    ingerir_documento(conn, d2, [
        _trecho(d2, "p1", "proc", 1, 2, "Passo 1, p. 1", [1], "Passo 1. [v:0+1+2] [s:0.30]",
                tipo_doc="procedimento"),
        _trecho(d2, "p2", "proc", 2, 2, "Passo 2, p. 1", [1], "Passo 2. [v:0+1+2+3] [s:0.20]",
                tipo_doc="procedimento"),
    ], Embedder(), MODELO)
    _, rr = _buscar(conn)
    assert len(rr.chamadas[0][1]) == 3  # artigo (2 trechos) + 2 passos


def test_filtro_de_instituicao_vale_para_o_pool(banco):
    res, rr = _buscar(banco, instituicao="inexistente")
    assert res == [] and rr.chamadas == []


def test_sem_candidatos_nao_chama_o_reranker(conn):
    res, rr = _buscar(conn)
    assert res == [] and rr.chamadas == []


# ---- pipeline -------------------------------------------------------------------------------

def test_pipeline_com_agrupamento_traz_o_artigo_127_que_o_amontoado_escondia(banco):
    llm = LLM("Vale [1] e [2].")
    r = perguntar(banco, "Qual a nota mínima?", Embedder(), Reranker(), llm, instituicao="ufu",
                  k_recuperacao=2, max_artigos=2, agrupar_antes_do_rerank=True)
    assert [b["pai_id"] for b in r["blocos"]] == ["d-normas/art-78", "d-normas/art-127"]
    assert r["recuperados_ids"] == ["d-normas/art-78#2", "d-normas/art-127#1"]
    assert r["recusou"] is False


def test_pipeline_padrao_continua_por_trecho_e_perde_o_127(banco):
    # comportamento anterior preservado: com k=2 os dois primeiros trechos sao do Art. 78
    r = perguntar(banco, "Qual a nota mínima?", Embedder(), Reranker(), LLM("Vale [1]."),
                  instituicao="ufu", k_recuperacao=2, max_artigos=2)
    assert [b["pai_id"] for b in r["blocos"]] == ["d-normas/art-78"]


def test_pipeline_chama_o_reranker_uma_vez_com_um_texto_por_artigo(banco):
    rr = Reranker()
    perguntar(banco, "pergunta", Embedder(), rr, LLM("Vale [1]."), instituicao="ufu",
              agrupar_antes_do_rerank=True)
    assert len(rr.chamadas) == 1 and len(rr.chamadas[0][1]) == 3


def test_pipeline_respeita_k_candidatos_com_agrupamento(banco):
    rr = Reranker()
    perguntar(banco, "pergunta", Embedder(), rr, LLM("Vale [1]."), instituicao="ufu",
              k_candidatos=2, agrupar_antes_do_rerank=True)
    assert len(rr.chamadas[0][1]) == 2  # pool de 2 trechos: 78#2 e 127


def test_pipeline_sem_candidatos_recusa_sem_chamar_reranker(banco):
    rr = Reranker()
    r = perguntar(banco, "pergunta", Embedder(), rr, LLM(), instituicao="inexistente",
                  agrupar_antes_do_rerank=True)
    assert r["recusou"] is True and r["motivo_recusa"] == "sem_contexto"
    assert rr.chamadas == []
