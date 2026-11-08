from __future__ import annotations

import logging
import math
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from guia.llm_gemini import ErroLLM

logger = logging.getLogger("guia.api")


class PerguntaEntrada(BaseModel):
    pergunta: str = Field(..., min_length=1, max_length=500)
    instituicao: Literal["ufu", "uniube"]

    @field_validator("pergunta", mode="before")
    @classmethod
    def validar_pergunta(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
        return v


def criar_app(
    responder_fn: Callable[[str, str], dict[str, Any]],
    *,
    origens_cors: Sequence[str] = (),
    limite_por_minuto: int = 10,
    teto_diario_tokens: int | None = None,
    confiar_proxy: bool = False,
    relogio: Callable[[], float] = time.monotonic,
    dia_atual: Callable[[], str] = lambda: date.today().isoformat(),
) -> FastAPI:
    app = FastAPI()

    if origens_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(origens_cors),
            allow_methods=["GET", "POST"],
            allow_headers=["content-type"],
        )

    historico_ip: dict[str, deque[float]] = defaultdict(deque)
    trava_limite = threading.Lock()
    trava_responder = threading.Lock()
    estado_tokens = {"dia": dia_atual(), "total": 0}

    @app.get("/saude")
    def saude() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/perguntar")
    def perguntar(corpo: PerguntaEntrada, request: Request) -> JSONResponse:
        if confiar_proxy:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                ip = xff.split(",")[0].strip()
            else:
                ip = request.client.host if request.client else "127.0.0.1"
        else:
            ip = request.client.host if request.client else "127.0.0.1"

        agora = relogio()
        with trava_limite:
            fila = historico_ip[ip]
            while fila and fila[0] <= agora - 60.0:
                fila.popleft()
            if len(fila) >= limite_por_minuto:
                tempo_espera = math.ceil(fila[0] + 60.0 - agora)
                retry_after = max(1, tempo_espera)
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Muitas requisições. Tente novamente em instantes."},
                    headers={"Retry-After": str(retry_after)},
                )
            fila.append(agora)

        with trava_responder:
            dia_hoje = dia_atual()
            if dia_hoje != estado_tokens["dia"]:
                estado_tokens["dia"] = dia_hoje
                estado_tokens["total"] = 0

            if teto_diario_tokens is not None and estado_tokens["total"] >= teto_diario_tokens:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Limite diário de uso atingido. Tente novamente amanhã."},
                )

            try:
                res = responder_fn(corpo.pergunta, corpo.instituicao)
            except ErroLLM:
                return JSONResponse(
                    status_code=502,
                    content={"detail": "Falha ao consultar o modelo de linguagem."},
                )
            except Exception:
                logger.exception("Erro interno ao processar a pergunta.")
                return JSONResponse(
                    status_code=500,
                    content={"detail": "Erro interno ao processar a pergunta."},
                )

            t_in = res.get("tokens_entrada") or 0
            t_out = res.get("tokens_saida") or 0
            estado_tokens["total"] += t_in + t_out

        logger.info(
            "pergunta_respondida",
            extra={
                "instituicao": corpo.instituicao,
                "recusou": res["recusou"],
                "tokens_entrada": res.get("tokens_entrada"),
                "tokens_saida": res.get("tokens_saida"),
                "recuperacao_s": res.get("recuperacao_s"),
                "geracao_s": res.get("latencia_s"),
                "total_s": res.get("total_s"),
            },
        )

        blocos = res.get("blocos") or []
        mapa_textos = {b["indice"]: b.get("texto", "") for b in blocos if "indice" in b}
        citacoes = [
            {
                "indice": c["indice"],
                "citacao": c["citacao"],
                "titulo_doc": c["titulo_doc"],
                "url": c["url"],
                "texto": mapa_textos.get(c["indice"], ""),
            }
            for c in res.get("citacoes") or []
        ]

        resposta_final = {
            "resposta": res["resposta"],
            "recusou": res["recusou"],
            "motivo_recusa": res.get("motivo_recusa"),
            "citacoes": citacoes,
            "tempos": {
                "recuperacao_s": res.get("recuperacao_s"),
                "geracao_s": res.get("latencia_s"),
                "total_s": res.get("total_s"),
            },
            "tokens": {
                "entrada": res.get("tokens_entrada"),
                "saida": res.get("tokens_saida"),
            },
        }

        return JSONResponse(status_code=200, content=resposta_final)

    return app
