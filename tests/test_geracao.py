"""Camada de geração (independe do provedor de LLM): contexto, prompt, citação e recusa.

Princípios (decididos com base no que a avaliação mostrou):
  * Recusa não se resolve na recuperação (distância vetorial e score do reranker não separam
    pergunta sem resposta de pergunta válida). Ela é resolvida aqui, em três degraus:
    sem contexto -> recusa sem chamar o LLM; LLM recusa; resposta sem citação válida é rejeitada.
  * O LLM cita por NÚMERO de bloco ([1], [2]); o código converte o número em citação real
    (artigo e página) a partir dos metadados. Assim não existe citação inventada: número fora do
    contexto => a resposta inteira é rejeitada (para normas, citação falsa é pior que recusa).
  * A unidade do contexto é o ARTIGO (trechos irmãos do mesmo pai_id, repetições do caput
    removidas), só para tipo_doc "resolucao". Procedimentos e páginas NÃO são expandidos: os
    passos de um procedimento compartilham um pai_id e fundi-los esconderia o passo certo.

Contrato (guia.geracao)

  MENSAGEM_RECUSA (str) e TOKEN_RECUSA = "NAO_ENCONTRADO"

  juntar_trechos_irmaos(textos: list[str]) -> str
      Junta, na ordem dada, os textos de trechos irmãos. As LINHAS iniciais comuns a todos
      (o caput repetido, comparadas com strip) aparecem uma vez só, no primeiro; dos demais
      são removidas. Nunca remove um trecho inteiro: cada texto mantém ao menos uma linha.
      Um único texto volta com strip. Separador: "\n".

  citacao_do_bloco(trechos: list[dict]) -> str
      Prefixo = citacao do primeiro trecho até ", p." (ou inteira se não houver). Páginas =
      união ordenada de "paginas" de todos (None/ausente = nenhuma). Formato: "<prefixo>, p. N",
      "<prefixo>, p. A-B" (intervalo contínuo) ou "<prefixo>, p. A, B, C"; sem páginas: só o prefixo.

  montar_contexto(conn, recuperados, max_artigos=3) -> list[dict]
      `recuperados`: lista de dicts de busca (basta a chave "id"), melhor primeiro. Ids que não
      existem no banco são ignorados. Para tipo_doc "resolucao": um bloco por pai_id, com TODOS os
      trechos do pai_id (ordem de "parte"). Para os demais tipos: um bloco por trecho recuperado.
      Blocos na ordem da primeira aparição; no máximo max_artigos. Cada bloco:
        indice (1-based), pai_id, doc_id, titulo_doc, url, citacao (citacao_do_bloco),
        paginas (união ordenada, lista), texto (juntar_trechos_irmaos), ids (ids dos trechos
        do bloco, na ordem de "parte")

  montar_prompt(pergunta, blocos) -> (system, user)
      ValueError se blocos estiver vazio. `system` explica as regras e contém TOKEN_RECUSA e o
      formato de citação [n]. `user` traz a pergunta e, para cada bloco na ordem, o rótulo [n],
      a citação e o texto.

  responder(pergunta, blocos, llm, relogio=time.perf_counter) -> dict
      llm(system, user) -> {"texto": str, "tokens_entrada": int|None, "tokens_saida": int|None}
      Devolve {resposta, resposta_bruta, recusou, motivo_recusa, citacoes, tokens_entrada,
      tokens_saida, latencia_s}.
        - sem blocos: recusou, motivo "sem_contexto", LLM NÃO é chamado, resposta=MENSAGEM_RECUSA,
          tokens None, latencia_s 0.0, resposta_bruta None
        - o LLM é chamado UMA vez com montar_prompt(...); latencia_s = relogio() depois - antes
        - texto que começa com TOKEN_RECUSA (strip, sem diferenciar maiúscula): recusou,
          motivo "llm_recusou", resposta=MENSAGEM_RECUSA, citacoes=[]
        - citações lidas de [n] e [n, m]; número fora de 1..len(blocos): recusou, motivo
          "citacao_invalida"; resposta sem nenhuma citação: recusou, motivo "sem_citacao"
          (em ambos resposta=MENSAGEM_RECUSA e resposta_bruta guarda o texto do LLM)
        - válida: recusou False, motivo None, resposta == texto do LLM, citacoes = lista sem
          repetição na ordem da primeira aparição, cada uma com
          {indice, citacao, doc_id, titulo_doc, url}
        - tokens_entrada/tokens_saida repassados do LLM (None se vierem None)

Testes de banco usam schema temporário e são pulados sem o Docker (guia-db).
"""
import uuid

