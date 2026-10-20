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

# ---------------------------------------------------------------------------
# Padrão de reconhecimento de alínea de primeiro nível (regra nova)
# Ignora espaços, tabs e NBSP iniciais; uma única letra minúscula seguida de
# ")" e espaço. Só abre bloco próprio quando nenhum inciso está aberto.
# ---------------------------------------------------------------------------
_ALINEA_RE = re.compile(
    r'^[ \t\u00a0]*[a-z]\) ',
)


def _eh_inciso(linha: str) -> bool:
    return bool(_INCISO_RE.match(linha))


def _eh_paragrafo(linha: str) -> bool:
    return bool(_PARAGRAFO_RE.match(linha))


def _eh_alinea(linha: str) -> bool:
    return bool(_ALINEA_RE.match(linha))


def _blocos_do_artigo(linhas: list[str]) -> tuple[str, list[tuple[str, list[str]]]]:
    """Separa o caput e retorna (caput, [(tipo, linhas_do_bloco)]).

    tipos possíveis: "inciso", "alinea" (primeiro nível, sem inciso acima),
    "paragrafo" (§ ou Parágrafo único, com seus incisos/alíneas internos).

    Alíneas de primeiro nível: abrem bloco próprio SOMENTE quando nenhum inciso
    ou parágrafo está aberto (tipo_corrente != "inciso" e em_paragrafo=False).
    Dentro de incisos ou parágrafos, alíneas grudam no bloco anterior (regra 4).
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
            elif _eh_alinea(linha):
                # Alínea de primeiro nível sob o caput (sem inciso acima)
                primeira_divisao_encontrada = True
                em_paragrafo = False
                tipo_corrente = "alinea"
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
            elif _eh_alinea(linha) and not em_paragrafo and tipo_corrente != "inciso":
                # Alínea de primeiro nível: abre bloco próprio somente se não
                # há inciso nem parágrafo aberto (tipo corrente é "alinea" ou
                # ainda não há bloco — mas neste branch já temos divisao)
                _fechar_bloco()
                tipo_corrente = "alinea"
                bloco_corrente.append(linha)
            else:
                # Alínea dentro de inciso/parágrafo, ou continuação: gruda no bloco anterior
                bloco_corrente.append(linha)

    _fechar_bloco()

    caput = "\n".join(caput_linhas)
    return caput, blocos


def _pagina_em(pos: int, marcas: list[list[int]]) -> int:
    """Retorna a página vigente na posição pos (última marca com posicao <= pos)."""
    pagina = marcas[0][1]
    for posicao, pag in marcas:
        if posicao <= pos:
            pagina = pag
        else:
            break
    return pagina


def _paginas_do_trecho(ini: int, fim: int, marcas: list[list[int]]) -> list[int]:
    """Páginas do corpo de um trecho dado pelas marcas_pagina do artigo.

    Inclui a página vigente em ini e todas as páginas de marcas com posicao
    estritamente dentro de (ini, fim), sem repetição, ordenadas.
    """
    paginas: set[int] = {_pagina_em(ini, marcas)}
    for posicao, pag in marcas:
        if ini < posicao < fim:
            paginas.add(pag)
    return sorted(paginas)


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
        "marcas_pagina" é removido dos trechos; as páginas do trecho são
        calculadas a partir de "marcas_pagina" e armazenadas em "paginas".
    """
    texto: str = artigo["texto"]
    num_artigo = artigo["artigo"]
    marcas: list[list[int]] | None = artigo.get("marcas_pagina") or None

    # Base do artigo sem marcas_pagina (nunca propagamos marcas_pagina para trechos)
    artigo_base = {k: v for k, v in artigo.items() if k != "marcas_pagina"}

    # Regra 1: artigo curto fica inteiro
    if len(texto) <= limite_artigo:
        return [{
            **artigo_base,
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
            **artigo_base,
            "texto": texto,
            "id": f"art-{num_artigo}#1",
            "parte": 1,
            "total_partes": 1,
        }]

    # Calcula o offset de início de cada bloco dentro de texto.
    # caput ocupa chars 0..len(caput); depois vem '\n' + cada bloco separado por '\n'.
    # Usamos a mesma lógica de split("\n") para achar posições.
    caput_len = len(caput)  # não inclui o '\n' separador
    bloco_inis: list[int] = []  # offset em texto do primeiro char do bloco
    bloco_fins: list[int] = []  # offset em texto após o último char do bloco
    pos = caput_len + 1  # +1 pelo '\n' após o caput
    for _, linhas_bloco in blocos:
        corpo_bloco = "\n".join(linhas_bloco)
        ini_b = pos
        fim_b = pos + len(corpo_bloco)
        bloco_inis.append(ini_b)
        bloco_fins.append(fim_b)
        pos = fim_b + 1  # +1 pelo '\n' separador

    # ---------- Agrupamento de incisos/alíneas do caput (regras 3, 4 e nova) ----------
    # Parágrafos viram trechos próprios imediatamente (regra 5).
    # Incisos e alíneas de primeiro nível são agrupados gulosa até limite_grupo.
    # Um bloco sozinho maior que o limite fica inteiro em trecho próprio (sem corte).

    corpos: list[str] = []      # corpo de cada trecho (sem caput)
    corpo_inis: list[int] = []  # offset de início do corpo no texto original
    corpo_fins: list[int] = []  # offset de fim do corpo no texto original
    acum_linhas: list[str] = [] # acumulador de linhas do grupo corrente de incisos
    acum_len: int = 0           # comprimento do corpo do grupo corrente
    acum_ini: int = 0           # offset de início do grupo acumulado
    acum_fim: int = 0           # offset de fim do grupo acumulado

    def flush() -> None:
        nonlocal acum_len, acum_ini, acum_fim
        if acum_linhas:
            corpos.append("\n".join(acum_linhas))
            corpo_inis.append(acum_ini)
            corpo_fins.append(acum_fim)
            acum_linhas.clear()
            acum_len = 0

    for idx_b, (tipo, linhas_bloco) in enumerate(blocos):
        corpo_bloco = "\n".join(linhas_bloco)
        ini_b = bloco_inis[idx_b]
        fim_b = bloco_fins[idx_b]

        if tipo == "paragrafo":
            # Regra 5: fecha grupo pendente; parágrafo vira trecho próprio
            flush()
            corpos.append(corpo_bloco)
            corpo_inis.append(ini_b)
            corpo_fins.append(fim_b)
        else:
            # tipo == "inciso" ou "alinea": agrupamento guloso (regras 3 e nova)
            if not acum_linhas:
                # Primeiro bloco do grupo: sempre entra (mesmo que ultrapasse limite_grupo)
                acum_linhas.extend(linhas_bloco)
                acum_len = len(corpo_bloco)
                acum_ini = ini_b
                acum_fim = fim_b
            else:
                novo_len = acum_len + 1 + len(corpo_bloco)  # +1 pelo "\n" separador
                if novo_len <= limite_grupo:
                    # Cabe: junta no grupo atual
                    acum_linhas.extend(linhas_bloco)
                    acum_len = novo_len
                    acum_fim = fim_b
                else:
                    # Não cabe: fecha grupo atual e abre novo com este bloco
                    flush()
                    acum_linhas.extend(linhas_bloco)
                    acum_len = len(corpo_bloco)
                    acum_ini = ini_b
                    acum_fim = fim_b

    flush()  # fecha eventual grupo de incisos pendente ao final

    # ---------- Montagem dos trechos (regra 6) ----------
    total = len(corpos)
    trechos: list[dict] = []
    for i, corpo in enumerate(corpos, start=1):
        texto_trecho = caput + "\n" + corpo
        ini_raw = corpo_inis[i - 1]
        fim = corpo_fins[i - 1]
        # Avança ini até o primeiro caractere não-vazio (as marcas apontam para
        # o primeiro char não-vazio, não para o início absoluto do bloco)
        ini = ini_raw + len(corpo) - len(corpo.lstrip())
        # Calcula paginas do trecho a partir de marcas_pagina do artigo
        if marcas:
            paginas_trecho = _paginas_do_trecho(ini, fim, marcas)
        else:
            paginas_trecho = artigo["paginas"]
        trechos.append({
            **artigo_base,
            "texto": texto_trecho,
            "paginas": paginas_trecho,
            "id": f"art-{num_artigo}#{i}",
            "parte": i,
            "total_partes": total,
        })

    return trechos
