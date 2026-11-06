"""Adaptador do Gemini (REST) para o contrato llm(system, user) -> dict da camada de geração.

Contrato (guia.llm_gemini)
  class ErroLLM(Exception)
  URL_BASE = "https://generativelanguage.googleapis.com/v1beta"
  criar_llm_gemini(modelo, api_key=None, enviar=None, max_tentativas=5, espera_inicial=2.0,
                   dormir=time.sleep, temperatura=0.0, max_tokens_saida=1024,
                   variavel_chave="GEMINI_API_KEY") -> llm
    - api_key None: lê os.environ[variavel_chave]; ausente ou vazia => ErroLLM JÁ NA CRIAÇÃO,
      com o NOME da variável na mensagem (nunca valor de chave).
    - `enviar(url, headers, corpo) -> (status:int, json:dict)`: transporte injetado (o padrão
      é um transporte HTTP fino, não testado aqui). Pode levantar OSError/TimeoutError.
    - llm(system, user) faz POST em f"{URL_BASE}/models/{modelo}:generateContent" com:
        headers {"Content-Type": "application/json", "x-goog-api-key": <chave>}
        corpo   {"systemInstruction": {"parts": [{"text": system}]},
                 "contents": [{"role": "user", "parts": [{"text": user}]}],
                 "generationConfig": {"temperature": temperatura, "maxOutputTokens": max_tokens_saida}}
      A chave aparece SOMENTE no cabeçalho (nunca na URL nem no corpo).
    - devolve {"texto", "tokens_entrada", "tokens_saida"}: texto = concatenação das partes de
      texto do 1º candidato, ignorando partes com "thought": true; tokens_entrada =
      usageMetadata.promptTokenCount; tokens_saida = candidatesTokenCount + thoughtsTokenCount
      (ausente = 0), ambos None se não houver usageMetadata.
    - status 429, 500, 502, 503, 504 e exceções OSError/TimeoutError do transporte: nova
      tentativa, até max_tentativas no total; antes da n-ésima repetição dorme
      espera_inicial * 2**(n-1) (sem dormir depois da última tentativa); esgotadas => ErroLLM
      com o último status (ou erro) na mensagem.
    - outro status != 200 (400, 401, 403, 404...): ErroLLM na hora, sem repetir, com o status e
      a mensagem de erro da API.
    - status 200 sem texto (sem candidatos, ou candidato sem partes de texto, p.ex. bloqueio de
      segurança): ErroLLM na hora, citando o blockReason/finishReason; sem repetir.
    - NENHUMA mensagem de ErroLLM pode conter o valor da chave (troque por "***").
"""
import json

import pytest

from guia.llm_gemini import URL_BASE, ErroLLM, criar_llm_gemini

CHAVE = "chave-secreta-de-teste-123"


def _ok(texto="Resposta [1].", entrada=100, saida=20, extra=None, partes=None):
    usage = {"promptTokenCount": entrada, "candidatesTokenCount": saida, **(extra or {})}
    partes = partes if partes is not None else [{"text": texto}]
    return 200, {"candidates": [{"content": {"parts": partes}, "finishReason": "STOP"}],
                 "usageMetadata": usage}


class Transporte:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __call__(self, url, headers, corpo):
        self.chamadas.append((url, dict(headers), corpo))
        r = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(r, Exception):
            raise r
        return r


def _llm(transporte, **kw):
    pausas = []
    llm = criar_llm_gemini("modelo-x", api_key=CHAVE, enviar=transporte, dormir=pausas.append, **kw)
    return llm, pausas


def test_monta_url_cabecalhos_e_corpo_com_a_chave_so_no_cabecalho():
    t = Transporte(_ok())
    llm, _ = _llm(t)
    llm("regras do sistema", "pergunta do usuário")
    url, headers, corpo = t.chamadas[0]
    assert url == f"{URL_BASE}/models/modelo-x:generateContent"
    assert headers["x-goog-api-key"] == CHAVE and headers["Content-Type"] == "application/json"
    assert CHAVE not in url and CHAVE not in json.dumps(corpo)
    assert corpo["systemInstruction"] == {"parts": [{"text": "regras do sistema"}]}
    assert corpo["contents"] == [{"role": "user", "parts": [{"text": "pergunta do usuário"}]}]
    assert corpo["generationConfig"] == {"temperature": 0.0, "maxOutputTokens": 1024}


def test_parametros_de_geracao_sao_configuraveis():
    t = Transporte(_ok())
    llm, _ = _llm(t, temperatura=0.3, max_tokens_saida=256)
    llm("s", "u")
    assert t.chamadas[0][2]["generationConfig"] == {"temperature": 0.3, "maxOutputTokens": 256}