import numpy as np
import psycopg
import pytest

from guia.banco import conectar, criar_esquema
from guia.geracao import (
    MENSAGEM_RECUSA,
    TOKEN_RECUSA,
    citacao_do_bloco,
    juntar_trechos_irmaos,
    montar_contexto,
    montar_prompt,
    responder,
)
from guia.ingestao.carga import DIMENSAO, ingerir_documento

MODELO = "bge-m3"


# ---------- juntar_trechos_irmaos ----------

def test_caput_repetido_aparece_uma_vez():
    textos = ["Art. 3º Para efeito:\nI - a;\nII - b;", "Art. 3º Para efeito:\nIII - c;",
              "Art. 3º Para efeito:\nIV - d."]
    assert juntar_trechos_irmaos(textos) == "Art. 3º Para efeito:\nI - a;\nII - b;\nIII - c;\nIV - d."


def test_caput_de_varias_linhas_e_linhas_em_branco():
    caput = "Art. 34.  Ressalvados os casos em que os projetos\n\npedagógicos vedam a matrícula."
    textos = [caput + "\n§ 1º  Primeiro.\n", caput + "\n      § 2º  Segundo.\n", caput + "\n§ 3º  Terceiro."]
    r = juntar_trechos_irmaos(textos)
    assert r.count("Ressalvados") == 1
    assert r.index("§ 1º") < r.index("§ 2º") < r.index("§ 3º")


def test_um_texto_so_volta_com_strip():
    assert juntar_trechos_irmaos(["  Art. 1º  Texto.\n\n"]) == "Art. 1º  Texto."


def test_sem_prefixo_comum_so_junta():
    assert juntar_trechos_irmaos(["Primeiro", "Segundo"]) == "Primeiro\nSegundo"


def test_nunca_remove_um_trecho_inteiro():
    r = juntar_trechos_irmaos(["Art. 5º  Igual.", "Art. 5º  Igual."])
    assert r.count("Igual.") == 2


# ---------- citacao_do_bloco ----------

@pytest.mark.parametrize(
    "trechos, esperado",
    [
        ([{"citacao": "Art. 3º, p. 2", "paginas": [2]}, {"citacao": "Art. 3º, p. 2-3", "paginas": [2, 3]},
          {"citacao": "Art. 3º, p. 3", "paginas": [3]}], "Art. 3º, p. 2-3"),
        ([{"citacao": "Art. 78, p. 12", "paginas": [12]}, {"citacao": "Art. 78, p. 14", "paginas": [14]}],
         "Art. 78, p. 12, 14"),
        ([{"citacao": "Art. 50, p. 17", "paginas": [17]}], "Art. 50, p. 17"),
        ([{"citacao": "Texto principal", "paginas": []}], "Texto principal"),
        ([{"citacao": "Contato"}], "Contato"),
        ([{"citacao": "Passo 5 (COORDENAÇÃO DE ESTÁGIO), p. 2", "paginas": [2]}],
         "Passo 5 (COORDENAÇÃO DE ESTÁGIO), p. 2"),
    ],
)
def test_citacao_do_bloco(trechos, esperado):
    assert citacao_do_bloco(trechos) == esperado


# ---------- montar_contexto (banco) ----------

def _doc(doc_id, tipo_doc_titulo):
    return {"id": doc_id, "instituicao": "ufu", "titulo": tipo_doc_titulo,
            "url": f"https://exemplo.edu.br/{doc_id}", "tipo": "pdf",
            "data_ref": "2024", "prioridade": 1}


def _trecho(doc, tipo_doc, local, pai, parte, total, citacao, paginas, texto):
    return {"id": f"{doc['id']}/{local}", "doc_id": doc["id"], "local_id": local,
            "tipo_doc": tipo_doc, "instituicao": "ufu", "titulo_doc": doc["titulo"],
            "url": doc["url"], "data_ref": "2024", "prioridade": 1, "paginas": paginas,
            "localizacao": {}, "citacao": citacao, "texto": texto,
            "pai_id": f"{doc['id']}/{pai}", "parte": parte, "total_partes": total,
            "hash_texto": f"h-{doc['id']}-{local}", "metadados": {}}


NORMAS, PROC = _doc("d-normas", "Normas Gerais"), _doc("d-proc", "Passo a passo")
CAPUT = "Art. 78. Caput do artigo setenta e oito."
A78 = ["d-normas/art-78#1", "d-normas/art-78#2", "d-normas/art-78#3"]
A127, P4, P5 = "d-normas/art-127#1", "d-proc/passo-4#1", "d-proc/passo-5#1"


