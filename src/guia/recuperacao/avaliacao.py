"""Avaliação da qualidade da recuperação (hit@k, MRR, separabilidade de recusas).

Funções puras — nenhuma dependência de banco ou modelo.
Contrato completo descrito em tests/test_avaliacao_recuperacao.py.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    """Remove acentos, converte para minúsculas e trata hífens/underscores como espaços."""
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return sem_acento.lower().replace("-", " ").replace("_", " ")


def _extrair_numero_artigo(texto: str) -> str | None:
    """Retorna o número do artigo a partir de 'Art. N' ou 'art. N' ou 'art N'.

    Aceita a forma sem ponto para cobrir local_ids normalizados (ex.: 'art-41'
    vira 'art 41' após _normalizar).
    """
    # Forma canônica: 'art. N' (com ponto)
    m = re.search(r"art\.\s*(\d+)", texto, re.IGNORECASE)
    if m:
        return m.group(1)
    # Forma normalizada de local_id: 'art N' (sem ponto, separado por espaço)
    m = re.search(r"\bart\s+(\d+)\b", texto, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _extrair_numero_passo(texto: str) -> str | None:
    """Retorna o número do passo a partir de 'passo N' (sem diferença de caixa)."""
    m = re.search(r"passo\s+(\d+)", texto, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# carregar_perguntas
# ---------------------------------------------------------------------------

def carregar_perguntas(caminho: str | Path) -> list[dict]:
    """Carrega perguntas de um arquivo JSONL em UTF-8.

    Linhas em branco (ou só espaços) são ignoradas; a ordem é preservada.
    Levanta ValueError com 'linha N' se alguma linha não for JSON válido ou
    faltar as chaves obrigatórias 'id', 'pergunta' ou 'tipo'.
    """
    caminho = Path(caminho)
    perguntas: list[dict] = []
    # Número de linha no arquivo (inclui linhas em branco, para a mensagem de erro)
    num_linha = 0
    for linha_raw in caminho.read_text(encoding="utf-8").splitlines():
        num_linha += 1
        # Ignora linhas em branco
        if not linha_raw.strip():
            continue
        # Tenta parsear o JSON
        try:
            obj = json.loads(linha_raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"linha {num_linha}: JSON inválido — {exc}") from exc
        # Valida chaves obrigatórias
        for chave in ("id", "pergunta", "tipo"):
            if chave not in obj:
                raise ValueError(
                    f"linha {num_linha}: chave obrigatória ausente: '{chave}'"
                )
        perguntas.append(obj)
    return perguntas


# ---------------------------------------------------------------------------
# interpretar_fonte
# ---------------------------------------------------------------------------

def interpretar_fonte(fonte_esperada: str, ids_docs: set[str] | frozenset[str]) -> dict:
    """Interpreta o campo fonte_esperada (texto livre separado por vírgula).

    Cada token que for EXATAMENTE um id conhecido (após strip) é documento;
    o restante, unido por ', ', é o detalhe (None se não sobrar nada).

    Levanta ValueError (com o texto recebido) se nenhum id conhecido for achado.
    """
    tokens = [t.strip() for t in fonte_esperada.split(",")]
    docs_encontrados: list[str] = []
    sobras: list[str] = []

    for token in tokens:
        if token in ids_docs:
            docs_encontrados.append(token)
        else:
            sobras.append(token)

    if not docs_encontrados:
        raise ValueError(
            f"Nenhum id de documento conhecido encontrado em: {fonte_esperada!r}"
        )

    # Detalhe: sobras reunidas por ", " (None se vazio ou só espaços)
    detalhe_str = ", ".join(s for s in sobras if s).strip() or None

    return {"docs": docs_encontrados, "detalhe": detalhe_str}


# ---------------------------------------------------------------------------
# casa_detalhe
# ---------------------------------------------------------------------------

def casa_detalhe(detalhe: str, resultado: dict) -> bool:
    """Verifica se o trecho de busca corresponde ao detalhe esperado.

    Comparação sem acento, sem diferença de maiúscula, com hífens e underscores
    tratados como espaços.  Granularidade de artigo ou passo (veja docstring do módulo).
    """
    citacao = resultado.get("citacao", "") or ""
    local_id = resultado.get("local_id", "") or ""

    # Normaliza tudo
    det = _normalizar(detalhe)
    cit = _normalizar(citacao)
    lid = _normalizar(local_id)

    # --- Caso 1: detalhe refere artigo ("Art. N") ---
    num_art_det = _extrair_numero_artigo(det)
    if num_art_det is not None:
        # Verifica na citação e no local_id
        for texto_alvo in (cit, lid):
            num_art_alvo = _extrair_numero_artigo(texto_alvo)
            if num_art_alvo is not None and num_art_alvo == num_art_det:
                return True
        return False

    # --- Caso 2: detalhe refere passo ("passo N") ---
    num_passo_det = _extrair_numero_passo(det)
    if num_passo_det is not None:
        for texto_alvo in (cit, lid):
            num_passo_alvo = _extrair_numero_passo(texto_alvo)
            if num_passo_alvo is not None and num_passo_alvo == num_passo_det:
                return True
        return False

    # --- Caso 3: texto livre (antes do primeiro '('), como palavras inteiras ---
    # Remove o que vier depois do primeiro '('
    det_base = det.split("(")[0].strip()
    if not det_base:
        return False

    # Usa \b (word boundary) para correspondência de palavras inteiras
    padrao = re.escape(det_base)
    for texto_alvo in (cit, lid):
        if re.search(r"\b" + padrao + r"\b", texto_alvo):
            return True
    return False


# ---------------------------------------------------------------------------
# avaliar_recuperacao
# ---------------------------------------------------------------------------

def avaliar_recuperacao(
    perguntas: list[dict],
    buscar: Callable[[str, int], list[dict]],
    ids_docs: set[str] | frozenset[str],
    ks: tuple[int, ...] = (1, 3, 5),
    profundidade: int = 10,
) -> dict[str, Any]:
    """Avalia a qualidade da recuperação via hit@k e MRR.

    Parâmetros
    ----------
    perguntas:
        Lista de dicts com ao menos 'id', 'pergunta' e 'tipo'; perguntas do
        tipo diferente de 'recusa' precisam de 'fonte_esperada'.
    buscar:
        Callable (pergunta, k) -> list[dict] com chaves 'doc_id', 'citacao',
        'local_id', 'distancia'.  Chamado UMA vez por pergunta (k=profundidade),
        exceto pendentes.
    ids_docs:
        Conjunto de ids de documentos conhecidos.
    ks:
        Cortes para hit e MRR.
    profundidade:
        Número de resultados pedidos à função buscar.

    Retorna dict serializável em JSON (todas as chaves de k são str).
    """
    if profundidade < max(ks):
        raise ValueError(
            f"profundidade ({profundidade}) deve ser >= max(ks) ({max(ks)})"
        )

    n_perguntas = len(perguntas)
    pendentes: list[str] = []
    n_recusa = 0
    # Resultados por pergunta: avaliadas E recusas (exceto pendentes)
    por_pergunta_lista: list[dict] = []

    # Acumuladores para hit_doc e mrr_doc (sobre avaliadas, não recusas)
    hit_doc_soma: dict[int, float] = {k: 0.0 for k in ks}
    mrr_soma = 0.0
    n_avaliadas = 0

    # Acumuladores para hit_trecho (só perguntas com detalhe)
    hit_trecho_soma: dict[int, float] = {k: 0.0 for k in ks}
    n_com_detalhe = 0

    # Distâncias: top-1 de aplicáveis e recusas
    dist_aplicaveis: list[float] = []
    dist_recusa: list[float] = []

    for perg in perguntas:
        pid = perg["id"]
        tipo = perg["tipo"]

        # Pergunta pendente: não busca, não conta em avaliadas/recusa
        if "depende" in perg:
            pendentes.append(pid)
            continue

        # Busca os resultados
        resultados = buscar(perg["pergunta"], profundidade)
        dist_top1 = resultados[0]["distancia"] if resultados else None

        # Pergunta de recusa: não tem gabarito de documento
        if tipo == "recusa":
            n_recusa += 1
            por_pergunta_lista.append({
                "id": pid,
                "tipo": tipo,
                "rank_doc": None,
                "rank_trecho": None,
                "distancia_top1": dist_top1,
            })
            if dist_top1 is not None:
                dist_recusa.append(dist_top1)
            continue

        # Pergunta avaliada: precisa de fonte_esperada
        if "fonte_esperada" not in perg:
            raise ValueError(
                f"Pergunta '{pid}' não é recusa mas não tem 'fonte_esperada'."
            )
        try:
            fonte = interpretar_fonte(perg["fonte_esperada"], ids_docs)
        except ValueError as exc:
            raise ValueError(f"Pergunta '{pid}': {exc}") from exc

        docs_esperados = set(fonte["docs"])
        detalhe = fonte["detalhe"]
        tem_detalhe = detalhe is not None

        n_avaliadas += 1
        if tem_detalhe:
            n_com_detalhe += 1

        # Encontra o rank do primeiro documento esperado (1-based)
        rank_doc: int | None = None
        rank_trecho: int | None = None

        # Limita ao número de resultados pedidos (profundidade)
        for pos, res in enumerate(resultados[:profundidade], start=1):
            doc_id = res.get("doc_id")
            if doc_id in docs_esperados:
                if rank_doc is None:
                    rank_doc = pos
                # Se tem detalhe, procura o primeiro trecho que bata
                if tem_detalhe and rank_trecho is None and casa_detalhe(detalhe, res):
                    rank_trecho = pos
            # Se já encontrou ambos, pode parar
            if rank_doc is not None and (not tem_detalhe or rank_trecho is not None):
                break

        # Acumula hit_doc
        for k in ks:
            if rank_doc is not None and rank_doc <= k:
                hit_doc_soma[k] += 1.0

        # Acumula MRR (0 se rank_doc fora da profundidade)
        if rank_doc is not None:
            mrr_soma += 1.0 / rank_doc

        # Acumula hit_trecho (só perguntas com detalhe)
        if tem_detalhe:
            for k in ks:
                if rank_trecho is not None and rank_trecho <= k:
                    hit_trecho_soma[k] += 1.0

        # Distância do top-1 (pergunta avaliada contribui para aplicáveis)
        if dist_top1 is not None:
            dist_aplicaveis.append(dist_top1)

        entrada_por_pergunta: dict[str, Any] = {
            "id": pid,
            "tipo": tipo,
            "rank_doc": rank_doc,
            "rank_trecho": rank_trecho if tem_detalhe else None,
            "distancia_top1": dist_top1,
        }

        por_pergunta_lista.append(entrada_por_pergunta)

    # Calcula métricas finais (chaves de k são str para ser serializável em JSON)
    hit_doc: dict[str, float] = {
        str(k): (hit_doc_soma[k] / n_avaliadas if n_avaliadas else 0.0)
        for k in ks
    }
    mrr_doc: float = mrr_soma / n_avaliadas if n_avaliadas else 0.0

    # hit_trecho: None em cada k se não houver perguntas com detalhe
    hit_trecho: dict[str, float | None] = {
        str(k): (
            hit_trecho_soma[k] / n_com_detalhe if n_com_detalhe else None
        )
        for k in ks
    }

    # Distâncias e separabilidade
    dist_apl_min = min(dist_aplicaveis) if dist_aplicaveis else None
    dist_apl_max = max(dist_aplicaveis) if dist_aplicaveis else None
    dist_rec_min = min(dist_recusa) if dist_recusa else None
    dist_rec_max = max(dist_recusa) if dist_recusa else None

    if dist_apl_max is not None and dist_rec_min is not None:
        separavel: bool | None = dist_apl_max < dist_rec_min
    else:
        separavel = None

    return {
        "n_perguntas": n_perguntas,
        "n_avaliadas": n_avaliadas,
        "n_recusa": n_recusa,
        "pendentes": pendentes,
        "hit_doc": hit_doc,
        "mrr_doc": mrr_doc,
        "n_com_detalhe": n_com_detalhe,
        "hit_trecho": hit_trecho,
        "por_pergunta": por_pergunta_lista,
        "distancias": {
            "aplicaveis": {"min": dist_apl_min, "max": dist_apl_max},
            "recusa": {"min": dist_rec_min, "max": dist_rec_max},
            "separavel": separavel,
        },
    }


# ---------------------------------------------------------------------------
# comparar
# ---------------------------------------------------------------------------

def comparar(antes: dict, depois: dict) -> dict:
    """Calcula o delta (depois - antes) para mrr_doc, hit_doc e hit_trecho.

    Só compara os k presentes nos dois dicts; None se algum lado for None.
    Arredonda a 6 casas decimais.
    """
    def _delta(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return round(b - a, 6)

    # hit_doc: só os k que aparecem nos dois
    ks_doc = set(antes.get("hit_doc", {})) & set(depois.get("hit_doc", {}))
    hit_doc_delta = {
        k: _delta(antes["hit_doc"][k], depois["hit_doc"][k])
        for k in sorted(ks_doc)
    }

    # hit_trecho: só os k que aparecem nos dois
    ks_trecho = set(antes.get("hit_trecho", {})) & set(depois.get("hit_trecho", {}))
    hit_trecho_delta = {
        k: _delta(antes["hit_trecho"][k], depois["hit_trecho"][k])
        for k in sorted(ks_trecho)
    }

    return {
        "mrr_doc": _delta(antes.get("mrr_doc"), depois.get("mrr_doc")),
        "hit_doc": hit_doc_delta,
        "hit_trecho": hit_trecho_delta,
    }


# ---------------------------------------------------------------------------
# salvar_resultado / carregar_resultado
# ---------------------------------------------------------------------------

def salvar_resultado(resultado: dict, caminho: str | Path, rotulo: str) -> None:
    """Salva o resultado como JSON legível (indent=2, sem escapar acentos).

    Cria a pasta se necessário; grava {"rotulo": rotulo, **resultado}.
    """
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    payload = {"rotulo": rotulo, **resultado}
    caminho.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def carregar_resultado(caminho: str | Path) -> dict:
    """Carrega o resultado salvo por salvar_resultado; devolve exatamente o que foi gravado."""
    caminho = Path(caminho)
    return json.loads(caminho.read_text(encoding="utf-8"))
