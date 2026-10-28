"""Reranking: reordena os candidatos da busca vetorial com um cross-encoder.

Motivo (medido, dev com filtro de instituição): em 12 das 31 perguntas o artigo certo não é o 1º
resultado, e em 11 delas está entre as 25 primeiras posições (q034 em 12º, q035 em 25º). O
embedding acerta o assunto e erra o artigo dentro do assunto; um cross-encoder lê pergunta e
trecho juntos e consegue pesar restrições finas. (Casos fora das 50 primeiras, como a q046,
não são recuperáveis por reranking.)

Contrato

  guia.reranking
    NOME_RERANKER = "bge-reranker-v2-m3"; RERANKER_HF = "BAAI/bge-reranker-v2-m3"
    criar_reranker(modelo, lote=8) -> reranker
        `modelo`: qualquer objeto com .predict(pares, batch_size=..., **kwargs) que devolve uma
        pontuação por par (array numpy ou lista), `pares` = [[pergunta, texto], ...].
        reranker(pergunta: str, textos: list[str]) -> list[float]
          - lista vazia -> [] sem chamar o modelo
          - um float do Python por texto, na mesma ordem; passa batch_size=lote ao modelo
          - ValueError se o modelo devolver número errado de pontuações ou valor não finito
    carregar_bge_reranker(dispositivo="cpu", max_length=1024) -> modelo (CrossEncoder)
        importa sentence_transformers só quando chamada (importar guia.reranking não pode puxar
        torch). Não é testada aqui: o sandbox não acessa o Hugging Face.

  guia.recuperacao.busca
    reordenar_por_score(candidatos, scores, k=None) -> list[dict]       (função pura)
        Ordena por score decrescente; empate mantém a ordem de entrada (estável). Cada dict é
        cópia do candidato mais "score_rerank". ValueError se len(scores) != len(candidatos).
        `k` corta no fim. Não altera a entrada.
    buscar_com_rerank(conn, vetor, pergunta, reranker, k=5, instituicao=None, k_candidatos=30)
        1. candidatos = buscar_vetorial(conn, vetor, k_candidatos, instituicao)
        2. se não houver candidatos, devolve [] sem chamar o reranker
        3. UMA chamada reranker(pergunta, [c["texto"] for c in candidatos]), na ordem vetorial
        4. devolve reordenar_por_score(...) com os k melhores; cada resultado mantém "distancia"
           (a vetorial) e ganha "score_rerank" e "rank_vetorial" (posição 1-based na busca vetorial)

Testes de banco usam schema temporário e são pulados sem o Docker (guia-db).
"""
import math
import re
import subprocess
import sys
import uuid

import numpy as np
import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.ingestao.carga import DIMENSAO, ingerir_documento
from guia.recuperacao.busca import buscar_com_rerank, reordenar_por_score
from guia.reranking import NOME_RERANKER, RERANKER_HF, criar_reranker

MODELO = "bge-m3"


# ---------- adaptador do modelo (sem banco) ----------

class ModeloFalso:
    def __init__(self, retorno=None, formato="numpy"):
        self.retorno = retorno
        self.formato = formato
        self.chamadas = []

    def predict(self, pares, **kwargs):
        self.chamadas.append((pares, kwargs))
        valores = self.retorno if self.retorno is not None else [0.1 * (i + 1) for i in range(len(pares))]
        return np.array(valores, dtype=np.float32) if self.formato == "numpy" else list(valores)


def test_constantes():
    assert NOME_RERANKER == "bge-reranker-v2-m3"
    assert RERANKER_HF == "BAAI/bge-reranker-v2-m3"


@pytest.mark.parametrize("formato", ["numpy", "lista"])
def test_devolve_floats_do_python_na_ordem_dos_textos(formato):
    r = criar_reranker(ModeloFalso([0.9, 0.1, 0.5], formato))("pergunta", ["a", "b", "c"])
    assert r == pytest.approx([0.9, 0.1, 0.5])
    assert all(type(x) is float for x in r)


