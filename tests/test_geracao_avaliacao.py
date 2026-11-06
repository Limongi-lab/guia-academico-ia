"""Avaliação da geração: recusa correta, recusa indevida, citação correta, tokens, custo, latência.

Mede o que a recuperação não consegue medir (a recusa se decide na geração). Não usa banco,
modelo nem LLM: a função de resposta entra como parâmetro.

Contrato (guia.geracao_avaliacao)
  avaliar_geracao(perguntas, responder_fn, ids_docs, preco_entrada=None, preco_saida=None) -> dict
    perguntas: dicts de perguntas.jsonl. As que têm "depende" são pendentes: não são
    respondidas nem contadas. `responder_fn(pergunta: dict) -> dict` devolve o dicionário de
    guia.geracao.responder (chaves usadas: recusou, motivo_recusa, citacoes, tokens_entrada,
    tokens_saida, latencia_s). Se o dicionário tiver "erro" (texto não vazio), a pergunta conta
    como ERRO: fica fora de todas as taxas.
    ValueError (com o id) se pergunta que não é "recusa" não tiver fonte_esperada ou citar só
    ids desconhecidos (mesma regra de guia.recuperacao.avaliacao.interpretar_fonte).
    Resultado (tudo serializável em JSON):
      n_perguntas, n_avaliadas (sem pendentes e sem erros), pendentes [ids], n_erros, erros [ids]
      n_recusa (tipo recusa), n_recusa_correta (recusou), taxa_recusa_correta (None se n_recusa=0)
      n_validas (tipo != recusa), n_respondidas (não recusou), n_recusa_indevida (recusou),
      taxa_recusa_indevida (= indevida / n_validas, None se 0)
      n_citacao_correta: respondidas cuja lista de citacoes tem alguma com doc_id em docs e, se a
        fonte tem detalhe, casa_detalhe(detalhe, {"citacao": c["citacao"]}) verdadeiro
      taxa_citacao_correta (= n_citacao_correta / n_respondidas, None se 0)
      aproveitamento (= n_citacao_correta / n_validas, None se 0)
      motivos_recusa: {motivo: quantidade} sobre todas as recusas das avaliadas
      Custo e latência, só sobre as avaliadas em que o LLM foi chamado (motivo != "sem_contexto"):
        chamadas_llm, tokens_entrada_total, tokens_saida_total (soma ignorando None),
        tokens_entrada_medio, tokens_saida_medio (média sobre as chamadas com valor, None se
        nenhuma), latencia_media_s, latencia_mediana_s, latencia_max_s (None se não houve chamada)
        custo_usd = (tokens_entrada_total*preco_entrada + tokens_saida_total*preco_saida)/1e6
        (preços em USD por milhão de tokens); None se algum preço faltar;
        custo_usd_por_chamada = custo_usd / chamadas_llm (None se custo None ou sem chamadas)
      por_pergunta: uma linha por pergunta não pendente, na ordem de entrada, com id, tipo,
        recusou, motivo_recusa, citacao_ok (True/False só para válidas respondidas; senão None),
        tokens_entrada, tokens_saida, latencia_s, erro (None se não houve)
"""
import json

import pytest

from guia.geracao_avaliacao import avaliar_geracao

IDS = {"d-a", "d-b"}


def _cit(doc, citacao):
    return {"indice": 1, "citacao": citacao, "doc_id": doc, "titulo_doc": "t", "url": "u"}


def _resp(recusou=False, motivo=None, citacoes=(), ti=100, ts=20, lat=1.0):
    return {"recusou": recusou, "motivo_recusa": motivo, "citacoes": list(citacoes),
            "tokens_entrada": ti, "tokens_saida": ts, "latencia_s": lat}


