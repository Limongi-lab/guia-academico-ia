"""Pipeline de ponta a ponta: pergunta -> embedding -> busca vetorial (+filtro) -> reranker
-> contexto por artigo -> LLM -> resposta com citação verificada.

Decisão registrada: a configuração de recuperação é a que ganhou na avaliação (vetorial +
filtro de instituição vindo do perfil do usuário + reranker com pool de 30). Busca textual,
híbrida e agrupamento por artigo ficam fora do caminho principal (medidos e descartados).

Contrato (guia.pipeline)
  perguntar(conn, pergunta, embedder, reranker, llm, instituicao=None, k_candidatos=30,
            k_recuperacao=10, max_artigos=3, relogio=time.perf_counter) -> dict
    1. vetor = embedder([pergunta])[0]                              (uma chamada)
    2. recuperados = buscar_com_rerank(conn, vetor, pergunta, reranker, k=k_recuperacao,
                                       instituicao=instituicao, k_candidatos=k_candidatos)
    3. blocos = montar_contexto(conn, recuperados, max_artigos)
    4. resposta = responder(pergunta, blocos, llm, relogio)
    Devolve o dicionário de guia.geracao.responder mais:
      recuperacao_s  (tempo dos passos 1 a 3, medido com `relogio` chamado 2 vezes, antes e depois)
      total_s        (= recuperacao_s + latencia_s)
      blocos         (a lista do passo 3)
      recuperados_ids (ids dos trechos devolvidos no passo 2, na ordem)
    Sem candidatos (p.ex. instituição inexistente): recusa "sem_contexto"; o reranker e o LLM
    não são chamados.
    `relogio` é chamado, em ordem: pipeline (início), pipeline (fim da recuperação), e depois
    duas vezes dentro de responder.

Testes de banco usam schema temporário e são pulados sem o Docker (guia-db).
"""
import re
import uuid

import numpy as np
import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.geracao import MENSAGEM_RECUSA
from guia.ingestao.carga import DIMENSAO, ingerir_documento
from guia.pipeline import perguntar

MODELO = "bge-m3"


def _vetor(*indices):
    v = np.zeros(DIMENSAO)
    for i in indices:
        v[i] = 1.0
    return (v / np.linalg.norm(v)).tolist()


class Embedder:
    """Texto com [v:0+1] vira esse vetor; qualquer outro texto (a pergunta) vira e0."""

    def __init__(self):
        self.chamadas = []

    def __call__(self, textos):
        self.chamadas.append(list(textos))
        saida = []
        for t in textos:
            m = re.search(r"\[v:([\d+]+)\]", t)
            saida.append(_vetor(*[int(x) for x in m.group(1).split("+")]) if m else _vetor(0))
        return saida


class Reranker:
    def __init__(self):
        self.chamadas = []

    def __call__(self, pergunta, textos):
        self.chamadas.append((pergunta, list(textos)))
        return [float(re.search(r"\[s:([\d.]+)\]", t).group(1)) for t in textos]


class LLM:
    def __init__(self, texto="Vale [1] e [2]."):
        self.texto = texto
        self.chamadas = []

    def __call__(self, system, user):
        self.chamadas.append((system, user))
        return {"texto": self.texto, "tokens_entrada": 300, "tokens_saida": 40}


class Relogio:
    def __init__(self, *marcas):
        self.marcas = list(marcas)

    def __call__(self):
        return self.marcas.pop(0)


def _doc():
    return {"id": "d-normas", "instituicao": "ufu", "titulo": "Normas Gerais",
            "url": "https://exemplo.edu.br/normas", "tipo": "pdf", "data_ref": "2024", "prioridade": 1}