def test_monta_os_pares_pergunta_texto_e_passa_o_lote():
    modelo = ModeloFalso()
    criar_reranker(modelo, lote=4)("qual o prazo?", ["texto um", "texto dois"])
    pares, kwargs = modelo.chamadas[0]
    assert [list(p) for p in pares] == [["qual o prazo?", "texto um"], ["qual o prazo?", "texto dois"]]
    assert kwargs["batch_size"] == 4


def test_lote_padrao_e_8():
    modelo = ModeloFalso()
    criar_reranker(modelo)("p", ["a"])
    assert modelo.chamadas[0][1]["batch_size"] == 8


def test_lista_vazia_nao_chama_o_modelo():
    modelo = ModeloFalso()
    assert criar_reranker(modelo)("p", []) == []
    assert modelo.chamadas == []


def test_numero_de_pontuacoes_errado_levanta_valueerror():
    with pytest.raises(ValueError):
        criar_reranker(ModeloFalso([0.5]))("p", ["a", "b"])


@pytest.mark.parametrize("ruim", [float("nan"), float("inf")])
def test_pontuacao_nao_finita_levanta_valueerror(ruim):
    with pytest.raises(ValueError):
        criar_reranker(ModeloFalso([0.5, ruim]))("p", ["a", "b"])


def test_importar_guia_reranking_nao_importa_torch():
    codigo = (
        "import sys, guia.reranking; "
        "sys.exit(1 if 'sentence_transformers' in sys.modules or 'torch' in sys.modules else 0)"
    )
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------- reordenar_por_score (sem banco) ----------

def _c(id_, **extra):
    return {"id": id_, **extra}


def test_reordena_por_score_decrescente_e_anota_o_score():
    r = reordenar_por_score([_c("a"), _c("b"), _c("c")], [0.2, 0.9, 0.5])
    assert [x["id"] for x in r] == ["b", "c", "a"]
    assert [x["score_rerank"] for x in r] == pytest.approx([0.9, 0.5, 0.2])


def test_empate_mantem_a_ordem_de_entrada():
    r = reordenar_por_score([_c("a"), _c("b"), _c("c")], [0.5, 0.5, 0.5])
    assert [x["id"] for x in r] == ["a", "b", "c"]


def test_k_corta_no_fim_e_nao_altera_a_entrada():
    entrada = [_c("a"), _c("b"), _c("c")]
    r = reordenar_por_score(entrada, [0.1, 0.3, 0.2], k=2)
    assert [x["id"] for x in r] == ["b", "c"]
    assert entrada == [_c("a"), _c("b"), _c("c")]


def test_tamanhos_diferentes_levantam_valueerror():
    with pytest.raises(ValueError):
        reordenar_por_score([_c("a"), _c("b")], [0.1])


def test_lista_vazia():
    assert reordenar_por_score([], []) == []


# ---------- buscar_com_rerank (banco) ----------

def _vetor(*indices):
    v = np.zeros(DIMENSAO)
    for i in indices:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


class EmbedderPorMarcador:
    def __call__(self, textos):
        return [_vetor(*[int(x) for x in re.search(r"\[v:([\d+]+)\]", t).group(1).split("+")])
                for t in textos]


