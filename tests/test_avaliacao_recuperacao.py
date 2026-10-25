"""Avaliação da recuperação: hit@k e MRR por documento (e por artigo/passo), distâncias para recusa.

Não usa banco nem modelo: a busca entra como função (`buscar`), então os testes são rápidos.

Contrato (guia.recuperacao.avaliacao):

  carregar_perguntas(caminho) -> list[dict]
      JSONL em UTF-8, uma pergunta por linha, linhas em branco ignoradas, ordem preservada.
      ValueError (com "linha N") se a linha não for JSON válido ou faltar id, pergunta ou tipo.

  interpretar_fonte(fonte_esperada, ids_docs) -> {"docs": [ids], "detalhe": str | None}
      `fonte_esperada` é texto livre separado por vírgula. Cada trecho que for EXATAMENTE um id
      de ids_docs (após strip) é documento; o que sobrar, unido por ", ", é o detalhe (None se
      não sobrar nada). ValueError (com o texto recebido) se nenhum id conhecido for achado.

  casa_detalhe(detalhe, resultado) -> bool
      `resultado` é um dict de busca (usa as chaves "citacao" e "local_id", ambas opcionais).
      Comparação sem acento, sem diferença de maiúscula, e com "-" e "_" lidos como espaço.
      O que vale no detalhe é o localizador, na granularidade de ARTIGO ou PASSO (trechos
      irmãos de um artigo longo compartilham o artigo; na geração busca-se o artigo todo):
        - se o detalhe tem "Art. N": casa quando citacao/local_id tem o mesmo artigo N
          ("Art. 41" não casa com "Art. 410"; "Art. 9" casa com "Art. 9º");
        - senão, se tem "passo N": idem para passo N;
        - senão: o texto do detalhe antes do primeiro "(", como palavra(s) inteira(s).

  avaliar_recuperacao(perguntas, buscar, ids_docs, ks=(1, 3, 5), profundidade=10) -> dict
      buscar(pergunta: str, k: int) -> list[dict] (melhor primeiro; chaves "doc_id",
      "citacao", "local_id", "distancia"). Chamada UMA vez por pergunta, com k=profundidade,
      exceto perguntas com a chave "depende" (pendentes: não são buscadas nem contadas).
      ValueError se profundidade < max(ks), se pergunta que não é "recusa" não tiver
      fonte_esperada, ou se a fonte não citar nenhum id conhecido (a mensagem traz o id da
      pergunta). Resultado, todo serializável em JSON (chaves de k são str):
        n_perguntas      total recebido
        n_avaliadas      perguntas que não são recusa nem pendentes
        n_recusa
        pendentes        [ids]
        hit_doc          {"1": f, "3": f, ...}  fração das avaliadas com algum documento
                         esperado entre os k primeiros
        mrr_doc          média de 1/posição do primeiro documento esperado (0 se fora da
                         profundidade)
        n_com_detalhe    avaliadas cuja fonte tem detalhe
        hit_trecho       igual a hit_doc, só entre as com detalhe: documento esperado E
                         casa_detalhe (None em cada k se n_com_detalhe == 0)
        por_pergunta     [{id, tipo, rank_doc, rank_trecho, distancia_top1}] das avaliadas e
                         das recusas, na ordem de entrada (rank_* = posição 1-based ou None;
                         rank_trecho só existe para quem tem detalhe; recusa tem rank None)
        distancias       {"aplicaveis": {"min", "max"}, "recusa": {"min", "max"},
                          "separavel": bool | None}: min/max da distância do 1º resultado
                         (None se não houver); separavel = max(aplicaveis) < min(recusa)
                         (None se faltar um dos grupos)

  comparar(antes, depois) -> {"mrr_doc": d, "hit_doc": {k: d}, "hit_trecho": {k: d | None}}
      d = depois - antes (arredondado a 6 casas), só para os k presentes nos dois; None se
      algum lado for None.

  salvar_resultado(resultado, caminho, rotulo) / carregar_resultado(caminho) -> dict
      JSON UTF-8 legível (indent=2, sem escapar acentos), cria a pasta se preciso; grava
      {"rotulo": rotulo, **resultado}; carregar devolve exatamente isso.
"""
import json

import pytest

from guia.recuperacao.avaliacao import (
    avaliar_recuperacao,
    carregar_perguntas,
    carregar_resultado,
    casa_detalhe,
    comparar,
    interpretar_fonte,
    salvar_resultado,
)

IDS = {"d-a", "d-b", "d-c", "fagen-gi-estagio", "fagen-gi-estagio-passo-a-passo", "ufu-normas"}


