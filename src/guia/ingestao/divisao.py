"""Divisão de artigos longos em trechos menores para indexação.

Regras (conforme contrato):
1. Se len(artigo["texto"]) <= limite_artigo  ->  devolve um único trecho intacto.
2. Caput = tudo antes da primeira linha de inciso ou de parágrafo.
   - Inciso: linha que, ignorando espaços/tabs/NBSP iniciais, começa com numeral
     romano MAIÚSCULO seguido de espaço opcional e de "-", "–" ou "—".
   - Parágrafo: linha que começa com "§" ou "Parágrafo único".
3. Incisos do caput são agrupados gulosa enquanto o corpo do grupo
   (sem caput, linhas unidas com "\n") tiver no máximo limite_grupo chars.
   Um inciso sozinho maior que o limite fica inteiro em trecho próprio.
4. Linhas que não iniciam inciso nem parágrafo (alíneas, continuações)
   pertencem ao bloco anterior.
5. Cada parágrafo (com os incisos/alíneas que vêm depois) é trecho próprio
   e nunca é agrupado com incisos do caput.
6. Cada trecho começa com o caput repetido, seguido de "\n" e do corpo.
7. Artigo longo sem inciso nem parágrafo  ->  devolve um trecho só, sem cortar.
8. Cada trecho é uma cópia do dict de entrada com "texto" trocado e as chaves
   "id" (f"art-{artigo}#{parte}"), "parte" (inicia em 1) e "total_partes".
   O dict de entrada não é alterado.
"""

import re

# ---------------------------------------------------------------------------
# Padrão de reconhecimento de linha de inciso (regra 2)
# Ignora espaços, tabs e NBSP (U+00A0) no início da linha.
# Numeral romano MAIÚSCULO: [IVXLCDM]+
# Seguido opcionalmente de espaço e de "-", "–" (U+2013) ou "—" (U+2014).
# ---------------------------------------------------------------------------
_INCISO_RE = re.compile(
    r'^[ \t\u00a0]*[IVXLCDM]+[ \t\u00a0]*[-\u2013\u2014]',
)

# ---------------------------------------------------------------------------
# Padrão de reconhecimento de linha de parágrafo (regra 2)
# ---------------------------------------------------------------------------
_PARAGRAFO_RE = re.compile(
    r'^[ \t\u00a0]*(§|Parágrafo único)',
)


def _eh_inciso(linha: str) -> bool:
    return bool(_INCISO_RE.match(linha))


def _eh_paragrafo(linha: str) -> bool:
    return bool(_PARAGRAFO_RE.match(linha))


def _blocos_do_artigo(linhas: list[str]) -> tuple[str, list[tuple[str, list[str]]]]:
    """Separa o caput e retorna (caput, [(tipo, linhas_do_bloco)]).

    tipo é "inciso" para incisos do caput e "paragrafo" para §/Parágrafo único
    (inclusive os incisos que pertencem ao parágrafo).

    Alíneas e continuações grudam no bloco imediatamente anterior (regra 4).
    Incisos após § pertencem ao § (regra 5).
    """
    caput_linhas: list[str] = []
    blocos: list[tuple[str, list[str]]] = []
    primeira_divisao_encontrada = False
    em_paragrafo = False  # True quando o bloco corrente é um parágrafo

    bloco_corrente: list[str] = []
    tipo_corrente: str = "inciso"

    def _fechar_bloco() -> None:
        if bloco_corrente:
            blocos.append((tipo_corrente, list(bloco_corrente)))
            bloco_corrente.clear()

    for linha in linhas:
        if not primeira_divisao_encontrada:
            # Ainda no caput
            if _eh_inciso(linha):
                primeira_divisao_encontrada = True
                em_paragrafo = False
                tipo_corrente = "inciso"
                bloco_corrente.append(linha)
            elif _eh_paragrafo(linha):
                primeira_divisao_encontrada = True
                em_paragrafo = True
                tipo_corrente = "paragrafo"
                bloco_corrente.append(linha)
            else:
                caput_linhas.append(linha)
        else:
            if _eh_paragrafo(linha):
                # Novo parágrafo: fecha bloco anterior e abre parágrafo
                _fechar_bloco()
                em_paragrafo = True
                tipo_corrente = "paragrafo"
                bloco_corrente.append(linha)
            elif _eh_inciso(linha):
                if em_paragrafo:
                    # Inciso dentro de parágrafo: fica no bloco do parágrafo (regra 5)
                    bloco_corrente.append(linha)
                else:
                    # Novo inciso do caput: fecha anterior e abre novo
                    _fechar_bloco()
                    tipo_corrente = "inciso"
                    bloco_corrente.append(linha)
            else:
                # Alínea ou continuação: pertence ao bloco anterior (regra 4)
                bloco_corrente.append(linha)

    _fechar_bloco()

    caput = "\n".join(caput_linhas)
    return caput, blocos