class EmbedderConstante:
    def __call__(self, textos):
        v = np.zeros(DIMENSAO)
        v[0] = 1.0
        return [v.tolist() for _ in textos]


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
    emb = EmbedderConstante()
    ingerir_documento(conn, NORMAS, [
        _trecho(NORMAS, "resolucao", "art-78#1", "art-78", 1, 3, "Art. 78, p. 22", [22],
                CAPUT + "\nI - primeiro inciso."),
        _trecho(NORMAS, "resolucao", "art-78#2", "art-78", 2, 3, "Art. 78, p. 22-23", [22, 23],
                CAPUT + "\nII - segundo inciso."),
        _trecho(NORMAS, "resolucao", "art-78#3", "art-78", 3, 3, "Art. 78, p. 23", [23],
                CAPUT + "\nIII - terceiro inciso."),
        _trecho(NORMAS, "resolucao", "art-127#1", "art-127", 1, 1, "Art. 127, p. 30", [30],
                "Art. 127. Aprovação exige sessenta pontos."),
    ], emb, MODELO)
    ingerir_documento(conn, PROC, [
        _trecho(PROC, "procedimento", "passo-4#1", "passos", 4, 10,
                "Passo 4 (ALUNO), p. 2", [2], "4º (ALUNO) Envia o formulário."),
        _trecho(PROC, "procedimento", "passo-5#1", "passos", 5, 10,
                "Passo 5 (COORDENAÇÃO), p. 2", [2], "5º (COORDENAÇÃO) Recebe o formulário."),
    ], emb, MODELO)
    return conn


def test_artigo_vira_um_bloco_com_todos_os_irmaos_e_caput_uma_vez(banco):
    blocos = montar_contexto(banco, [{"id": A78[1]}, {"id": A127}, {"id": A78[0]}])
    assert [b["pai_id"] for b in blocos] == ["d-normas/art-78", "d-normas/art-127"]
    b = blocos[0]
    assert b["ids"] == A78
    assert b["texto"].count("Caput do artigo") == 1
    assert b["texto"].index("I - primeiro") < b["texto"].index("II - segundo") < b["texto"].index("III - terceiro")
    assert b["citacao"] == "Art. 78, p. 22-23"
    assert b["paginas"] == [22, 23]
    assert (b["indice"], blocos[1]["indice"]) == (1, 2)
    assert b["doc_id"] == "d-normas" and b["titulo_doc"] == "Normas Gerais"
    assert b["url"] == "https://exemplo.edu.br/d-normas"


def test_respeita_max_artigos(banco):
    blocos = montar_contexto(banco, [{"id": A78[2]}, {"id": A127}], max_artigos=1)
    assert [b["pai_id"] for b in blocos] == ["d-normas/art-78"]


def test_procedimento_nao_e_expandido_nem_fundido(banco):
    blocos = montar_contexto(banco, [{"id": P4}, {"id": P5}])
    assert [b["ids"] for b in blocos] == [[P4], [P5]]
    assert blocos[0]["citacao"] == "Passo 4 (ALUNO), p. 2"
    assert "Recebe o formulário" not in blocos[0]["texto"]


def test_ignora_ids_inexistentes_e_lista_vazia(banco):
    blocos = montar_contexto(banco, [{"id": "nao/existe#1"}, {"id": A127}])
    assert [b["ids"] for b in blocos] == [[A127]]
    assert montar_contexto(banco, []) == []


# ---------- montar_prompt ----------

BLOCOS = [
    {"indice": 1, "citacao": "Art. 127, p. 30", "texto": "Art. 127. Aprovação exige sessenta pontos.",
     "doc_id": "d-normas", "titulo_doc": "Normas Gerais", "url": "u1", "pai_id": "p1", "ids": ["a"], "paginas": [30]},
    {"indice": 2, "citacao": "Art. 78, p. 22-23", "texto": "Art. 78. Caput do artigo.",
     "doc_id": "d-normas", "titulo_doc": "Normas Gerais", "url": "u2", "pai_id": "p2", "ids": ["b"], "paginas": [22, 23]},
]


def test_prompt_traz_pergunta_blocos_numerados_e_regras():
    system, user = montar_prompt("Qual a nota mínima?", BLOCOS)
    assert TOKEN_RECUSA in system and "[1]" in system
    assert "Qual a nota mínima?" in user
    assert user.index("[1]") < user.index("[2]")
    for b in BLOCOS:
        assert b["citacao"] in user and b["texto"] in user


