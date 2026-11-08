import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from guia.api import criar_app
from guia.llm_gemini import ErroLLM

PERGUNTA = "Qual a nota mínima para ser aprovado numa disciplina da UFU?"


def _resultado(**mudancas):
    base = {
        "resposta": "A nota mínima é 60 pontos [1].",
        "recusou": False,
        "motivo_recusa": None,
        "citacoes": [
            {"indice": 1, "citacao": "Art. 127, p. 33", "doc_id": "ufu-normas",
             "titulo_doc": "Normas Gerais da Graduação", "url": "http://exemplo.edu.br/normas.pdf"},
        ],
        "blocos": [
            {"indice": 1, "citacao": "Art. 127, p. 33", "texto": "Art. 127. Aprovação exige 60 pontos."},
            {"indice": 2, "citacao": "Art. 78, p. 22", "texto": "Art. 78. Frequência mínima de 75%."},
        ],
        "tokens_entrada": 700,
        "tokens_saida": 50,
        "latencia_s": 1.5,
        "recuperacao_s": 12.0,
        "total_s": 13.5,
    }
    base.update(mudancas)
    return base


class Responder:
    def __init__(self, resultado=None, erro=None):
        self.resultado = resultado if resultado is not None else _resultado()
        self.erro = erro
        self.chamadas = []

    def __call__(self, pergunta, instituicao):
        self.chamadas.append((pergunta, instituicao))
        if self.erro is not None:
            raise self.erro
        return self.resultado


class Relogio:
    def __init__(self):
        self.agora = 1000.0

    def __call__(self):
        return self.agora


def _cliente(responder=None, **kw):
    responder = responder or Responder()
    relogio = kw.pop("relogio", Relogio())
    app = criar_app(responder, relogio=relogio, **kw)
    return TestClient(app), responder, relogio


def _post(cliente, pergunta=PERGUNTA, instituicao="ufu", **kw):
    return cliente.post("/perguntar", json={"pergunta": pergunta, "instituicao": instituicao}, **kw)


def test_saude_responde_ok():
    cliente, _, _ = _cliente()
    r = cliente.get("/saude")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_perguntar_devolve_resposta_citacoes_tempos_e_tokens():
    cliente, _, _ = _cliente()
    r = _post(cliente)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["resposta"] == "A nota mínima é 60 pontos [1]."
    assert corpo["recusou"] is False and corpo["motivo_recusa"] is None
    assert corpo["citacoes"] == [{
        "indice": 1, "citacao": "Art. 127, p. 33", "titulo_doc": "Normas Gerais da Graduação",
        "url": "http://exemplo.edu.br/normas.pdf", "texto": "Art. 127. Aprovação exige 60 pontos.",
    }]
    assert corpo["tempos"] == {"recuperacao_s": 12.0, "geracao_s": 1.5, "total_s": 13.5}
    assert corpo["tokens"] == {"entrada": 700, "saida": 50}


def test_resposta_nao_expoe_campos_internos():
    cliente, _, _ = _cliente()
    corpo = _post(cliente).json()
    assert set(corpo) == {"resposta", "recusou", "motivo_recusa", "citacoes", "tempos", "tokens"}
    assert "doc_id" not in corpo["citacoes"][0]


def test_responder_recebe_pergunta_sem_espacos_e_a_instituicao():
    cliente, responder, _ = _cliente()
    _post(cliente, pergunta="  Qual a nota mínima?  ", instituicao="uniube")
    assert responder.chamadas == [("Qual a nota mínima?", "uniube")]


def test_citacao_sem_bloco_correspondente_vem_com_texto_vazio():
    resultado = _resultado(citacoes=[
        {"indice": 9, "citacao": "Art. 1, p. 1", "doc_id": "d", "titulo_doc": "t", "url": "u"},
    ])
    cliente, _, _ = _cliente(Responder(resultado))
    assert _post(cliente).json()["citacoes"][0]["texto"] == ""


def test_recusa_volta_com_status_200_e_motivo():
    resultado = _resultado(resposta="Não encontrei nos documentos.", recusou=True,
                           motivo_recusa="llm_recusou", citacoes=[], blocos=[])
    cliente, _, _ = _cliente(Responder(resultado))
    r = _post(cliente)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["recusou"] is True and corpo["motivo_recusa"] == "llm_recusou"
    assert corpo["citacoes"] == []


def test_tokens_ausentes_viram_null():
    resultado = _resultado(tokens_entrada=None, tokens_saida=None, latencia_s=0.0, total_s=0.2)
    cliente, _, _ = _cliente(Responder(resultado))
    assert _post(cliente).json()["tokens"] == {"entrada": None, "saida": None}


@pytest.mark.parametrize("corpo", [
    {"pergunta": "", "instituicao": "ufu"},
    {"pergunta": "    ", "instituicao": "ufu"},
    {"pergunta": "x" * 501, "instituicao": "ufu"},
    {"pergunta": PERGUNTA, "instituicao": "ufmg"},
    {"pergunta": PERGUNTA},
    {"instituicao": "ufu"},
])
def test_entrada_invalida_devolve_422_sem_chamar_o_responder(corpo):
    cliente, responder, _ = _cliente()
    r = cliente.post("/perguntar", json=corpo)
    assert r.status_code == 422
    assert responder.chamadas == []


def test_pergunta_de_500_caracteres_e_aceita():
    cliente, _, _ = _cliente()
    assert _post(cliente, pergunta="x" * 500).status_code == 200


def test_erro_do_llm_vira_502_sem_vazar_a_mensagem_original():
    cliente, _, _ = _cliente(Responder(erro=ErroLLM("falha com chave AIzaSECRETA123")))
    r = _post(cliente)
    assert r.status_code == 502
    assert "AIzaSECRETA123" not in r.text
    assert r.json() == {"detail": "Falha ao consultar o modelo de linguagem."}