def dividir_artigo(
    artigo: dict,
    limite_artigo: int = 1500,
    limite_grupo: int = 800,
) -> list[dict]:
    """Divide um artigo em trechos menores para indexação.

    Parâmetros
    ----------
    artigo : dict
        Dict com pelo menos as chaves "artigo" e "texto".
    limite_artigo : int
        Comprimento máximo (em caracteres) abaixo do qual o artigo não é dividido.
    limite_grupo : int
        Comprimento máximo do corpo de um grupo de incisos (sem o caput).

    Retorna
    -------
    list[dict]
        Lista de trechos. Cada trecho é uma cópia do dict de entrada com "texto"
        trocado, e as chaves adicionais "id", "parte" e "total_partes".
    """
    texto: str = artigo["texto"]
    num_artigo = artigo["artigo"]

    # Regra 1: artigo curto fica inteiro
    if len(texto) <= limite_artigo:
        return [{
            **artigo,
            "texto": texto,
            "id": f"art-{num_artigo}#1",
            "parte": 1,
            "total_partes": 1,
        }]

    linhas = texto.split("\n")
    caput, blocos = _blocos_do_artigo(linhas)

    # Regra 7: artigo longo sem inciso nem parágrafo -> trecho único, sem cortar
    if not blocos:
        return [{
            **artigo,
            "texto": texto,
            "id": f"art-{num_artigo}#1",
            "parte": 1,
            "total_partes": 1,
        }]

    # ---------- Agrupamento de incisos do caput (regras 3 e 4) ----------
    # Parágrafos viram trechos próprios imediatamente (regra 5).
    # Incisos são agrupados gulosa enquanto o corpo acumulado <= limite_grupo.
    # Um único inciso maior que o limite fica sozinho (sem corte).

    corpos: list[str] = []      # corpo de cada trecho (sem caput)
    acum_linhas: list[str] = [] # acumulador de linhas do grupo corrente de incisos
    acum_len: int = 0           # comprimento do corpo do grupo corrente

    def flush() -> None:
        nonlocal acum_len
        if acum_linhas:
            corpos.append("\n".join(acum_linhas))
            acum_linhas.clear()
            acum_len = 0

    for tipo, linhas_bloco in blocos:
        corpo_bloco = "\n".join(linhas_bloco)

        if tipo == "paragrafo":
            # Regra 5: fecha grupo de incisos pendente; parágrafo vira trecho próprio
            flush()
            corpos.append(corpo_bloco)
        else:
            # tipo == "inciso": agrupamento guloso (regra 3)
            if not acum_linhas:
                # Primeiro inciso do grupo: sempre entra (mesmo que ultrapasse limite_grupo)
                acum_linhas.extend(linhas_bloco)
                acum_len = len(corpo_bloco)
            else:
                novo_len = acum_len + 1 + len(corpo_bloco)  # +1 pelo "\n" separador
                if novo_len <= limite_grupo:
                    # Cabe: junta no grupo atual
                    acum_linhas.extend(linhas_bloco)
                    acum_len = novo_len
                else:
                    # Não cabe: fecha grupo atual e abre novo com este inciso
                    flush()
                    acum_linhas.extend(linhas_bloco)
                    acum_len = len(corpo_bloco)

    flush()  # fecha eventual grupo de incisos pendente ao final

    # ---------- Montagem dos trechos (regra 6) ----------
    total = len(corpos)
    trechos: list[dict] = []
    for i, corpo in enumerate(corpos, start=1):
        texto_trecho = caput + "\n" + corpo
        trechos.append({
            **artigo,
            "texto": texto_trecho,
            "id": f"art-{num_artigo}#{i}",
            "parte": i,
            "total_partes": total,
        })

    return trechos