def test_prompt_sem_blocos_levanta_valueerror():
    with pytest.raises(ValueError):
        montar_prompt("pergunta", [])


# ---------- responder ----------

class LLMFalso:
    def __init__(self, texto, tokens_entrada=120, tokens_saida=30):
        self.retorno = {"texto": texto, "tokens_entrada": tokens_entrada, "tokens_saida": tokens_saida}
        self.chamadas = []

    def __call__(self, system, user):
        self.chamadas.append((system, user))
        return self.retorno


class Relogio:
    def __init__(self, *marcas):
        self.marcas = list(marcas)

    def __call__(self):
        return self.marcas.pop(0)


def test_sem_contexto_recusa_sem_chamar_o_llm():
    llm = LLMFalso("qualquer coisa [1]")
    r = responder("pergunta", [], llm)
    assert llm.chamadas == []
    assert r["recusou"] is True and r["motivo_recusa"] == "sem_contexto"
    assert r["resposta"] == MENSAGEM_RECUSA and r["resposta_bruta"] is None
    assert r["citacoes"] == []
    assert r["tokens_entrada"] is None and r["tokens_saida"] is None and r["latencia_s"] == 0.0


def test_resposta_valida_traz_citacoes_tokens_e_latencia():
    llm = LLMFalso("São 60 pontos [1], conforme a regra de aprovação [2].", 200, 45)
    r = responder("Qual a nota mínima?", BLOCOS, llm, relogio=Relogio(10.0, 12.5))
    assert r["recusou"] is False and r["motivo_recusa"] is None
    assert r["resposta"] == r["resposta_bruta"] == "São 60 pontos [1], conforme a regra de aprovação [2]."
    assert r["citacoes"] == [
        {"indice": 1, "citacao": "Art. 127, p. 30", "doc_id": "d-normas", "titulo_doc": "Normas Gerais", "url": "u1"},
        {"indice": 2, "citacao": "Art. 78, p. 22-23", "doc_id": "d-normas", "titulo_doc": "Normas Gerais", "url": "u2"},
    ]
    assert (r["tokens_entrada"], r["tokens_saida"]) == (200, 45)
    assert r["latencia_s"] == pytest.approx(2.5)


def test_chama_o_llm_uma_vez_com_o_prompt_montado():
    llm = LLMFalso("Resposta [1].")
    responder("Qual a nota mínima?", BLOCOS, llm)
    assert llm.chamadas == [montar_prompt("Qual a nota mínima?", BLOCOS)]


def test_citacao_repetida_conta_uma_vez_e_aceita_lista():
    r = responder("p", BLOCOS, LLMFalso("Vale [2] e também [2]. Ver [1, 2]."))
    assert [c["indice"] for c in r["citacoes"]] == [2, 1]


@pytest.mark.parametrize("texto", ["NAO_ENCONTRADO", "  nao_encontrado.\n", "NAO_ENCONTRADO: a norma não cobre isso [1]"])
def test_llm_recusou(texto):
    r = responder("p", BLOCOS, LLMFalso(texto))
    assert r["recusou"] is True and r["motivo_recusa"] == "llm_recusou"
    assert r["resposta"] == MENSAGEM_RECUSA and r["citacoes"] == []
    assert r["resposta_bruta"] == texto
    assert r["tokens_entrada"] == 120


@pytest.mark.parametrize("texto", ["Vale [5].", "Vale [0].", "Vale [1] e [3]."])
def test_citacao_fora_do_contexto_rejeita_a_resposta_inteira(texto):
    r = responder("p", BLOCOS, LLMFalso(texto))
    assert r["recusou"] is True and r["motivo_recusa"] == "citacao_invalida"
    assert r["resposta"] == MENSAGEM_RECUSA and r["resposta_bruta"] == texto
    assert r["citacoes"] == []


def test_resposta_sem_citacao_e_rejeitada():
    r = responder("p", BLOCOS, LLMFalso("São 60 pontos, sem citar nada."))
    assert r["recusou"] is True and r["motivo_recusa"] == "sem_citacao"
    assert r["resposta"] == MENSAGEM_RECUSA


def test_tokens_none_sao_repassados():
    r = responder("p", BLOCOS, LLMFalso("Vale [1].", None, None))
    assert r["tokens_entrada"] is None and r["tokens_saida"] is None
