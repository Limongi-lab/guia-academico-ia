import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from guia.reranking_http import ErroReranker, criar_reranker_http

CHAVE = "chave-falsa-do-teste-123"
TEXTOS = ["texto a", "texto b"]
SALDO = {"code": 403, "reason": "NOT_ENOUGH_BALANCE", "message": "not enough balance", "metadata": {}}


class _Servidor:
    def __init__(self, status, corpo, tipo="application/json"):
        self.pedidos = []
        pedidos = self.pedidos
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                tamanho = int(self.headers.get("Content-Length", 0))
                pedidos.append((self.path, dict(self.headers), json.loads(self.rfile.read(tamanho))))
                self.send_response(status)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(dados)))
                self.end_headers()
                self.wfile.write(dados)

            def log_message(self, *args):
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/rerank"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.httpd.shutdown()
        self.httpd.server_close()


def _reranker(url, **kw):
    return criar_reranker_http("baai/bge-reranker-v2-m3", api_key=CHAVE, url=url, **kw)


def test_mensagem_de_nivel_superior_do_servico_aparece_no_erro():
    reranker = criar_reranker_http("m", api_key=CHAVE, enviar=lambda u, h, c: (403, SALDO), dormir=lambda s: None)
    with pytest.raises(ErroReranker) as exc:
        reranker("p", TEXTOS)
    erro = str(exc.value)
    assert "403" in erro and "not enough balance" in erro and "NOT_ENOUGH_BALANCE" in erro


def test_transporte_real_traz_a_mensagem_do_corpo_json_de_erro():
    with _Servidor(403, SALDO) as s:
        with pytest.raises(ErroReranker) as exc:
            _reranker(s.url, dormir=lambda x: None)("p", TEXTOS)
    assert "not enough balance" in str(exc.value) and "403" in str(exc.value)


def test_transporte_real_traz_um_trecho_de_corpo_que_nao_e_json():
    with _Servidor(403, b"<html>Access denied by firewall</html>", tipo="text/html") as s:
        with pytest.raises(ErroReranker) as exc:
            _reranker(s.url, dormir=lambda x: None)("p", TEXTOS)
    assert "Access denied by firewall" in str(exc.value)


def test_corpo_nao_json_e_truncado_e_sem_a_chave():
    corpo = (f"{CHAVE} " + "x" * 5000).encode("utf-8")
    with _Servidor(403, corpo, tipo="text/plain") as s:
        with pytest.raises(ErroReranker) as exc:
            _reranker(s.url, dormir=lambda x: None)("p", TEXTOS)
    assert CHAVE not in str(exc.value) and len(str(exc.value)) < 600


def test_transporte_real_com_corpo_vazio_cai_na_mensagem_com_o_status():
    with _Servidor(403, b"", tipo="text/plain") as s:
        with pytest.raises(ErroReranker) as exc:
            _reranker(s.url, dormir=lambda x: None)("p", TEXTOS)
    assert "403" in str(exc.value)


def test_transporte_real_envia_os_cabecalhos_e_o_corpo_e_le_os_scores():
    resposta = {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]}
    with _Servidor(200, resposta) as s:
        scores = _reranker(s.url)("Qual a nota?", TEXTOS)
    caminho, cabecalhos, corpo = s.pedidos[0]
    assert scores == [0.2, 0.9]
    assert caminho == "/rerank"
    assert cabecalhos["Authorization"] == f"Bearer {CHAVE}"
    assert corpo == {"model": "baai/bge-reranker-v2-m3", "query": "Qual a nota?",
                     "documents": TEXTOS, "top_n": 2}


def test_transporte_real_repete_503_e_depois_falha_com_a_mensagem():
    with _Servidor(503, {"message": "servico indisponivel"}) as s:
        dormidas = []
        with pytest.raises(ErroReranker) as exc:
            _reranker(s.url, max_tentativas=2, dormir=dormidas.append)("p", TEXTOS)
    assert len(s.pedidos) == 2 and len(dormidas) == 1
    assert "servico indisponivel" in str(exc.value)
