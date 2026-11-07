"""Camada de geração independente de provedor de LLM.

Princípios:
  * Recusa resolvida em três degraus: sem contexto (sem chamar o LLM),
    LLM recusa explicitamente (TOKEN_RECUSA), ou resposta sem citação válida.
  * O LLM cita por número de bloco ([1], [2]), convertidos para citações reais
    a partir dos metadados dos blocos de contexto.
  * A unidade de contexto é o ARTIGO (trechos irmãos com o mesmo pai_id, com
    repetições do caput removidas), exclusivo para tipo_doc "resolucao".
"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.rows import dict_row

# ---------------------------------------------------------------------------
# Constantes públicas
# ---------------------------------------------------------------------------

MENSAGEM_RECUSA: str = (
    "Não encontrei informações suficientes nos documentos disponíveis "
    "para responder a esta pergunta com segurança."
)
TOKEN_RECUSA: str = "NAO_ENCONTRADO"


# ---------------------------------------------------------------------------
# juntar_trechos_irmaos
# ---------------------------------------------------------------------------

def juntar_trechos_irmaos(textos: list[str]) -> str:
    """Junta os textos de trechos irmãos, removendo repetições do caput.

    As linhas iniciais comuns a todos os trechos (comparadas com strip())
    são mantidas apenas no primeiro trecho e removidas dos demais.
    Cada trecho mantém no mínimo uma linha (nunca remove um trecho inteiro).
    Um único texto é retornado com strip(). Separador entre trechos: '\\n'.
    """
    if not textos:
        return ""
    if len(textos) == 1:
        return textos[0].strip()

    # Cada texto tem suas bordas limpas antes de dividir em linhas
    linhas_por_texto = [t.strip().splitlines() for t in textos]
    linhas_por_texto = [linhas if linhas else [""] for linhas in linhas_por_texto]

    # Determina o número de linhas iniciais comuns a todos os textos
    k = 0
    while (
        k < len(linhas_por_texto[0])
        and all(k < len(linhas) - 1 for linhas in linhas_por_texto[1:])
    ):
        linha_ref = linhas_por_texto[0][k].strip()
        if all(linhas[k].strip() == linha_ref for linhas in linhas_por_texto[1:]):
            k += 1
        else:
            break

    partes: list[str] = ["\n".join(linhas_por_texto[0])]
    for linhas in linhas_por_texto[1:]:
        partes.append("\n".join(linhas[k:]))

    return "\n".join(partes)


# ---------------------------------------------------------------------------
# citacao_do_bloco
# ---------------------------------------------------------------------------

def citacao_do_bloco(trechos: list[dict[str, Any]]) -> str:
    """Monta a citação consolidada de um bloco de trechos irmãos.

    O prefixo é extraído da citação do primeiro trecho até ', p.' (ou inteira
    se não houver). As páginas são a união ordenada e sem duplicações de todas
    as páginas dos trechos do bloco. Formatos possíveis de páginas:
    'p. N', 'p. A-B' (intervalo contínuo) ou 'p. A, B, C'. Sem páginas: só o prefixo.
    """
    if not trechos:
        return ""

    citacao_primeiro = trechos[0].get("citacao", "") or ""
    prefixo = citacao_primeiro.split(", p.")[0].strip()

    paginas_set: set[int] = set()
    for t in trechos:
        pags = t.get("paginas")
        if pags:
            for p in pags:
                if isinstance(p, int):
                    paginas_set.add(p)

    uniq = sorted(paginas_set)
    if not uniq:
        return prefixo

    grupos: list[tuple[int, int]] = []
    inicio = uniq[0]
    fim = uniq[0]
    for n in uniq[1:]:
        if n == fim + 1:
            fim = n
        else:
            grupos.append((inicio, fim))
            inicio = fim = n
    grupos.append((inicio, fim))

    partes = [str(a) if a == b else f"{a}-{b}" for a, b in grupos]
    faixa = ", ".join(partes)
    return f"{prefixo}, p. {faixa}"


# ---------------------------------------------------------------------------
# montar_contexto
# ---------------------------------------------------------------------------

def montar_contexto(
    conn: psycopg.Connection,
    recuperados: list[dict[str, Any]],
    max_artigos: int = 3,
) -> list[dict[str, Any]]:
    """Monta os blocos de contexto para o LLM a partir dos trechos recuperados.

    Para documentos do tipo 'resolucao', agrupa por pai_id e busca todos os
    trechos irmãos no banco (ordenados por parte). Para os demais tipos, cada
    trecho recuperado forma seu próprio bloco (sem expansão).

    Executa no máximo duas consultas ao banco (uma para os ids recuperados e
    outra para os trechos irmãos das resoluções), ambas parametrizadas.
    """
    if not recuperados or max_artigos <= 0:
        return []

    ids_recuperados = [r["id"] for r in recuperados if "id" in r]
    if not ids_recuperados:
        return []

    # 1ª consulta: busca os trechos recuperados pelo ID
    sql_recuperados = """
        SELECT
            id, doc_id, tipo_doc, titulo_doc, url, citacao, texto,
            pai_id, parte, paginas
        FROM trechos
        WHERE id = ANY(%s)
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql_recuperados, (ids_recuperados,))
        linhas_rec = cur.fetchall()

    trechos_por_id: dict[str, dict[str, Any]] = {row["id"]: row for row in linhas_rec}

    # Seleciona os blocos respeitando a ordem de primeira aparição e max_artigos
    chaves_selecionadas: list[tuple[str, str]] = []
    trecho_ref_por_chave: dict[tuple[str, str], dict[str, Any]] = {}
    seen_chaves: set[tuple[str, str]] = set()

    for item in recuperados:
        tid = item.get("id")
        trecho = trechos_por_id.get(tid)
        if not trecho:
            continue

        tipo_doc = trecho.get("tipo_doc")
        if tipo_doc == "resolucao":
            pai = trecho.get("pai_id")
            chave = ("resolucao", pai if pai is not None else trecho["id"])
        else:
            chave = ("trecho", trecho["id"])

        if chave not in seen_chaves:
            seen_chaves.add(chave)
            chaves_selecionadas.append(chave)
            trecho_ref_por_chave[chave] = trecho
            if len(chaves_selecionadas) == max_artigos:
                break

    if not chaves_selecionadas:
        return []

    # Identifica pai_ids de resoluções que precisam de busca por irmãos
    pais_resolucao = [
        ident
        for tipo_chave, ident in chaves_selecionadas
        if tipo_chave == "resolucao"
    ]

    # 2ª consulta: busca todos os trechos irmãos das resoluções selecionadas
    irmaos_por_pai: dict[str, list[dict[str, Any]]] = {}
    if pais_resolucao:
        sql_irmaos = """
            SELECT
                id, doc_id, tipo_doc, titulo_doc, url, citacao, texto,
                pai_id, parte, paginas
            FROM trechos
            WHERE pai_id = ANY(%s)
            ORDER BY parte ASC, id ASC
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql_irmaos, (pais_resolucao,))
            for row in cur.fetchall():
                p_id = row.get("pai_id")
                if p_id:
                    irmaos_por_pai.setdefault(p_id, []).append(row)

    # Constrói a lista final de blocos
    blocos: list[dict[str, Any]] = []
    for idx, (tipo_chave, ident) in enumerate(chaves_selecionadas, start=1):
        if tipo_chave == "resolucao":
            trechos_bloco = irmaos_por_pai.get(ident)
            if not trechos_bloco:
                trechos_bloco = [trecho_ref_por_chave[(tipo_chave, ident)]]
        else:
            trechos_bloco = [trecho_ref_por_chave[(tipo_chave, ident)]]

        base = trechos_bloco[0]

        # União ordenada de páginas
        paginas_set: set[int] = set()
        for t in trechos_bloco:
            pags = t.get("paginas")
            if pags:
                for p in pags:
                    if isinstance(p, int):
                        paginas_set.add(p)
        paginas_uniao = sorted(paginas_set)

        citacao = citacao_do_bloco(trechos_bloco)
        textos_irmaos = [t.get("texto", "") or "" for t in trechos_bloco]
        texto_combinado = juntar_trechos_irmaos(textos_irmaos)
        ids_bloco = [t["id"] for t in trechos_bloco]

        bloco = {
            "indice": idx,
            "pai_id": base.get("pai_id"),
            "doc_id": base.get("doc_id"),
            "titulo_doc": base.get("titulo_doc"),
            "url": base.get("url"),
            "citacao": citacao,
            "paginas": paginas_uniao,
            "texto": texto_combinado,
            "ids": ids_bloco,
        }
        blocos.append(bloco)

    return blocos


# ---------------------------------------------------------------------------
# montar_prompt
# ---------------------------------------------------------------------------

def montar_prompt(
    pergunta: str,
    blocos: list[dict[str, Any]],
) -> tuple[str, str]:
    """Monta o system prompt e o user prompt para a consulta ao LLM.

    Levanta ValueError se blocos for vazio.
    """
    if not blocos:
        raise ValueError("A lista de blocos não pode ser vazia para montar o prompt.")

    system = (
        "Você é um assistente acadêmico institucional. Sua tarefa é responder perguntas "
        "com base estritamente nos trechos de documentos fornecidos no contexto.\n\n"
        "Regras fundamentais:\n"
        "1. Responda apenas o que estiver fundamentado nas fontes fornecidas.\n"
        "2. Todas as informações factuais da resposta DEVEM conter citação usando o número do bloco "
        "correspondente entre colchetes, no formato [n] ou [n, m], por exemplo: [1] ou [1, 2]. "
        "Nunca invente números de blocos e nunca use outro formato de citação.\n"
        f"3. Se as fontes fornecidas não contiverem informação suficiente para responder com certeza, "
        f"responda EXATAMENTE com o token {TOKEN_RECUSA} e nada mais.\n"
        "4. Seja claro, direto e objetivo."
    )

    linhas_user = ["Fontes disponíveis:\n"]
    for b in blocos:
        linhas_user.append(f"[{b['indice']}] {b['citacao']}")
        linhas_user.append(b["texto"])
        linhas_user.append("")

    linhas_user.append(f"Pergunta: {pergunta}")
    user = "\n".join(linhas_user).strip()

    return system, user


# ---------------------------------------------------------------------------
# responder
# ---------------------------------------------------------------------------

def responder(
    pergunta: str,
    blocos: list[dict[str, Any]],
    llm: Callable[[str, str], dict[str, Any]],
    relogio: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    """Gera resposta para a pergunta a partir dos blocos usando o LLM informado.

    Valida as citações numéricas e trata recusas (sem contexto, LLM recusou,
    citação inválida ou ausência de citação).
    """
    if not blocos:
        return {
            "resposta": MENSAGEM_RECUSA,
            "resposta_bruta": None,
            "recusou": True,
            "motivo_recusa": "sem_contexto",
            "citacoes": [],
            "tokens_entrada": None,
            "tokens_saida": None,
            "latencia_s": 0.0,
        }

    system, user = montar_prompt(pergunta, blocos)

    t_inicio = relogio()
    saida = llm(system, user)
    latencia_s = float(relogio() - t_inicio)

    texto_bruto = saida.get("texto", "") or ""
    tokens_entrada = saida.get("tokens_entrada")
    tokens_saida = saida.get("tokens_saida")

    # Verifica se o LLM recusou explicitamente
    if texto_bruto.strip().upper().startswith(TOKEN_RECUSA.upper()):
        return {
            "resposta": MENSAGEM_RECUSA,
            "resposta_bruta": texto_bruto,
            "recusou": True,
            "motivo_recusa": "llm_recusou",
            "citacoes": [],
            "tokens_entrada": tokens_entrada,
            "tokens_saida": tokens_saida,
            "latencia_s": latencia_s,
        }

    # Extrai números de citação nos formatos [n] e [n, m]
    todos_numeros: list[int] = []
    for match in re.finditer(r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]", texto_bruto):
        for parte in match.group(1).split(","):
            todos_numeros.append(int(parte.strip()))

    # Se não houver nenhuma citação, rejeita a resposta
    if not todos_numeros:
        return {
            "resposta": MENSAGEM_RECUSA,
            "resposta_bruta": texto_bruto,
            "recusou": True,
            "motivo_recusa": "sem_citacao",
            "citacoes": [],
            "tokens_entrada": tokens_entrada,
            "tokens_saida": tokens_saida,
            "latencia_s": latencia_s,
        }

    # Valida se todos os números estão no intervalo 1..len(blocos)
    n_blocos = len(blocos)
    for num in todos_numeros:
        if num < 1 or num > n_blocos:
            return {
                "resposta": MENSAGEM_RECUSA,
                "resposta_bruta": texto_bruto,
                "recusou": True,
                "motivo_recusa": "citacao_invalida",
                "citacoes": [],
                "tokens_entrada": tokens_entrada,
                "tokens_saida": tokens_saida,
                "latencia_s": latencia_s,
            }

    # Monta citações sem repetição na ordem da primeira aparição
    blocos_por_indice = {b["indice"]: b for b in blocos}
    indices_vistos: set[int] = set()
    citacoes: list[dict[str, Any]] = []

    for num in todos_numeros:
        if num not in indices_vistos:
            indices_vistos.add(num)
            b = blocos_por_indice[num]
            citacoes.append({
                "indice": b["indice"],
                "citacao": b["citacao"],
                "doc_id": b["doc_id"],
                "titulo_doc": b["titulo_doc"],
                "url": b["url"],
            })

    return {
        "resposta": texto_bruto,
        "resposta_bruta": texto_bruto,
        "recusou": False,
        "motivo_recusa": None,
        "citacoes": citacoes,
        "tokens_entrada": tokens_entrada,
        "tokens_saida": tokens_saida,
        "latencia_s": latencia_s,
    }