def test_erro_inesperado_vira_500_sem_vazar_a_mensagem_original():
    cliente = TestClient(criar_app(Responder(erro=RuntimeError("senha do banco: guia")),
                                   relogio=Relogio()), raise_server_exceptions=False)
    r = _post(cliente)
    assert r.status_code == 500
    assert "senha do banco" not in r.text
    assert r.json() == {"detail": "Erro interno ao processar a pergunta."}


def test_limite_por_minuto_devolve_429_com_retry_after():
    cliente, responder, _ = _cliente(limite_por_minuto=2)
    assert _post(cliente).status_code == 200
    assert _post(cliente).status_code == 200
    r = _post(cliente)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert len(responder.chamadas) == 2


def test_saude_nao_conta_para_o_limite():
    cliente, _, _ = _cliente(limite_por_minuto=1)
    for _ in range(5):
        assert cliente.get("/saude").status_code == 200
    assert _post(cliente).status_code == 200


def test_janela_do_limite_desliza_com_o_tempo():
    cliente, _, relogio = _cliente(limite_por_minuto=1)
    assert _post(cliente).status_code == 200
    assert _post(cliente).status_code == 429
    relogio.agora += 30
    assert _post(cliente).status_code == 429
    relogio.agora += 31
    assert _post(cliente).status_code == 200


def test_limite_e_por_ip_quando_ha_proxy_confiavel():
    cliente, _, _ = _cliente(limite_por_minuto=1, confiar_proxy=True)
    assert _post(cliente, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
    assert _post(cliente, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 429
    assert _post(cliente, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 200


def test_x_forwarded_for_e_ignorado_sem_proxy_confiavel():
    cliente, _, _ = _cliente(limite_por_minuto=1)
    assert _post(cliente, headers={"X-Forwarded-For": "10.0.0.1"}).status_code == 200
    assert _post(cliente, headers={"X-Forwarded-For": "10.0.0.2"}).status_code == 429


def test_teto_diario_de_tokens_bloqueia_com_503_sem_chamar_o_responder():
    cliente, responder, _ = _cliente(teto_diario_tokens=1000, limite_por_minuto=100)
    assert _post(cliente).status_code == 200
    assert _post(cliente).status_code == 200
    r = _post(cliente)
    assert r.status_code == 503
    assert r.json() == {"detail": "Limite diário de uso atingido. Tente novamente amanhã."}
    assert len(responder.chamadas) == 2


def test_teto_diario_zera_no_dia_seguinte():
    dia = ["2026-11-08"]
    cliente, _, _ = _cliente(teto_diario_tokens=700, limite_por_minuto=100, dia_atual=lambda: dia[0])
    assert _post(cliente).status_code == 200
    assert _post(cliente).status_code == 503
    dia[0] = "2026-11-09"
    assert _post(cliente).status_code == 200


def test_tokens_ausentes_nao_consomem_o_teto():
    resultado = _resultado(tokens_entrada=None, tokens_saida=None)
    cliente, _, _ = _cliente(Responder(resultado), teto_diario_tokens=1, limite_por_minuto=100)
    for _ in range(3):
        assert _post(cliente).status_code == 200


def test_chamada_que_falha_nao_consome_o_teto():
    responder = Responder(erro=ErroLLM("x"))
    cliente, _, _ = _cliente(responder, teto_diario_tokens=1, limite_por_minuto=100)
    for _ in range(3):
        assert _post(cliente).status_code == 502


def test_cors_permite_origem_configurada_e_bloqueia_as_outras():
    cliente, _, _ = _cliente(origens_cors=["http://localhost:5173"])
    ok = _post(cliente, headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    nao = _post(cliente, headers={"Origin": "http://malicioso.example"})
    assert "access-control-allow-origin" not in nao.headers


def test_cors_responde_ao_preflight_da_origem_permitida():
    cliente, _, _ = _cliente(origens_cors=["http://localhost:5173"])
    r = cliente.options("/perguntar", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_sem_origens_configuradas_nao_ha_cabecalho_cors():
    cliente, _, _ = _cliente()
    r = _post(cliente, headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in r.headers


def test_responder_nunca_roda_em_paralelo():
    estado = {"atual": 0, "maximo": 0}
    trava = threading.Lock()

    def lento(pergunta, instituicao):
        with trava:
            estado["atual"] += 1
            estado["maximo"] = max(estado["maximo"], estado["atual"])
        time.sleep(0.05)
        with trava:
            estado["atual"] -= 1
        return _resultado()

    cliente, _, _ = _cliente(lento, limite_por_minuto=100)
    codigos = []

    def chamar():
        codigos.append(_post(cliente).status_code)

    threads = [threading.Thread(target=chamar) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codigos == [200] * 4
    assert estado["maximo"] == 1


def test_log_registra_custo_e_latencia_sem_a_pergunta(caplog):
    cliente, _, _ = _cliente()
    with caplog.at_level(logging.INFO, logger="guia.api"):
        _post(cliente)
    registros = [r for r in caplog.records if r.name == "guia.api" and hasattr(r, "tokens_entrada")]
    assert len(registros) == 1
    r = registros[0]
    assert (r.instituicao, r.recusou, r.tokens_entrada, r.tokens_saida) == ("ufu", False, 700, 50)
    assert (r.recuperacao_s, r.geracao_s, r.total_s) == (12.0, 1.5, 13.5)
    for registro in caplog.records:
        assert "nota mínima" not in registro.getMessage()
        assert "nota mínima" not in str(registro.__dict__)