# ---------- carregar_perguntas ----------

def test_carregar_perguntas_utf8_ordem_e_linhas_em_branco(tmp_path):
    arq = tmp_path / "p.jsonl"
    p1 = {"id": "q1", "pergunta": "Qual a duração mínima do estágio?", "tipo": "resposta_direta"}
    p2 = {"id": "q2", "pergunta": "E a avaliação é obrigatória?", "tipo": "recusa"}
    arq.write_text(
        json.dumps(p1, ensure_ascii=False) + "\n\n  \n" + json.dumps(p2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert carregar_perguntas(arq) == [p1, p2]
    assert carregar_perguntas(str(arq)) == [p1, p2]


def test_carregar_perguntas_json_invalido_informa_a_linha(tmp_path):
    arq = tmp_path / "p.jsonl"
    arq.write_text(
        '{"id": "q1", "pergunta": "a", "tipo": "recusa"}\n{nao e json\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="linha 2"):
        carregar_perguntas(arq)


def test_carregar_perguntas_chave_obrigatoria_faltando(tmp_path):
    arq = tmp_path / "p.jsonl"
    arq.write_text('{"id": "q1", "tipo": "recusa"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="linha 1") as erro:
        carregar_perguntas(arq)
    assert "pergunta" in str(erro.value)


# ---------- interpretar_fonte ----------

def test_fonte_so_com_documento():
    assert interpretar_fonte("fagen-gi-estagio", IDS) == {"docs": ["fagen-gi-estagio"], "detalhe": None}


def test_fonte_com_detalhe_nao_confunde_ids_com_prefixo_em_comum():
    r = interpretar_fonte("fagen-gi-estagio-passo-a-passo, passo 4", IDS)
    assert r == {"docs": ["fagen-gi-estagio-passo-a-passo"], "detalhe": "passo 4"}


def test_fonte_detalhe_com_parenteses_e_virgula():
    r = interpretar_fonte("ufu-normas, Art. 41 (inciso III revogado)", IDS)
    assert r == {"docs": ["ufu-normas"], "detalhe": "Art. 41 (inciso III revogado)"}
    r = interpretar_fonte("ufu-normas, Art. 41, III", IDS)
    assert r == {"docs": ["ufu-normas"], "detalhe": "Art. 41, III"}


def test_fonte_com_dois_documentos():
    assert interpretar_fonte("d-a, d-b", IDS) == {"docs": ["d-a", "d-b"], "detalhe": None}


@pytest.mark.parametrize("texto", ["", "documento-que-nao-existe, Art. 2", "Art. 41"])
def test_fonte_sem_id_conhecido_levanta_valueerror(texto):
    with pytest.raises(ValueError) as erro:
        interpretar_fonte(texto, IDS)
    assert texto in str(erro.value) or texto == ""


# ---------- casa_detalhe ----------

@pytest.mark.parametrize(
    "detalhe, resultado, esperado",
    [
        ("Art. 41 (inciso III revogado)", {"citacao": "Art. 41, p. 12"}, True),
        ("Art. 41 II", {"citacao": "Art. 41, p. 12"}, True),
        ("Art. 41 §3", {"citacao": "Art. 41, p. 12"}, True),  # granularidade: artigo
        ("Art. 41 II", {"citacao": "Art. 410, p. 90"}, False),
        ("Art. 41 II", {"citacao": "Art. 4º, p. 3"}, False),
        ("Art. 9", {"citacao": "Art. 9º, p. 3"}, True),
        ("Art. 9", {"citacao": "Art. 90, p. 30"}, False),
        ("art. 41", {"citacao": "", "local_id": "art-41"}, True),
        ("Art. 41", {"citacao": "Passo 4"}, False),
        ("passo 4", {"citacao": "Passo 4"}, True),
        ("passo 4", {"citacao": "Passo 4 (Aluno)", "local_id": "passo-4#1"}, True),
        ("passo 4", {"citacao": "", "local_id": "passo-4"}, True),
        ("passo 4", {"citacao": "Passo 14"}, False),
        ("contato", {"citacao": "Contato"}, True),
        ("contato", {"citacao": "Telefone"}, False),
        ("texto principal", {"citacao": "Texto principal"}, True),
        ("Seção Contato", {"citacao": "secao contato"}, True),  # sem acento / maiúscula
    ],
)
def test_casa_detalhe(detalhe, resultado, esperado):
    assert casa_detalhe(detalhe, resultado) is esperado


def test_casa_detalhe_tolera_chaves_ausentes():
    assert casa_detalhe("contato", {}) is False


# ---------- avaliar_recuperacao ----------

def _r(doc_id, citacao="x", distancia=0.5, local_id=None):
    return {"doc_id": doc_id, "citacao": citacao, "distancia": distancia,
            "local_id": local_id or citacao}


PERGUNTAS = [
    {"id": "p1", "pergunta": "pergunta um", "tipo": "resposta_direta", "fonte_esperada": "d-a"},
    {"id": "p2", "pergunta": "pergunta dois", "tipo": "procedimento",
     "fonte_esperada": "d-b, passo 4"},
    {"id": "p3", "pergunta": "pergunta tres", "tipo": "resposta_direta", "fonte_esperada": "d-c"},
    {"id": "p4", "pergunta": "pergunta quatro", "tipo": "recusa", "fonte_esperada": ""},
    {"id": "p5", "pergunta": "pergunta cinco", "tipo": "resposta_direta",
     "fonte_esperada": "d-c", "depende": "atividades"},
]

RESPOSTAS = {
    "pergunta um": [_r("d-b", distancia=0.30), _r("d-a", distancia=0.35), _r("d-c", distancia=0.4)],
    "pergunta dois": [_r("d-b", "Passo 3", 0.25), _r("d-b", "Passo 4", 0.26), _r("d-a", "x", 0.3)],
    "pergunta tres": [_r("d-a", distancia=0.40), _r("d-b", distancia=0.41)],
    "pergunta quatro": [_r("d-a", distancia=0.70), _r("d-b", distancia=0.72)],
}


class BuscaFalsa:
    def __init__(self, respostas):
        self.respostas = respostas
        self.chamadas = []

    def __call__(self, pergunta, k):
        self.chamadas.append((pergunta, k))
        return self.respostas[pergunta]


def _avaliar(respostas=None, perguntas=None, **kw):
    busca = BuscaFalsa(respostas or RESPOSTAS)
    r = avaliar_recuperacao(perguntas or PERGUNTAS, busca, IDS, **kw)
    return r, busca


def test_contagens_e_pendentes_nao_sao_buscados():
    r, busca = _avaliar()
    assert (r["n_perguntas"], r["n_avaliadas"], r["n_recusa"]) == (5, 3, 1)
    assert r["pendentes"] == ["p5"]
    assert sorted(p for p, _ in busca.chamadas) == [
        "pergunta dois", "pergunta quatro", "pergunta tres", "pergunta um"
    ]
    assert all(k == 10 for _, k in busca.chamadas)


def test_hit_doc_e_mrr():
    r, _ = _avaliar()
    assert r["hit_doc"] == {"1": pytest.approx(1 / 3), "3": pytest.approx(2 / 3), "5": pytest.approx(2 / 3)}
    assert r["mrr_doc"] == pytest.approx((1 / 2 + 1 + 0) / 3)


def test_hit_trecho_so_entre_as_perguntas_com_detalhe():
    r, _ = _avaliar()
    assert r["n_com_detalhe"] == 1
    assert r["hit_trecho"] == {"1": 0.0, "3": 1.0, "5": 1.0}


def test_hit_trecho_none_quando_ninguem_tem_detalhe():
    r, _ = _avaliar(perguntas=[PERGUNTAS[0]])
    assert r["n_com_detalhe"] == 0
    assert r["hit_trecho"] == {"1": None, "3": None, "5": None}


def test_por_pergunta():
    r, _ = _avaliar()
    por_id = {p["id"]: p for p in r["por_pergunta"]}
    assert [p["id"] for p in r["por_pergunta"]] == ["p1", "p2", "p3", "p4"]
    assert por_id["p1"]["rank_doc"] == 2 and por_id["p1"]["rank_trecho"] is None
    assert por_id["p2"]["rank_doc"] == 1 and por_id["p2"]["rank_trecho"] == 2
    assert por_id["p3"]["rank_doc"] is None
    assert por_id["p4"]["tipo"] == "recusa"
    assert por_id["p4"]["rank_doc"] is None and por_id["p4"]["rank_trecho"] is None
    assert por_id["p4"]["distancia_top1"] == pytest.approx(0.70)
    assert por_id["p1"]["distancia_top1"] == pytest.approx(0.30)


def test_usa_a_primeira_posicao_quando_o_documento_aparece_mais_de_uma_vez():
    resp = dict(RESPOSTAS)
    resp["pergunta um"] = [_r("d-b"), _r("d-a"), _r("d-a")]
    r, _ = _avaliar(resp)
    assert {p["id"]: p for p in r["por_pergunta"]}["p1"]["rank_doc"] == 2


def test_so_conta_ate_a_profundidade():
    resp = dict(RESPOSTAS)
    resp["pergunta um"] = [_r("d-b"), _r("d-b"), _r("d-b"), _r("d-a")]  # d-a na posição 4
    r, busca = _avaliar(resp, ks=(1, 3), profundidade=3)
    assert {p["id"]: p for p in r["por_pergunta"]}["p1"]["rank_doc"] is None
    assert all(k == 3 for _, k in busca.chamadas)


def test_aceita_varios_documentos_esperados():
    perguntas = [{"id": "m1", "pergunta": "pergunta um", "tipo": "resposta_direta",
                  "fonte_esperada": "d-c, d-a"}]
    r, _ = _avaliar(perguntas=perguntas)
    assert r["por_pergunta"][0]["rank_doc"] == 2


def test_distancias_e_separabilidade():
    r, _ = _avaliar()
    assert r["distancias"]["aplicaveis"] == {"min": pytest.approx(0.25), "max": pytest.approx(0.40)}
    assert r["distancias"]["recusa"] == {"min": pytest.approx(0.70), "max": pytest.approx(0.70)}
    assert r["distancias"]["separavel"] is True


def test_nao_separavel_quando_a_recusa_fica_mais_perto_que_uma_pergunta_valida():
    resp = dict(RESPOSTAS)
    resp["pergunta quatro"] = [_r("d-a", distancia=0.35)]
    r, _ = _avaliar(resp)
    assert r["distancias"]["separavel"] is False


def test_separavel_none_sem_recusas():
    r, _ = _avaliar(perguntas=PERGUNTAS[:3])
    assert r["distancias"]["recusa"] == {"min": None, "max": None}
    assert r["distancias"]["separavel"] is None


def test_busca_sem_resultados_nao_quebra():
    resp = dict(RESPOSTAS)
    resp["pergunta um"] = []
    r, _ = _avaliar(resp)
    p1 = {p["id"]: p for p in r["por_pergunta"]}["p1"]
    assert p1["rank_doc"] is None and p1["distancia_top1"] is None


def test_profundidade_menor_que_o_maior_k_levanta_valueerror():
    with pytest.raises(ValueError):
        _avaliar(ks=(1, 5), profundidade=3)


def test_pergunta_sem_fonte_levanta_valueerror_com_o_id():
    perguntas = [{"id": "q77", "pergunta": "pergunta um", "tipo": "resposta_direta"}]
    with pytest.raises(ValueError, match="q77"):
        _avaliar(perguntas=perguntas)


def test_fonte_com_id_desconhecido_levanta_valueerror_com_o_id_da_pergunta():
    perguntas = [{"id": "q88", "pergunta": "pergunta um", "tipo": "resposta_direta",
                  "fonte_esperada": "d-typo, Art. 1"}]
    with pytest.raises(ValueError, match="q88"):
        _avaliar(perguntas=perguntas)


def test_resultado_e_serializavel_em_json_sem_mudar():
    r, _ = _avaliar()
    assert json.loads(json.dumps(r)) == r


# ---------- comparar ----------

def test_comparar_deltas():
    antes = {"mrr_doc": 0.50, "hit_doc": {"1": 0.40, "3": 0.60, "5": 0.70},
             "hit_trecho": {"1": 0.10, "3": None, "5": 0.50}}
    depois = {"mrr_doc": 0.65, "hit_doc": {"1": 0.55, "3": 0.60, "10": 0.9},
              "hit_trecho": {"1": 0.30, "3": 0.40, "5": None}}
    d = comparar(antes, depois)
    assert d["mrr_doc"] == pytest.approx(0.15)
    assert d["hit_doc"] == {"1": pytest.approx(0.15), "3": pytest.approx(0.0)}
    assert d["hit_trecho"] == {"1": pytest.approx(0.20), "3": None, "5": None}


# ---------- salvar / carregar ----------

def test_salvar_e_carregar_resultado(tmp_path):
    r, _ = _avaliar()
    caminho = tmp_path / "novos" / "resultados" / "baseline.json"
    salvar_resultado(r, caminho, "baseline-vetorial")
    texto = caminho.read_text(encoding="utf-8")
    assert "\n" in texto and '"rotulo": "baseline-vetorial"' in texto
    assert carregar_resultado(caminho) == {"rotulo": "baseline-vetorial", **r}


def test_salvar_nao_escapa_acentos(tmp_path):
    caminho = tmp_path / "r.json"
    salvar_resultado({"mrr_doc": 0.5}, caminho, "híbrido-vetorial-textual")
    assert "híbrido" in caminho.read_text(encoding="utf-8")
