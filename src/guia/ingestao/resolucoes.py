"""Divisão de resoluções consolidadas da UFU em artigos vigentes.

Lógica de vigência:
- Unidade marcada com (Revogado pela ...) é descartada.
- Se o mesmo rótulo de unidade aparece duas vezes e a segunda tem
  (Redação dada pela ...), a primeira é descartada (substituída).
- Unidade com (Incluído pela ...) é mantida normalmente.
- As marcações entre parênteses são removidas do texto final, mas a
  resolução citada é salva em "alteracoes".

Cabeçalho/rodapé do SEI, contadores de página e títulos estruturais
são removidos antes de qualquer processamento de vigência.
"""

import re
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Padrões globais
# ---------------------------------------------------------------------------

# Marcador de página inserido pelo extrator de PDF
_PAG_RE = re.compile(r'^=== página (\d+) ===$', re.MULTILINE)

# Linhas de cabeçalho/rodapé do SEI a remover (ordem importa)
_SEI_PATTERNS = [
    # "18/04/2024, 13:16  SEI/UFU - 5346187 - Resolução"
    re.compile(r'^\d{2}/\d{2}/\d{4}, \d{2}:\d{2}.*$', re.MULTILINE),
    # "SEI/UFU - XXXXXXX - Resolução"
    re.compile(r'^SEI/UFU\s+-\s+\d+\s+-\s+Resolução.*$', re.MULTILINE),
    # URL do controlador do SEI
    re.compile(r'^https://www\.sei\.ufu\.br/sei/controlador\.php.*$', re.MULTILINE),
    # Contador de páginas estilo "16/52" em linha isolada (rodapé do SEI impresso).
    # Removido aqui para não partir marcações de alteração ao meio.
    re.compile(r'^\d+/\d+\s*$', re.MULTILINE),
]

# Início de artigo — quatro formatos aceitos:
#   a) "Art. 10. Texto..."   ponto após número obrigatório (arts. 10+)
#   b) "Art. 1º Texto..."    ordinal sem ponto final (arts. 1-9)
#   c) "Art 202. Texto..."   "Art" sem ponto (variação tipográfica do PDF)
#   d) "Art. 13  Texto..."   número seguido só de espaços, sem ponto/ordinal
#      (formato do Regimento UNIUBE); exige letra MAIÚSCULA na próxima palavra
#      para não tratar citações como "Art. 18 desta Norma" como novo artigo.
# O lookahead (?=\s) exige espaço/quebra após o terminador — evita citações falsas.
# Grupo 1 captura apenas os dígitos; ordinal e ponto são consumidos mas descartados.
_ARTIGO_RE = re.compile(
    r'^Art\.?\s+(\d+)(?:(?:º|o)\.?|\.(?=\s)|\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ]))',
    re.MULTILINE,
)

# Títulos estruturais (CAPÍTULO, TÍTULO, SEÇÃO, SUBSEÇÃO em qualquer caixa)
# e a linha de nome que os segue. São removidos do artigo anterior e viram
# metadado dos artigos seguintes.
_TITULO_RE = re.compile(
    r'^(CAP[ÍI]TULO|T[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\b.*',
    re.IGNORECASE | re.MULTILINE,
)

# Rótulos internos de uma unidade dentro de um artigo:
#   - Parágrafo único
#   - § N  (parágrafo numerado)
#   - Inciso romano + travessão "–" ou hífen "-"
_UNIDADE_RE = re.compile(
    r'^('
    r'Parágrafo único'
    r'|§\s*\d+'
    r'|[IVXLCDM]+\s*[–\-]'
    r')',
    re.MULTILINE,
)

# Marcações de alteração.
# Aceita "nº" ou "Nº" (re.IGNORECASE); "\s+" abrange quebras de linha e
# espaços múltiplos (marcações partidas pelo PDF ou pelo contador de páginas).
_MARCA_RE = re.compile(
    r'\('
    r'(Redação dada|Revogado|Incluído[ao]?)'
    r'(?:\s+pela\s+Resolução\s+CONGRAD\s+[Nn][Oo º]+\s*(\d+)[^)]*)?'
    r'\)',
    re.DOTALL | re.IGNORECASE,
)

