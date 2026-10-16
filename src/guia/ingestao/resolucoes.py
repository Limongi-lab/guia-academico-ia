"""Divisão de resoluções consolidadas da UFU em artigos vigentes.

Lógica de vigência:
- Unidade marcada com (Revogado pela ...) é descartada.
- Se o mesmo rótulo de unidade aparece duas vezes e a segunda tem
  (Redação dada pela ...), a primeira é descartada (substituída).
- Unidade com (Incluído pela ...) é mantida normalmente.
- As marcações entre parênteses são removidas do texto final, mas a
  resolução citada é salva em "alteracoes".

Cabeçalho/rodapé do SEI são removidos antes de qualquer processamento.
"""

import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Padrões globais
# ---------------------------------------------------------------------------

# Marcador de página inserido pelo extrator de PDF
_PAG_RE = re.compile(r'^=== página (\d+) ===$', re.MULTILINE)

# Linhas de cabeçalho/rodapé do SEI a remover (a ordem importa)
_SEI_PATTERNS = [
    # "18/04/2024, 13:16  SEI/UFU - 5346187 - Resolução"
    re.compile(r'^\d{2}/\d{2}/\d{4}, \d{2}:\d{2}.*$', re.MULTILINE),
    # "SEI/UFU - XXXXXXX - Resolução"
    re.compile(r'^SEI/UFU\s+-\s+\d+\s+-\s+Resolução.*$', re.MULTILINE),
    # URL do controlador do SEI
    re.compile(r'^https://www\.sei\.ufu\.br/sei/controlador\.php.*$', re.MULTILINE),
]

# Início de artigo: "Art. 12." ou "Art. 12º." etc.
_ARTIGO_RE = re.compile(
    r'^(Art\.\s+(\d+)(?:º|o)?\.)',
    re.MULTILINE,
)

# Rótulos internos de uma unidade dentro de um artigo.
# Usamos grupos nomeados para facilitar a identificação.
#   - parágrafo único
#   - § N
#   - inciso romano com travessão ou hífen
_UNIDADE_RE = re.compile(
    r'^('
    r'Parágrafo único'
    r'|§\s*\d+'
    r'|[IVXLCDM]+\s*[–\-]'          # inciso romano + travessão/hífen
    r')',
    re.MULTILINE,
)

# Marcações de alteração (podem estar partidas em duas linhas)
# Capturamos o tipo (Redação dada / Revogado / Incluído) e a resolução citada.
_MARCA_RE = re.compile(
    r'\('
    r'(Redação dada|Revogado|Incluído[ao]?)'
    r'(?:\s+pela\s+Resolução\s+CONGRAD\s+nº\s+(\d+)[^)]*)?'
    r'\)',
    re.DOTALL,
)

# Extrai o número da resolução de uma string de referência completa.
_RESOLUCAO_CITADA_RE = re.compile(
    r'Resolução\s+CONGRAD\s+nº\s+(\d+)',
    re.DOTALL,
)

# ---------------------------------------------------------------------------
# Helpers de limpeza
# ---------------------------------------------------------------------------

def _remover_sei(texto: str) -> str:
    """Remove cabeçalho e rodapé do SEI mantendo marcadores de página."""
    for pat in _SEI_PATTERNS:
        texto = pat.sub('', texto)
    return texto


def _extrair_resolucoes(texto: str) -> list[str]:
    """Retorna lista de strings 'Resolução CONGRAD nº X, de ...' encontradas."""
    return [m.group(0) for m in _RESOLUCAO_CITADA_RE.finditer(texto)]


def _limpar_marcacoes(texto: str) -> str:
    """Remove marcações (Redação dada...), (Revogado...), (Incluído...) do texto.

    As marcações podem estar quebradas em duas linhas — o flag re.DOTALL
    do _MARCA_RE já lida com isso.
    """
    return _MARCA_RE.sub('', texto)


# ---------------------------------------------------------------------------
# Estruturas intermediárias
# ---------------------------------------------------------------------------

class _Unidade(NamedTuple):
    """Trecho de texto com um rótulo e seu tipo de alteração (se houver)."""
    rotulo: str          # ex.: "Parágrafo único", "§ 1º", "II –", "Art."
    texto: str           # texto bruto (com marcações ainda presentes)
    tipo: str            # "", "Redação dada", "Revogado", "Incluído"
    resolucoes: list[str]


# ---------------------------------------------------------------------------
# Lógica de vigência por unidade
# ---------------------------------------------------------------------------

