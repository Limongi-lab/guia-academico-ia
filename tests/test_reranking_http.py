import pytest

from guia.reranking_http import URL_RERANK, ErroReranker, criar_reranker_http

CHAVE = "chave-falsa-do-teste-123"
MODELO = "baai/bge-reranker-v2-m3"
TEXTOS = ["texto a", "texto b", "texto c"]


def _ok(scores, ordem=None):
    ordem = ordem if ordem is not None else range(len(scores))
    return 200, {
        "results": [{"index": i, "relevance_score": scores[i], "document": {"text": "x"}} for i in ordem],
        "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
    }


class Transporte:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def __call__(self, url, headers, corpo):
        self.chamadas.append((url, headers, corpo))
        resposta = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def _reranker(*respostas, **kw):
    transporte = Transporte(*respostas)
    dormidas = []
    kw.setdefault("dormir", dormidas.append)
    kw.setdefault("api_key", CHAVE)
    return criar_reranker_http(MODELO, enviar=transporte, **kw), transporte, dormidas


def test_monta_url_cabecalhos_e_corpo_com_a_chave_so_no_cabecalho():
    reranker, transporte, _ = _reranker(_ok([0.1, 0.2, 0.3]))
    reranker("Qual a nota mínima?", TEXTOS)
    url, headers, corpo = transporte.chamadas[0]
    assert url == URL_RERANK == "https://api.novita.ai/openai/v1/rerank"
    assert headers["Authorization"] == f"Bearer {CHAVE}"
    assert headers["Content-Type"] == "application/json"
    assert corpo == {"model": MODELO, "query": "Qual a nota mínima?", "documents": TEXTOS, "top_n": 3}
    assert CHAVE not in str(corpo) and CHAVE not in url


def test_devolve_os_scores_na_ordem_dos_textos_mesmo_com_resposta_ordenada_por_score():
    reranker, _, _ = _reranker(_ok([0.2, 0.9, 0.5], ordem=[1, 2, 0]))
    assert reranker("p", TEXTOS) == [0.2, 0.9, 0.5]


def test_devolve_floats():
    reranker, _, _ = _reranker(_ok([1, 0, 1]))
    resultado = reranker("p", TEXTOS)
    assert resultado == [1.0, 0.0, 1.0] and all(isinstance(x, float) for x in resultado)


def test_lista_vazia_nao_chama_o_servico():
    reranker, transporte, _ = _reranker(_ok([]))
    assert reranker("p", []) == []
    assert transporte.chamadas == []


def test_uma_unica_chamada_por_rerank():
    reranker, transporte, _ = _reranker(_ok([0.1, 0.2, 0.3]))
    reranker("p", TEXTOS)
    assert len(transporte.chamadas) == 1


def test_modelo_e_url_sao_configuraveis():
    transporte = Transporte(_ok([0.5]))
    reranker = criar_reranker_http("outro/modelo", api_key=CHAVE, enviar=transporte,
                                   url="https://exemplo.test/rerank")
    reranker("p", ["a"])
    url, _, corpo = transporte.chamadas[0]
    assert url == "https://exemplo.test/rerank" and corpo["model"] == "outro/modelo"


def test_chave_vem_do_ambiente(monkeypatch):
    monkeypatch.setenv("NOVITA_API_KEY", "chave-do-ambiente")
    transporte = Transporte(_ok([0.5]))
    criar_reranker_http(MODELO, enviar=transporte)("p", ["a"])
    assert transporte.chamadas[0][1]["Authorization"] == "Bearer chave-do-ambiente"


def test_variavel_da_chave_e_configuravel(monkeypatch):
    monkeypatch.delenv("NOVITA_API_KEY", raising=False)
    monkeypatch.setenv("OUTRA_CHAVE", "valor-outra")
    transporte = Transporte(_ok([0.5]))
    criar_reranker_http(MODELO, enviar=transporte, variavel_chave="OUTRA_CHAVE")("p", ["a"])
    assert transporte.chamadas[0][1]["Authorization"] == "Bearer valor-outra"


