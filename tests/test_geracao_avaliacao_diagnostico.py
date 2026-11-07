import json

from guia.geracao_avaliacao import avaliar_geracao

IDS = {"d-a", "d-b"}


def _cit(doc, citacao):
    return {"indice": 1, "citacao": citacao, "doc_id": doc, "titulo_doc": "t", "url": "u"}


def _bloco(indice, citacao):
    return {"indice": indice, "citacao": citacao, "doc_id": "d-a", "titulo_doc": "t", "url": "u", "texto": "x"}


PERGUNTAS = [
    {"id": "v1", "pergunta": "p1", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 41"},
    {"id": "v2", "pergunta": "p2", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 50"},
    {"id": "r1", "pergunta": "p3", "tipo": "recusa", "fonte_esperada": ""},
    {"id": "e1", "pergunta": "p4", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 70"},
    {"id": "m1", "pergunta": "p5", "tipo": "resposta_direta", "fonte_esperada": "d-a, Art. 60"},
]

RESPOSTAS = {
    "v1": {
        "recusou": False, "motivo_recusa": None,
        "citacoes": [_cit("d-a", "Art. 41, p. 12"), _cit("d-a", "Art. 42, p. 13")],
        "resposta_bruta": "Vale o Art. 41 [1] e o Art. 42 [2].",
        "blocos": [_bloco(1, "Art. 41, p. 12"), _bloco(2, "Art. 42, p. 13"), _bloco(3, "Art. 9, p. 2")],
        "recuperados_ids": ["d-a/art-41#1", "d-a/art-42#1", "d-a/art-9#1"],
        "tokens_entrada": 100, "tokens_saida": 20, "latencia_s": 1.0,
    },
    "v2": {
        "recusou": True, "motivo_recusa": "llm_recusou", "citacoes": [],
        "resposta_bruta": "NAO_ENCONTRADO",
        "blocos": [_bloco(1, "Art. 51, p. 3")],
        "recuperados_ids": ["d-a/art-51#1"],
        "tokens_entrada": 50, "tokens_saida": 5, "latencia_s": 2.0,
    },
    "r1": {
        "recusou": False, "motivo_recusa": None,
        "citacoes": [_cit("d-a", "Art. 9, p. 2")],
        "resposta_bruta": "A fórmula é X [1].",
        "blocos": [_bloco(1, "Art. 9, p. 2")],
        "recuperados_ids": ["d-a/art-9#1"],
        "tokens_entrada": 60, "tokens_saida": 6, "latencia_s": 1.0,
    },
    "e1": {"erro": "ErroLLM: cota excedida"},
    "m1": {
        "recusou": True, "motivo_recusa": "sem_contexto", "citacoes": [],
        "tokens_entrada": None, "tokens_saida": None, "latencia_s": 0.0,
    },
}


def _linhas():
    r = avaliar_geracao(PERGUNTAS, lambda p: RESPOSTAS[p["id"]], IDS)
    return {x["id"]: x for x in r["por_pergunta"]}, r


def test_linha_guarda_a_resposta_bruta_do_llm():
    linhas, _ = _linhas()
    assert linhas["v1"]["resposta_bruta"] == "Vale o Art. 41 [1] e o Art. 42 [2]."
    assert linhas["v2"]["resposta_bruta"] == "NAO_ENCONTRADO"
    assert linhas["r1"]["resposta_bruta"] == "A fórmula é X [1]."


def test_linha_guarda_as_citacoes_da_resposta_em_ordem():
    linhas, _ = _linhas()
    assert linhas["v1"]["citacoes"] == ["Art. 41, p. 12", "Art. 42, p. 13"]
    assert linhas["v2"]["citacoes"] == []


def test_linha_guarda_o_que_entrou_no_contexto_em_ordem():
    linhas, _ = _linhas()
    assert linhas["v1"]["contexto"] == ["Art. 41, p. 12", "Art. 42, p. 13", "Art. 9, p. 2"]
    assert linhas["v2"]["contexto"] == ["Art. 51, p. 3"]


def test_linha_guarda_os_ids_recuperados_em_ordem():
    linhas, _ = _linhas()
    assert linhas["v1"]["recuperados_ids"] == ["d-a/art-41#1", "d-a/art-42#1", "d-a/art-9#1"]
    assert linhas["r1"]["recuperados_ids"] == ["d-a/art-9#1"]


def test_resposta_sem_os_campos_novos_vira_none_e_listas_vazias():
    linhas, _ = _linhas()
    m1 = linhas["m1"]
    assert m1["resposta_bruta"] is None and m1["recuperados_ids"] is None
    assert m1["contexto"] == [] and m1["citacoes"] == []


def test_linha_de_erro_tem_os_campos_novos_vazios():
    linhas, _ = _linhas()
    e1 = linhas["e1"]
    assert e1["erro"] == "ErroLLM: cota excedida"
    assert e1["resposta_bruta"] is None and e1["recuperados_ids"] is None
    assert e1["contexto"] == [] and e1["citacoes"] == []


def test_campos_antigos_continuam_iguais():
    linhas, r = _linhas()
    assert linhas["v1"]["recusou"] is False and linhas["v1"]["citacao_ok"] is True
    assert linhas["v2"]["recusou"] is True and linhas["v2"]["motivo_recusa"] == "llm_recusou"
    assert linhas["v1"]["tokens_entrada"] == 100 and linhas["v1"]["latencia_s"] == 1.0
    assert r["n_recusa_indevida"] == 2 and r["n_citacao_correta"] == 1


def test_resultado_continua_serializavel_em_json_sem_mudar():
    _, r = _linhas()
    assert json.loads(json.dumps(r)) == r