# Extrai "Resolução CONGRAD nº X" (case-insensitive para Nº/nº).
_RESOLUCAO_CITADA_RE = re.compile(
    r'Resolução\s+CONGRAD\s+[Nn][Oo º]+\s*(\d+)',
    re.DOTALL | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Helpers de limpeza
# ---------------------------------------------------------------------------

def _remover_sei(texto: str) -> str:
    """Remove cabeçalho, rodapé e contadores do SEI, mantendo marcadores de página."""
    for pat in _SEI_PATTERNS:
        texto = pat.sub('', texto)
    return texto


def _extrair_resolucoes(texto: str) -> list[str]:
    """Retorna lista com cada ocorrência de 'Resolução CONGRAD nº X...' encontrada."""
    return [m.group(0) for m in _RESOLUCAO_CITADA_RE.finditer(texto)]


def _limpar_marcacoes(texto: str) -> str:
    """Remove marcações (Redação dada...), (Revogado...), (Incluído...) do texto.

    re.DOTALL + re.IGNORECASE já estão no _MARCA_RE compilado, portanto
    marcações partidas em múltiplas linhas e variações de caixa são tratadas.
    """
    return _MARCA_RE.sub('', texto)


# ---------------------------------------------------------------------------
# Extração de títulos estruturais do bloco bruto
# ---------------------------------------------------------------------------

def _extrair_titulos(bloco: str) -> tuple[str, str]:
    """Remove linhas de título do bloco e retorna (bloco_limpo, titulo_concatenado).

    Títulos: linhas iniciadas por CAPÍTULO/TÍTULO/SEÇÃO/SUBSEÇÃO (qualquer caixa)
    mais a linha imediatamente seguinte com o nome (ex.: "DO TRANCAMENTO DE MATRÍCULA").
    As duas linhas são concatenadas com espaço para formar o metadado.

    Estratégia: cada match do _TITULO_RE captura apenas a linha da palavra-chave;
    a linha de nome fica na linha seguinte — capturamos ambas com uma versão
    estendida do padrão.
    """
    # Padrão que captura palavra-chave + resto da linha + linha seguinte (nome)
    titulo_bloco_re = re.compile(
        r'^((?:CAP[ÍI]TULO|T[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\b[^\n]*)\n([^\n]+)',
        re.IGNORECASE | re.MULTILINE,
    )

    titulos: list[str] = []

    def _substituir(m: re.Match) -> str:
        linha_chave = m.group(1).strip()
        linha_nome = m.group(2).strip()
        titulos.append(f"{linha_chave} {linha_nome}")
        return ''   # remove do bloco

    bloco_limpo = titulo_bloco_re.sub(_substituir, bloco)
    titulo = ' '.join(titulos).strip()
    return bloco_limpo, titulo


# ---------------------------------------------------------------------------
# Estruturas intermediárias
# ---------------------------------------------------------------------------

class _Unidade(NamedTuple):
    """Trecho de texto com um rótulo e seu tipo de alteração (se houver)."""
    rotulo: str          # ex.: "Parágrafo único", "§ 1º", "II –", "Art.<num>"
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
        return '', []
    tipo = m.group(1)
    resols = _extrair_resolucoes(texto)
    return tipo, resols


def _rotulo_unidade(linha: str) -> str:
    """Retorna o rótulo normalizado da primeira unidade reconhecida na linha."""
    m = _UNIDADE_RE.match(linha)
    if not m:
        return ''
    raw = m.group(1).strip()
    # Normaliza incisos: "II –" e "II -" viram "II"
    return re.sub(r'\s*[–\-]\s*$', '', raw).strip()


def _aplicar_vigencia(unidades: list[_Unidade]) -> list[_Unidade]:
    """Aplica as regras de vigência a uma lista de unidades.

    Regras:
    1. Unidade Revogada → descarta sempre.
    2. Mesmo rótulo aparece duas vezes e a segunda tem "Redação dada" →
       descarta a primeira (versão antiga) e mantém a segunda (vigente).
    3. Unidade com "Incluído" → mantida; apenas a marcação é removida do texto.
    """
    # Última posição de cada rótulo: permite identificar versões antigas.
    ultima_ocorrencia: dict[str, int] = {}
    for i, u in enumerate(unidades):
        if u.rotulo:
            ultima_ocorrencia[u.rotulo] = i

    resultado: list[_Unidade] = []
    for i, u in enumerate(unidades):
        # Regra 1: revogado → descarta sempre
        if u.tipo == 'Revogado':
            continue
        # Regra 2: se há ocorrência posterior do mesmo rótulo, esta é versão antiga
        if u.rotulo and ultima_ocorrencia.get(u.rotulo, i) != i:
            continue
        resultado.append(u)

    return resultado


# ---------------------------------------------------------------------------
# Divisão em artigos
# ---------------------------------------------------------------------------

def _dividir_em_blocos_de_artigo(texto: str) -> list[tuple[str, str]]:
    """Retorna lista de (numero_artigo, texto_bruto) na ordem do documento.

    Filtro monotônico: rejeita candidatos com número MENOR que o último aceito,
    para evitar tratar citações internas ("conforme art. 5º desta Norma") como
    novos artigos. Números iguais são permitidos (artigo com redação substituída).
    """
    candidatos = [(m.start(), m.group(1)) for m in _ARTIGO_RE.finditer(texto)]

    posicoes: list[tuple[int, str]] = []
    ultimo_num = -1
    for pos, num_str in candidatos:
        n = int(num_str)
        if n >= ultimo_num:          # aceita igual (duplicata vigente) ou maior
            posicoes.append((pos, num_str))
            if n > ultimo_num:       # régua só avança quando cresce
                ultimo_num = n

    blocos = []
    for idx, (pos, num) in enumerate(posicoes):
        fim = posicoes[idx + 1][0] if idx + 1 < len(posicoes) else len(texto)
        blocos.append((num, texto[pos:fim]))
    return blocos


def _paginas_do_bloco(bloco: str, pagina_atual: int) -> list[int]:
    """Extrai os números de página referenciados dentro de um bloco de texto.

    Um marcador de página só conta se houver conteúdo real após ele no bloco;
    o marcador final pertence ao próximo artigo.
    """
    paginas: set[int] = set()
    for m in _PAG_RE.finditer(bloco):
        texto_apos = _PAG_RE.sub('', bloco[m.end():]).strip()
        if texto_apos:
            paginas.add(int(m.group(1)))
    # Bloco sem marcador próprio herda a página corrente
    if not _PAG_RE.match(bloco.lstrip()):
        paginas.add(pagina_atual)
    return sorted(paginas)


# ---------------------------------------------------------------------------
# Divisão de um artigo em suas unidades internas
# ---------------------------------------------------------------------------

def _dividir_artigo_em_unidades(numero: str, texto_bruto: str) -> list[_Unidade]:
    """Divide o texto bruto de um artigo em unidades (artigo + parágrafos/incisos).

    Cada linha que começa com um rótulo reconhecido inicia uma nova unidade.
    A primeira unidade tem o rótulo "Art.<numero>".
    Marcadores de página não quebram unidades (são passados adiante).
    """
    linhas = texto_bruto.splitlines(keepends=True)
    unidades: list[_Unidade] = []
    bloco_atual: list[str] = []
    rotulo_atual = f'Art.{numero}'

    def _fechar_bloco() -> None:
        if not bloco_atual:
            return
        texto_bloco = ''.join(bloco_atual).strip()
        if not texto_bloco:
            return
        tipo, resols = _tipo_alteracao(texto_bloco)
        unidades.append(_Unidade(rotulo_atual, texto_bloco, tipo, resols))

    for linha in linhas:
        if _PAG_RE.match(linha.rstrip()):   # marcador de página → não quebra unidade
            bloco_atual.append(linha)
            continue
        rot = _rotulo_unidade(linha)
        if rot:
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
        - "artigo"    : str       – número do artigo (ex.: "50")
        - "texto"     : str       – redação vigente, sem marcações nem títulos
        - "paginas"   : list[int] – páginas onde o artigo aparece
        - "alteracoes": list[str] – resoluções citadas nas marcações
        - "capitulo"  : str       – último cabeçalho CAPÍTULO/TÍTULO visto (ou "")
        - "secao"     : str       – última SEÇÃO/SUBSEÇÃO vista (ou ""); resetada
                                    quando começa novo capítulo
    """
    # 1. Remover cabeçalho/rodapé/contadores do SEI antes de qualquer análise.
    #    O contador "46/52" é removido aqui para não partir marcações de alteração.
    texto = _remover_sei(texto)

    pagina_corrente = 1
    artigos_vistos: dict[str, dict] = {}

    # Metadados estruturais correntes (atualizados ao processar cada bloco)
    capitulo_corrente = ''
    secao_corrente = ''

    for num, bloco in _dividir_em_blocos_de_artigo(texto):
        # Atualiza página corrente com a última página vista antes deste bloco
        pags_antes = [int(m.group(1)) for m in _PAG_RE.finditer(texto[:texto.find(bloco)])]
        if pags_antes:
            pagina_corrente = pags_antes[-1]

        paginas = _paginas_do_bloco(bloco, pagina_corrente)
        if paginas:
            pagina_corrente = max(paginas)

        # Extrair e remover títulos estruturais do bloco.
        # Títulos encontrados aqui pertencem ao próximo artigo, não a este.
        bloco_sem_titulos, titulo_encontrado = _extrair_titulos(bloco)

        # Divide em unidades e aplica vigência
        unidades = _dividir_artigo_em_unidades(num, bloco_sem_titulos)
        unidades_vigentes = _aplicar_vigencia(unidades)

        # Todas as resoluções citadas (inclusive das unidades descartadas) → histórico
        todas_resolucoes: list[str] = []
        for u in unidades:
            todas_resolucoes.extend(u.resolucoes)

        # Monta texto vigente: remove marcações e marcadores de página
        texto_vigente = '\n'.join(
            _limpar_marcacoes(u.texto) for u in unidades_vigentes
        ).strip()
        texto_vigente = _PAG_RE.sub('', texto_vigente)
        texto_vigente = re.sub(r'\n{3,}', '\n\n', texto_vigente)
        texto_vigente = re.sub(r'[ \t]+\n', '\n', texto_vigente)
        texto_vigente = texto_vigente.strip()

        # Artigo completamente revogado → texto vazio → não entra no resultado.
        if not texto_vigente:
            continue

        if num not in artigos_vistos:
            artigos_vistos[num] = {
                'artigo': num,
                'texto': texto_vigente,
                'paginas': paginas,
                'alteracoes': list(dict.fromkeys(todas_resolucoes)),
                'capitulo': capitulo_corrente,
                'secao': secao_corrente,
            }
        else:
            # Artigo já visto: versão mais nova (Redação dada) substitui o texto.
            # Páginas e alterações são acumuladas de todas as ocorrências.
            anterior = artigos_vistos[num]
            artigos_vistos[num] = {
                'artigo': num,
                'texto': texto_vigente,
                'paginas': sorted(set(anterior['paginas']) | set(paginas)),
                'alteracoes': list(dict.fromkeys(
                    anterior['alteracoes'] + list(dict.fromkeys(todas_resolucoes))
                )),
                'capitulo': capitulo_corrente,
                'secao': secao_corrente,
            }

        # Atualiza metadados estruturais APÓS registrar o artigo corrente.
        # Títulos encontrados neste bloco pertencem aos artigos SEGUINTES.
        if titulo_encontrado:
            palavra = titulo_encontrado.split()[0].upper()
            if any(kw in palavra for kw in ('CAP', 'TIT', 'TÍT')):
                # Novo capítulo: zera a seção
                capitulo_corrente = titulo_encontrado
                secao_corrente = ''
            else:
                # Seção/Subseção: mantém o capítulo, atualiza seção
                secao_corrente = titulo_encontrado

    return list(artigos_vistos.values())