def _tipo_alteracao(texto: str) -> tuple[str, list[str]]:
    """Detecta o tipo de alteração e as resoluções citadas num bloco de texto."""
    m = _MARCA_RE.search(texto)
    if not m:
        return "", []
    tipo = m.group(1)
    resols = _extrair_resolucoes(texto)
    return tipo, resols


def _rotulo_unidade(linha: str) -> str:
    """Retorna o rótulo normalizado da primeira unidade reconhecida na linha."""
    m = _UNIDADE_RE.match(linha)
    if not m:
        return ""
    raw = m.group(1).strip()
    # Normaliza incisos: "II –" e "II -" viram "II"
    raw_norm = re.sub(r'\s*[–\-]\s*$', '', raw).strip()
    return raw_norm


def _aplicar_vigencia(unidades: list[_Unidade]) -> list[_Unidade]:
    """Aplica as regras de vigência a uma lista de unidades.

    Regras:
    1. Unidade Revogada → descarta.
    2. Mesmo rótulo aparece duas vezes e a segunda é "Redação dada" →
       descarta a primeira e mantém a segunda (que já substituiu a anterior).
    3. Incluído → mantém normalmente (apenas remove a marcação no final).
    """
    # Passagem 1: identificar duplicatas por rótulo
    # Guardamos a última ocorrência de cada rótulo e seu índice.
    ultima_ocorrencia: dict[str, int] = {}
    for i, u in enumerate(unidades):
        if u.rotulo:
            ultima_ocorrencia[u.rotulo] = i

    resultado: list[_Unidade] = []
    for i, u in enumerate(unidades):
        # Regra 1: revogado → descarta sempre
        if u.tipo == "Revogado":
            continue

        if u.rotulo and ultima_ocorrencia.get(u.rotulo, i) != i:
            # Há uma ocorrência posterior com o mesmo rótulo.
            # Esta é a versão antiga → descarta (será substituída pela última).
            continue

        resultado.append(u)

    return resultado


# ---------------------------------------------------------------------------
# Divisão em artigos
# ---------------------------------------------------------------------------

def _dividir_em_blocos_de_artigo(texto: str) -> list[tuple[str, str]]:
    """Retorna lista de (numero_artigo, texto_bruto) na ordem do documento."""
    posicoes = [(m.start(), m.group(2)) for m in _ARTIGO_RE.finditer(texto)]
    blocos = []
    for idx, (pos, num) in enumerate(posicoes):
        fim = posicoes[idx + 1][0] if idx + 1 < len(posicoes) else len(texto)
        blocos.append((num, texto[pos:fim]))
    return blocos


def _paginas_do_bloco(bloco: str, pagina_atual: int) -> list[int]:
    """Extrai os números de página referenciados dentro de um bloco de texto.

    Um marcador de página só é contado se houver conteúdo real (texto não-marcador)
    após ele dentro deste bloco. O marcador no final do bloco pertence ao próximo
    artigo, não a este.
    """
    paginas = set()
    for m in _PAG_RE.finditer(bloco):
        # Verifica se há texto real após este marcador dentro do bloco
        texto_apos = bloco[m.end():]
        # Remove outros marcadores e espaços; se sobrar algo, esta página é deste bloco
        texto_real_apos = _PAG_RE.sub('', texto_apos).strip()
        if texto_real_apos:
            paginas.add(int(m.group(1)))
    # Verifica se o bloco começa sem marcador (herdou a página anterior)
    if not _PAG_RE.match(bloco.lstrip()):
        paginas.add(pagina_atual)
    return sorted(paginas)


# ---------------------------------------------------------------------------
# Funções para dividir um artigo em suas unidades internas
# ---------------------------------------------------------------------------

