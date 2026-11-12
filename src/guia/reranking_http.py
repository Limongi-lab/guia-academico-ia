from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

URL_RERANK = "https://api.novita.ai/openai/v1/rerank"
_STATUS_REPETIVEIS = {429, 500, 502, 503, 504}


class ErroReranker(Exception):
    pass


def _enviar_padrao(
    url: str,
    headers: dict[str, str],
    corpo: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    dados = json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(url, data=dados, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            corpo_resp = json.loads(resp.read().decode("utf-8"))
            return status, corpo_resp
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            texto = exc.read().decode("utf-8", errors="replace")
        except OSError:
            return status, {}
        try:
            parsed = json.loads(texto)
            if isinstance(parsed, dict):
                return status, parsed
            return status, {"_corpo": texto[:300]}
        except (json.JSONDecodeError, ValueError):
            return status, {"_corpo": texto[:300]}


def _extrair_mensagem(resp: Any, status: int) -> str:
    if not isinstance(resp, dict):
        return f"Status HTTP {status}"

    partes: list[str] = []

    reason = resp.get("reason")
    if isinstance(reason, str) and reason:
        partes.append(reason)

    err = resp.get("error")
    if isinstance(err, dict):
        msg = err.get("message")
        if isinstance(msg, str) and msg:
            partes.append(msg)
    else:
        msg = resp.get("message")
        if isinstance(msg, str) and msg:
            partes.append(msg)

    corpo_raw = resp.get("_corpo")
    if isinstance(corpo_raw, str) and corpo_raw:
        partes.append(corpo_raw)

    if not partes:
        return f"Status HTTP {status}"

    resultado = ": ".join(partes)
    return resultado[:300]


def criar_reranker_http(
    modelo: str,
    api_key: str | None = None,
    enviar: Callable[[str, dict[str, str], dict[str, Any]], tuple[int, dict[str, Any]]] | None = None,
    max_tentativas: int = 5,
    espera_inicial: float = 1.0,
    dormir: Callable[[float], None] = time.sleep,
    variavel_chave: str = "NOVITA_API_KEY",
    url: str = URL_RERANK,
) -> Callable[[str, Sequence[str]], list[float]]:
    chave = api_key if api_key is not None else os.environ.get(variavel_chave)
    if not chave:
        raise ErroReranker(
            f"Chave da API não informada. Defina a variável de ambiente '{variavel_chave}' "
            f"ou passe api_key explicitamente."
        )

    enviar_fn = enviar if enviar is not None else _enviar_padrao

    def _sanitizar(texto: str) -> str:
        if chave and chave in texto:
            return texto.replace(chave, "***")
        return texto

    def reranker(pergunta: str, textos: Sequence[str]) -> list[float]:
        if not textos:
            return []

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {chave}",
        }
        corpo = {
            "model": modelo,
            "query": pergunta,
            "documents": list(textos),
            "top_n": len(textos),
        }

        for tentativa in range(1, max_tentativas + 1):
            try:
                status, resp = enviar_fn(url, headers, corpo)
            except (OSError, TimeoutError) as exc:
                msg_erro = _sanitizar(str(exc))
                if tentativa < max_tentativas:
                    dormir(espera_inicial * (2 ** (tentativa - 1)))
                    continue
                raise ErroReranker(
                    f"Falha de rede após {max_tentativas} tentativas: {msg_erro}"
                ) from exc

            if status == 200:
                if not isinstance(resp, dict):
                    raise ErroReranker("Resposta 200 não é um dicionário JSON válido.")
                results = resp.get("results")
                if not isinstance(results, list) or len(results) != len(textos):
                    raise ErroReranker(
                        f"Resposta 200 inválida: esperava {len(textos)} resultados em 'results'."
                    )

                scores = [0.0] * len(textos)
                vistos: set[int] = set()
                for item in results:
                    if not isinstance(item, dict):
                        raise ErroReranker("Item em 'results' não é um dicionário.")
                    idx = item.get("index")
                    if not isinstance(idx, int) or isinstance(idx, bool):
                        raise ErroReranker("Campo 'index' ausente ou inválido no resultado.")
                    if idx < 0 or idx >= len(textos):
                        raise ErroReranker(f"Campo 'index' {idx} fora da faixa 0..{len(textos) - 1}.")
                    if idx in vistos:
                        raise ErroReranker(f"Campo 'index' {idx} duplicado nos resultados.")
                    vistos.add(idx)

                    score = item.get("relevance_score")
                    if score is None:
                        raise ErroReranker(f"Campo 'relevance_score' ausente para index {idx}.")
                    try:
                        scores[idx] = float(score)
                    except (ValueError, TypeError) as exc:
                        raise ErroReranker(f"Campo 'relevance_score' não numérico para index {idx}.") from exc

                return scores

            msg_erro = _sanitizar(_extrair_mensagem(resp, status))
            if status in _STATUS_REPETIVEIS:
                if tentativa < max_tentativas:
                    dormir(espera_inicial * (2 ** (tentativa - 1)))
                    continue
                raise ErroReranker(
                    f"Erro no reranker após {max_tentativas} tentativas (status {status}): {msg_erro}"
                )

            raise ErroReranker(f"Erro no reranker (status {status}): {msg_erro}")

        raise ErroReranker(f"Tentativas esgotadas para modelo '{modelo}'.")

    return reranker