def _trecho(doc, local, pai, parte, total, citacao, paginas, texto):
    return {"id": f"{doc['id']}/{local}", "doc_id": doc["id"], "local_id": local,
            "tipo_doc": "resolucao", "instituicao": "ufu", "titulo_doc": doc["titulo"],
            "url": doc["url"], "data_ref": "2024", "prioridade": 1, "paginas": paginas,
            "localizacao": {}, "citacao": citacao, "texto": texto, "pai_id": f"{doc['id']}/{pai}",
            "parte": parte, "total_partes": total, "hash_texto": f"h-{local}", "metadados": {}}


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
    # vetor ao e0: 78#1 (0) < 78#2 < 78#3 < 127 ; notas do reranker: 127 (0,9) > 78#2 (0,6) > ...
    ingerir_documento(conn, d, [
        _trecho(d, "art-78#1", "art-78", 1, 3, "Art. 78, p. 22", [22],
                CAPUT + "\nI - primeiro inciso. [v:0] [s:0.20]"),
        _trecho(d, "art-78#2", "art-78", 2, 3, "Art. 78, p. 22-23", [22, 23],
                CAPUT + "\nII - segundo inciso. [v:0+1] [s:0.60]"),
        _trecho(d, "art-78#3", "art-78", 3, 3, "Art. 78, p. 23", [23],
                CAPUT + "\nIII - terceiro inciso. [v:0+1+2] [s:0.30]"),
        _trecho(d, "art-127#1", "art-127", 1, 1, "Art. 127, p. 30", [30],
                "Art. 127. Aprovação exige sessenta pontos. [v:0+1+2+3] [s:0.90]"),
    ], Embedder(), MODELO)
    return conn


def test_fluxo_completo_cita_os_artigos_na_ordem_do_reranker(banco):
    emb, rr, llm = Embedder(), Reranker(), LLM("Vale [1] e [2].")
    r = perguntar(banco, "Qual a nota mínima?", emb, rr, llm, instituicao="ufu")
    assert r["recusou"] is False
    assert [c["citacao"] for c in r["citacoes"]] == ["Art. 127, p. 30", "Art. 78, p. 22-23"]
    assert [b["pai_id"] for b in r["blocos"]] == ["d-normas/art-127", "d-normas/art-78"]
    assert r["recuperados_ids"][0] == "d-normas/art-127#1"


def test_cada_componente_e_chamado_uma_vez_com_os_argumentos_certos(banco):
    emb, rr, llm = Embedder(), Reranker(), LLM()
    perguntar(banco, "Qual a nota mínima?", emb, rr, llm, instituicao="ufu")
    assert emb.chamadas == [["Qual a nota mínima?"]]
    assert len(rr.chamadas) == 1 and rr.chamadas[0][0] == "Qual a nota mínima?"
    assert len(llm.chamadas) == 1
    assert "Qual a nota mínima?" in llm.chamadas[0][1]


def test_contexto_expande_os_trechos_irmaos_do_artigo(banco):
    # só 2 recuperados (127 e 78#2): os incisos I e III do artigo 78 entram por expansão
    llm = LLM()
    perguntar(banco, "pergunta", Embedder(), Reranker(), llm, instituicao="ufu", k_recuperacao=2)
    prompt = llm.chamadas[0][1]
    assert "I - primeiro inciso" in prompt and "III - terceiro inciso" in prompt
    assert prompt.count("Caput do artigo setenta e oito") == 1


def test_respeita_max_artigos(banco):
    r = perguntar(banco, "pergunta", Embedder(), Reranker(), LLM("Vale [1]."), instituicao="ufu", max_artigos=1)
    assert len(r["blocos"]) == 1 and r["blocos"][0]["pai_id"] == "d-normas/art-127"


def test_sem_candidatos_recusa_sem_chamar_reranker_nem_llm(banco):
    rr, llm = Reranker(), LLM()
    r = perguntar(banco, "pergunta", Embedder(), rr, llm, instituicao="inexistente")
    assert r["recusou"] is True and r["motivo_recusa"] == "sem_contexto"
    assert r["resposta"] == MENSAGEM_RECUSA
    assert rr.chamadas == [] and llm.chamadas == []
    assert r["blocos"] == [] and r["recuperados_ids"] == []


def test_resposta_com_citacao_invalida_vira_recusa(banco):
    r = perguntar(banco, "pergunta", Embedder(), Reranker(), LLM("Vale [9]."), instituicao="ufu")
    assert r["recusou"] is True and r["motivo_recusa"] == "citacao_invalida"


def test_tempos_somam_recuperacao_e_geracao(banco):
    relogio = Relogio(0.0, 3.0, 10.0, 12.0)
    r = perguntar(banco, "pergunta", Embedder(), Reranker(), LLM(), instituicao="ufu", relogio=relogio)
    assert r["recuperacao_s"] == pytest.approx(3.0)
    assert r["latencia_s"] == pytest.approx(2.0)
    assert r["total_s"] == pytest.approx(5.0)
    assert (r["tokens_entrada"], r["tokens_saida"]) == (300, 40)