def test_devolve_texto_e_tokens():
    llm, _ = _llm(Transporte(_ok("Vale [1].", 150, 30)))
    assert llm("s", "u") == {"texto": "Vale [1].", "tokens_entrada": 150, "tokens_saida": 30}


def test_tokens_de_raciocinio_contam_como_saida():
    llm, _ = _llm(Transporte(_ok("x", 10, 30, extra={"thoughtsTokenCount": 50})))
    assert llm("s", "u")["tokens_saida"] == 80


def test_junta_partes_de_texto_e_ignora_as_de_raciocinio():
    partes = [{"text": "A "}, {"text": "raciocínio interno", "thought": True}, {"text": "B"}]
    llm, _ = _llm(Transporte(_ok(partes=partes)))
    assert llm("s", "u")["texto"] == "A B"


def test_sem_usage_metadata_os_tokens_sao_none():
    resp = (200, {"candidates": [{"content": {"parts": [{"text": "ok [1]"}]}}]})
    llm, _ = _llm(Transporte(resp))
    r = llm("s", "u")
    assert r["texto"] == "ok [1]" and r["tokens_entrada"] is None and r["tokens_saida"] is None


def test_chave_vem_do_ambiente(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", CHAVE)
    t = Transporte(_ok())
    llm = criar_llm_gemini("m", enviar=t, dormir=lambda s: None)
    llm("s", "u")
    assert t.chamadas[0][1]["x-goog-api-key"] == CHAVE


def test_chave_ausente_falha_na_criacao_citando_so_o_nome_da_variavel(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ErroLLM, match="GEMINI_API_KEY"):
        criar_llm_gemini("m", enviar=Transporte(_ok()))
    monkeypatch.setenv("OUTRA_CHAVE", "")
    with pytest.raises(ErroLLM, match="OUTRA_CHAVE"):
        criar_llm_gemini("m", enviar=Transporte(_ok()), variavel_chave="OUTRA_CHAVE")


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_status_temporarios_sao_repetidos(status):
    t = Transporte((status, {"error": {"message": "tente depois"}}), _ok("depois [1]"))
    llm, pausas = _llm(t)
    assert llm("s", "u")["texto"] == "depois [1]"
    assert len(t.chamadas) == 2 and pausas == [2.0]


def test_espera_dobra_a_cada_repeticao():
    t = Transporte((429, {}), (429, {}), _ok())
    llm, pausas = _llm(t, espera_inicial=2.0)
    llm("s", "u")
    assert len(t.chamadas) == 3 and pausas == [2.0, 4.0]


def test_esgotadas_as_tentativas_levanta_erro_sem_dormir_depois_da_ultima():
    t = Transporte((503, {"error": {"message": "indisponível"}}))
    llm, pausas = _llm(t, max_tentativas=3)
    with pytest.raises(ErroLLM, match="503"):
        llm("s", "u")
    assert len(t.chamadas) == 3 and pausas == [2.0, 4.0]


def test_erro_do_cliente_nao_e_repetido():
    t = Transporte((400, {"error": {"message": "parâmetro inválido"}}))
    llm, pausas = _llm(t)
    with pytest.raises(ErroLLM) as erro:
        llm("s", "u")
    assert "400" in str(erro.value) and "parâmetro inválido" in str(erro.value)
    assert len(t.chamadas) == 1 and pausas == []


def test_mensagem_de_erro_nunca_traz_a_chave():
    t = Transporte((401, {"error": {"message": f"API key {CHAVE} não é válida"}}))
    llm, _ = _llm(t)
    with pytest.raises(ErroLLM) as erro:
        llm("s", "u")
    assert CHAVE not in str(erro.value)


@pytest.mark.parametrize("resposta", [
    (200, {"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}),
    (200, {"candidates": [{"finishReason": "SAFETY"}]}),
])
def test_resposta_sem_texto_levanta_erro_citando_o_motivo_sem_repetir(resposta):
    t = Transporte(resposta)
    llm, pausas = _llm(t)
    with pytest.raises(ErroLLM, match="SAFETY"):
        llm("s", "u")
    assert len(t.chamadas) == 1 and pausas == []


def test_falha_de_rede_e_repetida():
    t = Transporte(TimeoutError("tempo esgotado"), _ok("voltou [1]"))
    llm, pausas = _llm(t)
    assert llm("s", "u")["texto"] == "voltou [1]"
    assert pausas == [2.0]


def test_falha_de_rede_esgotada_nao_vaza_a_chave():
    t = Transporte(OSError(f"conexão recusada para chave {CHAVE}"))
    llm, _ = _llm(t, max_tentativas=2)
    with pytest.raises(ErroLLM) as erro:
        llm("s", "u")
    assert CHAVE not in str(erro.value)
    assert len(t.chamadas) == 2