def _dividir_artigo_em_unidades(numero: str, texto_bruto: str) -> list[_Unidade]:
    """Divide o texto bruto de um artigo em unidades (artigo + parágrafos/incisos).

    Cada linha que começa com um rótulo reconhecido inicia uma nova unidade.
    A primeira unidade tem o rótulo "Art.<numero>".
    """
    linhas = texto_bruto.splitlines(keepends=True)
    unidades: list[_Unidade] = []
    bloco_atual: list[str] = []
    rotulo_atual = f"Art.{numero}"

    def _fechar_bloco():
        if not bloco_atual:
            return
        texto_bloco = "".join(bloco_atual).strip()
        if not texto_bloco:
            return
        tipo, resols = _tipo_alteracao(texto_bloco)
        unidades.append(_Unidade(rotulo_atual, texto_bloco, tipo, resols))

    for linha in linhas:
        # Marcadores de página não quebram uma unidade
        if _PAG_RE.match(linha.rstrip()):
            bloco_atual.append(linha)
            continue

        rot = _rotulo_unidade(linha)
        if rot:
            # Nova unidade começa
            _fechar_bloco()
            bloco_atual = [linha]
            rotulo_atual = rot
        else:
            bloco_atual.append(linha)

    _fechar_bloco()
    return unidades


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def dividir_em_artigos(texto: str) -> list[dict]:
    """Transforma o texto de uma resolução consolidada da UFU em uma lista
    de trechos, um por artigo, com apenas a redação VIGENTE.

    Parâmetros
    ----------
    texto : str
        Texto completo extraído de um PDF, com marcadores "=== página N ===".

    Retorna
    -------
    list[dict]
        Cada dict contém:
        - "artigo"    : str  – número do artigo (ex.: "50")
        - "texto"     : str  – redação vigente, sem marcações de alteração
        - "paginas"   : list[int] – páginas onde o artigo aparece
        - "alteracoes": list[str] – resoluções citadas nas marcações
    """
    # 1. Remover cabeçalho/rodapé do SEI
    texto = _remover_sei(texto)

    # 2. Rastrear página corrente para atribuir a blocos sem marcador próprio
    pagina_corrente = 1
    resultado: list[dict] = []

    # 3. Consolidar múltiplas ocorrências do mesmo artigo num único dict
    #    Usamos um dict ordenado: numero → dict parcial
    artigos_vistos: dict[str, dict] = {}

    for num, bloco in _dividir_em_blocos_de_artigo(texto):
        # Atualiza página corrente com a última que aparece antes deste bloco
        pags_antes = [int(m.group(1)) for m in _PAG_RE.finditer(texto[:texto.find(bloco)])]
        if pags_antes:
            pagina_corrente = pags_antes[-1]

        paginas = _paginas_do_bloco(bloco, pagina_corrente)
        # Atualiza página corrente para o próximo bloco
        if paginas:
            pagina_corrente = max(paginas)

        # Divide o artigo em unidades e aplica vigência
        unidades = _dividir_artigo_em_unidades(num, bloco)
        unidades_vigentes = _aplicar_vigencia(unidades)

        # Coleta todas as resoluções citadas (de todas as unidades, inclusive as descartadas)
        # porque queremos registrar o histórico, não só o vigente.
        todas_resolucoes: list[str] = []
        for u in unidades:
            todas_resolucoes.extend(u.resolucoes)

        # Monta texto vigente: concatena unidades, remove marcações e marcadores de página
        texto_vigente = "\n".join(
            _limpar_marcacoes(u.texto) for u in unidades_vigentes
        ).strip()
        # Remove marcadores de página do texto (já foram contabilizados em 'paginas')
        texto_vigente = _PAG_RE.sub('', texto_vigente)
        # Limpa espaços extras deixados pela remoção das marcações e marcadores
        texto_vigente = re.sub(r'\n{3,}', '\n\n', texto_vigente)
        texto_vigente = re.sub(r'[ \t]+\n', '\n', texto_vigente)
        texto_vigente = texto_vigente.strip()

        if num not in artigos_vistos:
            # Primeira vez que vemos este artigo
            artigos_vistos[num] = {
                "artigo": num,
                "texto": texto_vigente,
                "paginas": paginas,
                "alteracoes": list(dict.fromkeys(todas_resolucoes)),
            }
        else:
            # Artigo já existe: esta é uma versão mais nova (Redação dada).
            # A vigência já foi decidida internamente, então simplesmente
            # substituímos o texto pelo resultado já processado desta ocorrência
            # e acumulamos páginas e alterações.
            anterior = artigos_vistos[num]
            paginas_merged = sorted(set(anterior["paginas"]) | set(paginas))
            alteracoes_merged = list(dict.fromkeys(
                anterior["alteracoes"] + list(dict.fromkeys(todas_resolucoes))
            ))
            artigos_vistos[num] = {
                "artigo": num,
                "texto": texto_vigente,      # texto da ocorrência mais recente (vigente)
                "paginas": paginas_merged,
                "alteracoes": alteracoes_merged,
            }

    return list(artigos_vistos.values())
