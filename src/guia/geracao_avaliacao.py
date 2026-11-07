"""Avaliação da geração: recusa correta, recusa indevida, citação correta, tokens, custo e latência.

Mede o comportamento do pipeline completo em relação a gabaritos de perguntas,
avaliando se o modelo soube responder citando a norma correta ou se recusou
adequadamente perguntas sem resposta.
"""
from __future__ import annotations

import statistics
from collections.abc import Callable
from typing import Any

from guia.recuperacao.avaliacao import casa_detalhe, interpretar_fonte


def avaliar_geracao(
    perguntas: list[dict[str, Any]],
    responder_fn: Callable[[dict[str, Any]], dict[str, Any]],
    ids_docs: set[str] | frozenset[str],
    preco_entrada: float | None = None,
    preco_saida: float | None = None,
) -> dict[str, Any]:
    """Avalia as respostas da camada de geração sobre um conjunto de perguntas.

    Parâmetros:
      perguntas: Lista de dicionários de perguntas (ex: de perguntas.jsonl).
                 Perguntas com chave 'depende' são consideradas pendentes.
      responder_fn: Função que recebe a pergunta e retorna o dict de resposta
                    (ou dict contendo chave 'erro' caso ocorra falha).
      ids_docs: Conjunto de identificadores de documentos conhecidos.
      preco_entrada: Preço em USD por milhão de tokens de entrada (opcional).
      preco_saida: Preço em USD por milhão de tokens de saída (opcional).

    Retorna um dicionário serializável em JSON com todas as métricas consolidadas
    e detalhes linha a linha em 'por_pergunta'.
    """
    # Valida antecipadamente as perguntas não pendentes que não são recusa
    for p in perguntas:
        if "depende" in p:
            continue
        pid = p["id"]
        if p.get("tipo") != "recusa":
            fonte = p.get("fonte_esperada")
            if not fonte or not str(fonte).strip():
                raise ValueError(f"Pergunta '{pid}' não é recusa mas não tem 'fonte_esperada'.")
            try:
                interpretar_fonte(str(fonte), ids_docs)
            except ValueError as exc:
                raise ValueError(f"Pergunta '{pid}': {exc}") from exc

    pendentes: list[str] = []
    erros: list[str] = []
    por_pergunta: list[dict[str, Any]] = []

    n_recusa = 0
    n_recusa_correta = 0
    n_validas = 0
    n_respondidas = 0
    n_recusa_indevida = 0
    n_citacao_correta = 0

    motivos_recusa: dict[str, int] = {}

    chamadas_llm = 0
    tokens_in_list: list[int] = []
    tokens_out_list: list[int] = []
    latencias: list[float] = []

    for p in perguntas:
        pid = p["id"]
        tipo = p.get("tipo", "")

        if "depende" in p:
            pendentes.append(pid)
            continue

        resp = responder_fn(p)
        erro = resp.get("erro")
        if erro:
            erros.append(pid)
            por_pergunta.append({
                "id": pid,
                "tipo": tipo,
                "recusou": None,
                "motivo_recusa": None,
                "citacao_ok": None,
                "tokens_entrada": None,
                "tokens_saida": None,
                "latencia_s": None,
                "erro": str(erro),
                "resposta_bruta": None,
                "contexto": [],
                "citacoes": [],
                "recuperados_ids": None,
            })
            continue

        recusou = bool(resp.get("recusou"))
        motivo = resp.get("motivo_recusa")
        citacoes = resp.get("citacoes") or []
        ti = resp.get("tokens_entrada")
        ts = resp.get("tokens_saida")
        lat = resp.get("latencia_s")
        resposta_bruta = resp.get("resposta_bruta")
        contexto = [b["citacao"] for b in resp.get("blocos") or []]
        citacoes_lista = [c.get("citacao", "") for c in citacoes]
        recuperados_ids = resp.get("recuperados_ids")

        if motivo != "sem_contexto":
            chamadas_llm += 1
            if ti is not None:
                tokens_in_list.append(ti)
            if ts is not None:
                tokens_out_list.append(ts)
            if lat is not None:
                latencias.append(lat)

        if recusou and motivo:
            motivos_recusa[motivo] = motivos_recusa.get(motivo, 0) + 1

        citacao_ok = None
        if tipo == "recusa":
            n_recusa += 1
            if recusou:
                n_recusa_correta += 1
        else:
            n_validas += 1
            if recusou:
                n_recusa_indevida += 1
            else:
                n_respondidas += 1
                fonte = interpretar_fonte(p["fonte_esperada"], ids_docs)
                docs_esperados = set(fonte["docs"])
                detalhe = fonte["detalhe"]
                ok = False
                for c in citacoes:
                    if c.get("doc_id") in docs_esperados and (
                        detalhe is None or casa_detalhe(detalhe, {"citacao": c.get("citacao", "")})
                    ):
                        ok = True
                        break
                citacao_ok = ok
                if ok:
                    n_citacao_correta += 1

        por_pergunta.append({
            "id": pid,
            "tipo": tipo,
            "recusou": recusou,
            "motivo_recusa": motivo,
            "citacao_ok": citacao_ok,
            "tokens_entrada": ti,
            "tokens_saida": ts,
            "latencia_s": lat,
            "erro": None,
            "resposta_bruta": resposta_bruta,
            "contexto": contexto,
            "citacoes": citacoes_lista,
            "recuperados_ids": recuperados_ids,
        })

    n_erros = len(erros)
    n_avaliadas = len(por_pergunta) - n_erros

    taxa_recusa_correta = (n_recusa_correta / n_recusa) if n_recusa > 0 else None
    taxa_recusa_indevida = (n_recusa_indevida / n_validas) if n_validas > 0 else None
    taxa_citacao_correta = (n_citacao_correta / n_respondidas) if n_respondidas > 0 else None
    aproveitamento = (n_citacao_correta / n_validas) if n_validas > 0 else None

    tokens_entrada_total = sum(tokens_in_list)
    tokens_saida_total = sum(tokens_out_list)
    tokens_entrada_medio = (tokens_entrada_total / len(tokens_in_list)) if tokens_in_list else None
    tokens_saida_medio = (tokens_saida_total / len(tokens_out_list)) if tokens_out_list else None

    latencia_media_s = (sum(latencias) / len(latencias)) if latencias else None
    latencia_mediana_s = float(statistics.median(latencias)) if latencias else None
    latencia_max_s = max(latencias) if latencias else None

    if preco_entrada is not None and preco_saida is not None:
        custo_usd = (tokens_entrada_total * preco_entrada + tokens_saida_total * preco_saida) / 1e6
        custo_usd_por_chamada = (custo_usd / chamadas_llm) if chamadas_llm > 0 else None
    else:
        custo_usd = None
        custo_usd_por_chamada = None

    return {
        "n_perguntas": len(perguntas),
        "n_avaliadas": n_avaliadas,
        "pendentes": pendentes,
        "n_erros": n_erros,
        "erros": erros,
        "n_recusa": n_recusa,
        "n_recusa_correta": n_recusa_correta,
        "taxa_recusa_correta": taxa_recusa_correta,
        "n_validas": n_validas,
        "n_respondidas": n_respondidas,
        "n_recusa_indevida": n_recusa_indevida,
        "taxa_recusa_indevida": taxa_recusa_indevida,
        "n_citacao_correta": n_citacao_correta,
        "taxa_citacao_correta": taxa_citacao_correta,
        "aproveitamento": aproveitamento,
        "motivos_recusa": motivos_recusa,
        "chamadas_llm": chamadas_llm,
        "tokens_entrada_total": tokens_entrada_total,
        "tokens_saida_total": tokens_saida_total,
        "tokens_entrada_medio": tokens_entrada_medio,
        "tokens_saida_medio": tokens_saida_medio,
        "latencia_media_s": latencia_media_s,
        "latencia_mediana_s": latencia_mediana_s,
        "latencia_max_s": latencia_max_s,
        "custo_usd": custo_usd,
        "custo_usd_por_chamada": custo_usd_por_chamada,
        "por_pergunta": por_pergunta,
    }