PERGUNTAS = [
    {"id": "v1", "pergunta": "p1", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 41"},
    {"id": "v2", "pergunta": "p2", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 50"},
    {"id": "v3", "pergunta": "p3", "tipo": "procedimento", "fonte_esperada": "d-b"},
    {"id": "v4", "pergunta": "p4", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 60"},
    {"id": "r1", "pergunta": "p5", "tipo": "recusa", "fonte_esperada": ""},
    {"id": "r2", "pergunta": "p6", "tipo": "recusa", "fonte_esperada": ""},
    {"id": "pd", "pergunta": "p7", "tipo": "resposta_direta", "fonte_esperada": "d-a", "depende": "x"},
    {"id": "e1", "pergunta": "p8", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 70"},
]

RESPOSTAS = {
    "v1": _resp(citacoes=[_cit("d-a", "Art. 41, p. 12")], ti=100, ts=20, lat=1.0),   # certa
    "v2": _resp(citacoes=[_cit("d-a", "Art. 51, p. 3")], ti=200, ts=40, lat=3.0),    # artigo errado
    "v3": _resp(recusou=True, motivo="llm_recusou", ti=50, ts=5, lat=2.0),           # recusa indevida
    "v4": _resp(citacoes=[_cit("d-b", "Art. 60, p. 1")], ti=100, ts=10, lat=2.0),    # documento errado
    "r1": _resp(recusou=True, motivo="llm_recusou", ti=60, ts=6, lat=1.0),           # recusa certa
    "r2": _resp(citacoes=[_cit("d-a", "Art. 9, p. 2")], ti=80, ts=8, lat=1.0),       # devia recusar
    "e1": {"erro": "ErroLLM: cota excedida"},
}


class Responder:
    def __init__(self, respostas):
        self.respostas = respostas
        self.chamadas = []

    def __call__(self, pergunta):
        self.chamadas.append(pergunta["id"])
        return self.respostas[pergunta["id"]]


def _avaliar(respostas=None, perguntas=None, **kw):
    fn = Responder(respostas or RESPOSTAS)
    return avaliar_geracao(perguntas or PERGUNTAS, fn, IDS, **kw), fn


def test_contagens_pendentes_e_erros():
    r, fn = _avaliar()
    assert (r["n_perguntas"], r["n_avaliadas"], r["n_erros"]) == (8, 6, 1)
    assert r["pendentes"] == ["pd"] and r["erros"] == ["e1"]
    assert "pd" not in fn.chamadas and fn.chamadas.count("v1") == 1


def test_recusa_correta_e_indevida():
    r, _ = _avaliar()
    assert (r["n_recusa"], r["n_recusa_correta"], r["taxa_recusa_correta"]) == (2, 1, 0.5)
    assert r["n_validas"] == 4 and r["n_respondidas"] == 3
    assert r["n_recusa_indevida"] == 1 and r["taxa_recusa_indevida"] == pytest.approx(0.25)


def test_citacao_correta_exige_documento_e_artigo():
    r, _ = _avaliar()
    assert r["n_citacao_correta"] == 1
    assert r["taxa_citacao_correta"] == pytest.approx(1 / 3)
    assert r["aproveitamento"] == pytest.approx(1 / 4)
    por_id = {x["id"]: x for x in r["por_pergunta"]}
    assert por_id["v1"]["citacao_ok"] is True
    assert por_id["v2"]["citacao_ok"] is False and por_id["v4"]["citacao_ok"] is False
    assert por_id["v3"]["citacao_ok"] is None and por_id["r2"]["citacao_ok"] is None


def test_fonte_sem_detalhe_basta_o_documento():
    perguntas = [{"id": "v9", "pergunta": "p", "tipo": "resposta_direta", "fonte_esperada": "d-b"}]
    r, _ = _avaliar({"v9": _resp(citacoes=[_cit("d-b", "Texto principal")])}, perguntas)
    assert r["n_citacao_correta"] == 1


def test_motivos_de_recusa():
    r, _ = _avaliar()
    assert r["motivos_recusa"] == {"llm_recusou": 2}


def test_tokens_e_latencia_so_sobre_chamadas_ao_llm():
    r, _ = _avaliar()
    assert r["chamadas_llm"] == 6
    assert (r["tokens_entrada_total"], r["tokens_saida_total"]) == (590, 89)
    assert r["tokens_entrada_medio"] == pytest.approx(590 / 6)
    assert r["tokens_saida_medio"] == pytest.approx(89 / 6)
    assert r["latencia_media_s"] == pytest.approx(10 / 6)
    assert r["latencia_mediana_s"] == pytest.approx(1.5) and r["latencia_max_s"] == 3.0


def test_custo_em_usd_por_milhao_de_tokens():
    r, _ = _avaliar(preco_entrada=0.10, preco_saida=0.40)
    assert r["custo_usd"] == pytest.approx((590 * 0.10 + 89 * 0.40) / 1e6)
    assert r["custo_usd_por_chamada"] == pytest.approx(r["custo_usd"] / 6)
    sem, _ = _avaliar(preco_entrada=0.10)
    assert sem["custo_usd"] is None and sem["custo_usd_por_chamada"] is None


def test_sem_contexto_conta_como_recusa_mas_nao_como_chamada_ao_llm():
    perguntas = [{"id": "r3", "pergunta": "p", "tipo": "recusa", "fonte_esperada": ""}]
    resp = {"r3": _resp(recusou=True, motivo="sem_contexto", ti=None, ts=None, lat=0.0)}
    r, _ = _avaliar(resp, perguntas)
    assert r["n_recusa_correta"] == 1 and r["motivos_recusa"] == {"sem_contexto": 1}
    assert r["chamadas_llm"] == 0
    assert r["tokens_entrada_total"] == 0 and r["tokens_entrada_medio"] is None
    assert r["latencia_media_s"] is None


def test_tokens_none_sao_ignorados_na_soma_e_na_media():
    perguntas = [{"id": "a", "pergunta": "p", "tipo": "recusa", "fonte_esperada": ""},
                 {"id": "b", "pergunta": "p", "tipo": "recusa", "fonte_esperada": ""}]
    resp = {"a": _resp(recusou=True, motivo="llm_recusou", ti=100, ts=10),
            "b": _resp(recusou=True, motivo="llm_recusou", ti=None, ts=None)}
    r, _ = _avaliar(resp, perguntas)
    assert r["tokens_entrada_total"] == 100 and r["tokens_entrada_medio"] == pytest.approx(100.0)
    assert r["chamadas_llm"] == 2


def test_taxas_none_quando_nao_ha_base():
    perguntas = [{"id": "r3", "pergunta": "p", "tipo": "recusa", "fonte_esperada": ""}]
    r, _ = _avaliar({"r3": _resp(recusou=True, motivo="llm_recusou")}, perguntas)
    assert r["n_validas"] == 0 and r["taxa_recusa_indevida"] is None
    assert r["taxa_citacao_correta"] is None and r["aproveitamento"] is None


def test_linha_de_erro_e_ordem_de_entrada():
    r, _ = _avaliar()
    assert [x["id"] for x in r["por_pergunta"]] == ["v1", "v2", "v3", "v4", "r1", "r2", "e1"]
    e1 = r["por_pergunta"][-1]
    assert e1["erro"] == "ErroLLM: cota excedida" and e1["recusou"] is None
    assert r["por_pergunta"][0]["erro"] is None


def test_pergunta_sem_fonte_ou_com_fonte_desconhecida_levanta_valueerror_com_o_id():
    sem_fonte = [{"id": "q77", "pergunta": "p", "tipo": "resposta_direta"}]
    with pytest.raises(ValueError, match="q77"):
        _avaliar({"q77": _resp()}, sem_fonte)
    desconhecida = [{"id": "q88", "pergunta": "p", "tipo": "resposta_direta", "fonte_esperada": "d-x, Art. 1"}]
    with pytest.raises(ValueError, match="q88"):
        _avaliar({"q88": _resp()}, desconhecida)


def test_resultado_e_serializavel_em_json_sem_mudar():
    r, _ = _avaliar(preco_entrada=0.1, preco_saida=0.4)
    assert json.loads(json.dumps(r)) == r