def test_chave_ausente_falha_na_criacao_citando_so_o_nome_da_variavel(monkeypatch):
    monkeypatch.delenv("NOVITA_API_KEY", raising=False)
    with pytest.raises(ErroReranker) as exc:
        criar_reranker_http(MODELO, enviar=Transporte(_ok([0.5])))
    assert "NOVITA_API_KEY" in str(exc.value)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_status_temporarios_sao_repetidos(status):
    reranker, transporte, _ = _reranker((status, {}), _ok([0.1, 0.2, 0.3]))
    assert reranker("p", TEXTOS) == [0.1, 0.2, 0.3]
    assert len(transporte.chamadas) == 2


def test_espera_dobra_a_cada_repeticao():
    reranker, _, dormidas = _reranker((503, {}), (503, {}), (503, {}), _ok([0.1, 0.2, 0.3]),
                                      espera_inicial=1.5)
    reranker("p", TEXTOS)
    assert dormidas == [1.5, 3.0, 6.0]


def test_esgotadas_as_tentativas_levanta_erro_sem_dormir_depois_da_ultima():
    reranker, transporte, dormidas = _reranker((503, {}), max_tentativas=3, espera_inicial=1.0)
    with pytest.raises(ErroReranker, match="503"):
        reranker("p", TEXTOS)
    assert len(transporte.chamadas) == 3 and dormidas == [1.0, 2.0]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_erro_do_cliente_nao_e_repetido(status):
    reranker, transporte, dormidas = _reranker((status, {"error": {"message": "pedido invalido"}}))
    with pytest.raises(ErroReranker, match=str(status)):
        reranker("p", TEXTOS)
    assert len(transporte.chamadas) == 1 and dormidas == []


def test_mensagem_de_erro_do_servico_aparece_sem_a_chave():
    resposta = (401, {"error": {"message": f"chave {CHAVE} invalida"}})
    reranker, _, _ = _reranker(resposta)
    with pytest.raises(ErroReranker) as exc:
        reranker("p", TEXTOS)
    assert CHAVE not in str(exc.value) and "***" in str(exc.value)


def test_falha_de_rede_e_repetida():
    reranker, transporte, _ = _reranker(OSError("rede caiu"), _ok([0.1, 0.2, 0.3]))
    assert reranker("p", TEXTOS) == [0.1, 0.2, 0.3]
    assert len(transporte.chamadas) == 2


def test_falha_de_rede_esgotada_nao_vaza_a_chave():
    reranker, _, _ = _reranker(OSError(f"conexao com {CHAVE} falhou"), max_tentativas=2)
    with pytest.raises(ErroReranker) as exc:
        reranker("p", TEXTOS)
    assert CHAVE not in str(exc.value)


def test_falha_de_rede_esgotada_nao_dorme_depois_da_ultima_tentativa():
    reranker, transporte, dormidas = _reranker(OSError("rede caiu"), max_tentativas=3, espera_inicial=1.0)
    with pytest.raises(ErroReranker):
        reranker("p", TEXTOS)
    assert len(transporte.chamadas) == 3 and dormidas == [1.0, 2.0]


def test_timeout_tambem_e_repetido():
    reranker, transporte, _ = _reranker(TimeoutError("lento"), _ok([0.1, 0.2, 0.3]))
    assert reranker("p", TEXTOS) == [0.1, 0.2, 0.3]
    assert len(transporte.chamadas) == 2


@pytest.mark.parametrize("corpo", [
    {},
    {"results": []},
    {"results": [{"index": 0, "relevance_score": 0.5}]},
    {"results": [{"index": 0, "relevance_score": 0.5}, {"index": 0, "relevance_score": 0.4},
                 {"index": 2, "relevance_score": 0.3}]},
    {"results": [{"index": 0, "relevance_score": 0.5}, {"index": 1, "relevance_score": 0.4},
                 {"index": 7, "relevance_score": 0.3}]},
    {"results": [{"index": 0}, {"index": 1}, {"index": 2}]},
])
def test_resposta_malformada_ou_incompleta_levanta_erro_sem_repetir(corpo):
    reranker, transporte, _ = _reranker((200, corpo))
    with pytest.raises(ErroReranker):
        reranker("p", TEXTOS)
    assert len(transporte.chamadas) == 1


def test_serve_como_reranker_do_pipeline_de_busca():
    reranker, _, _ = _reranker(_ok([0.3, 0.8, 0.1]))
    scores = reranker("p", TEXTOS)
    ordem = sorted(range(len(TEXTOS)), key=lambda i: -scores[i])
    assert ordem == [1, 0, 2]