class RerankerFalso:
    """A nota sai do marcador [s:0.9] no texto; registra as chamadas."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, pergunta, textos):
        self.chamadas.append((pergunta, list(textos)))
        return [float(re.search(r"\[s:([\d.]+)\]", t).group(1)) for t in textos]


def _doc(doc_id, instituicao):
    return {"id": doc_id, "instituicao": instituicao, "titulo": f"Doc {doc_id}",
            "url": f"https://exemplo.edu.br/{doc_id}", "tipo": "pdf",
            "data_ref": "2024-04-18", "prioridade": 1}


def _trecho(doc, n, texto):
    return {"id": f"{doc['id']}/art-{n}#1", "doc_id": doc["id"], "local_id": f"art-{n}#1",
            "tipo_doc": "resolucao", "instituicao": doc["instituicao"], "titulo_doc": doc["titulo"],
            "url": doc["url"], "data_ref": doc["data_ref"], "prioridade": doc["prioridade"],
            "paginas": [1], "localizacao": {}, "citacao": f"Art. {n}", "texto": texto,
            "pai_id": f"{doc['id']}/art-{n}", "parte": 1, "total_partes": 1,
            "hash_texto": f"h-{doc['id']}-{n}", "metadados": {}}


UFU, UNIUBE = _doc("d-ufu", "ufu"), _doc("d-uniube", "uniube")
T1, T2, T3, T4 = "d-ufu/art-1#1", "d-ufu/art-2#1", "d-ufu/art-3#1", "d-ufu/art-4#1"
D1 = "d-uniube/art-9#1"
Q = _vetor(0)
PERGUNTA = "posso trancar uma disciplina?"


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
    # ordem vetorial ao e0: T1 (0) < T2 (0,29) < T3 (0,42) < T4 (1,0); D1 (UNIUBE) 0
    ingerir_documento(conn, UFU, [
        _trecho(UFU, 1, "Disposições gerais. [v:0] [s:0.10]"),
        _trecho(UFU, 2, "Trancamento parcial exige duas disciplinas. [v:0+1] [s:0.90]"),
        _trecho(UFU, 3, "Trancamento geral por dois semestres. [v:0+1+2] [s:0.50]"),
        _trecho(UFU, 4, "Assunto sem relação. [v:5] [s:0.20]"),
    ], emb, MODELO)
    ingerir_documento(conn, UNIUBE, [
        _trecho(UNIUBE, 9, "Interrupção de estudos na UNIUBE. [v:0] [s:0.99]"),
    ], emb, MODELO)
    return conn


def _ids(r):
    return [x["id"] for x in r]


def test_reordena_os_candidatos_vetoriais_pela_nota_do_reranker(banco):
    r = buscar_com_rerank(banco, Q, PERGUNTA, RerankerFalso(), k=3, instituicao="ufu")
    assert _ids(r) == [T2, T3, T4]


def test_resultado_traz_distancia_vetorial_score_e_posicao_original(banco):
    r = {x["id"]: x for x in buscar_com_rerank(banco, Q, PERGUNTA, RerankerFalso(), k=4, instituicao="ufu")}
    assert r[T2]["score_rerank"] == pytest.approx(0.90)
    assert r[T2]["rank_vetorial"] == 2 and r[T1]["rank_vetorial"] == 1
    assert r[T2]["distancia"] == pytest.approx(1 - 1 / math.sqrt(2), abs=1e-4)


def test_chama_o_reranker_uma_vez_com_pergunta_e_textos_na_ordem_vetorial(banco):
    rr = RerankerFalso()
    buscar_com_rerank(banco, Q, PERGUNTA, rr, k=2, instituicao="ufu")
    assert len(rr.chamadas) == 1
    pergunta, textos = rr.chamadas[0]
    assert pergunta == PERGUNTA
    assert [t.split(" [v:")[0] for t in textos] == [
        "Disposições gerais.", "Trancamento parcial exige duas disciplinas.",
        "Trancamento geral por dois semestres.", "Assunto sem relação."]


def test_k_candidatos_limita_o_que_o_reranker_enxerga(banco):
    rr = RerankerFalso()
    r = buscar_com_rerank(banco, Q, PERGUNTA, rr, k=5, instituicao="ufu", k_candidatos=2)
    assert len(rr.chamadas[0][1]) == 2
    assert _ids(r) == [T2, T1]  # T3 e T4 nunca foram vistos


def test_filtro_de_instituicao_vale_antes_do_reranker(banco):
    rr = RerankerFalso()
    r = buscar_com_rerank(banco, Q, PERGUNTA, rr, k=10, instituicao="ufu")
    assert D1 not in _ids(r)
    assert not any("UNIUBE" in t for t in rr.chamadas[0][1])
    sem_filtro = buscar_com_rerank(banco, Q, PERGUNTA, RerankerFalso(), k=10)
    assert _ids(sem_filtro)[0] == D1  # nota 0,99


def test_respeita_k(banco):
    assert len(buscar_com_rerank(banco, Q, PERGUNTA, RerankerFalso(), k=2, instituicao="ufu")) == 2


def test_sem_candidatos_devolve_vazio_sem_chamar_o_reranker(banco):
    rr = RerankerFalso()
    assert buscar_com_rerank(banco, Q, PERGUNTA, rr, k=3, instituicao="inexistente") == []
    assert rr.chamadas == []
