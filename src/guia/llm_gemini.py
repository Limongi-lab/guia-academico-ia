"""Adaptador do Gemini (REST) para o contrato llm(system, user) -> dict.

Permite consultar modelos do Google Gemini via API REST usando HTTP direto
(urllib.request), sem dependência de bibliotecas de terceiros de LLM.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

# ---------------------------------------------------------------------------
# Constantes públicas
# ---------------------------------------------------------------------------

URL_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
_STATUS_REPETIVEIS: set[int] = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------

class ErroLLM(Exception):
    """Erro levantado durante a chamada ou processamento do LLM."""


# ---------------------------------------------------------------------------
# Transporte HTTP padrão
# ---------------------------------------------------------------------------

def _enviar_padrao(
    url: str,
    headers: dict[str, str],
    corpo: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    """Transporte HTTP padrão usando urllib.request com timeout de 60s.

    Devolve (status, json), capturando HTTPError para retornar o corpo da resposta.
    """
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
            corpo_resp = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            corpo_resp = {}
        return status, corpo_resp


# ---------------------------------------------------------------------------
# Fábrica do LLM Gemini
# ---------------------------------------------------------------------------

def criar_llm_gemini(
    modelo: str,
    api_key: str | None = None,
    enviar: Callable[[str, dict[str, str], dict[str, Any]], tuple[int, dict[str, Any]]] | None = None,
    max_tentativas: int = 5,
    espera_inicial: float = 2.0,
    dormir: Callable[[float], None] = time.sleep,
    temperatura: float = 0.0,
    max_tokens_saida: int = 1024,
    variavel_chave: str = "GEMINI_API_KEY",
) -> Callable[[str, str], dict[str, Any]]:
    """Cria um adaptador para o Gemini no contrato llm(system, user) -> dict.

    Parâmetros:
      modelo: Identificador do modelo (ex: 'gemini-2.5-flash').
      api_key: Chave de API opcional; se None, lê a variável de ambiente variavel_chave.
      enviar: Função de transporte (url, headers, corpo) -> (status, json).
      max_tentativas: Quantidade máxima de tentativas para erros temporários.
      espera_inicial: Tempo base em segundos para recuo exponencial.
      dormir: Função de pausa entre repetições (padrão: time.sleep).
      temperatura: Temperatura de amostragem na geração.
      max_tokens_saida: Limite máximo de tokens de saída.
      variavel_chave: Nome da variável de ambiente com a chave (padrão: GEMINI_API_KEY).
    """
    chave = api_key if api_key is not None else os.environ.get(variavel_chave)
    if not chave:
        raise ErroLLM(
            f"Chave da API não informada. Defina a variável de ambiente '{variavel_chave}' "
            f"ou passe api_key explicitamente."
        )

    enviar_fn = enviar if enviar is not None else _enviar_padrao
    url = f"{URL_BASE}/models/{modelo}:generateContent"

    def _sanitizar(texto: str) -> str:
        """Substitui a chave de API por asteriscos para evitar vazamento."""
        if chave and chave in texto:
            return texto.replace(chave, "***")
        return texto

    def llm(system: str, user: str) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": chave,
        }
        corpo = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperatura,
                "maxOutputTokens": max_tokens_saida,
            },
        }

        for tentativa in range(1, max_tentativas + 1):
            try:
                status, resp = enviar_fn(url, headers, corpo)
            except (OSError, TimeoutError) as exc:
                msg_erro = _sanitizar(str(exc))
                if tentativa < max_tentativas:
                    dormir(espera_inicial * (2 ** (tentativa - 1)))
                    continue
                raise ErroLLM(
                    f"Falha de rede após {max_tentativas} tentativas: {msg_erro}"
                ) from exc

            if status == 200:
                candidates = resp.get("candidates") or []
                if not candidates:
                    prompt_feedback = resp.get("promptFeedback") or {}
                    block_reason = prompt_feedback.get("blockReason") or "sem candidatos"
                    raise ErroLLM(f"Resposta 200 sem candidatos ({block_reason})")

                primeiro = candidates[0]
                content = primeiro.get("content") or {}
                partes = content.get("parts") or []

                partes_texto = [
                    p.get("text", "")
                    for p in partes
                    if not p.get("thought")
                ]
                texto = "".join(partes_texto)
                if not texto:
                    finish_reason = primeiro.get("finishReason") or "sem partes de texto"
                    raise ErroLLM(f"Resposta 200 sem texto no candidato ({finish_reason})")

                usage = resp.get("usageMetadata")
                if usage is not None:
                    tokens_entrada = usage.get("promptTokenCount")
                    tokens_saida = (
                        (usage.get("candidatesTokenCount") or 0)
                        + (usage.get("thoughtsTokenCount") or 0)
                    )
                else:
                    tokens_entrada = None
                    tokens_saida = None

                return {
                    "texto": texto,
                    "tokens_entrada": tokens_entrada,
                    "tokens_saida": tokens_saida,
                }

            if status in _STATUS_REPETIVEIS:
                msg_erro = _sanitizar(
                    resp.get("error", {}).get("message")
                    or f"Status HTTP {status}"
                )
                if tentativa < max_tentativas:
                    dormir(espera_inicial * (2 ** (tentativa - 1)))
                    continue
                raise ErroLLM(
                    f"Erro na API Gemini após {max_tentativas} tentativas (status {status}): {msg_erro}"
                )

            # Outro status de erro (400, 401, 403, 404...): sem repetição
            msg_erro = _sanitizar(
                resp.get("error", {}).get("message")
                or f"Status HTTP {status}"
            )
            raise ErroLLM(f"Erro na API Gemini (status {status}): {msg_erro}")

        raise ErroLLM(f"Tentativas esgotadas para modelo '{modelo}'.")

    return llm
