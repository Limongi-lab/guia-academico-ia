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
    r'^[ \t]*Art\.?\s+(\d+)(?:(?:º|o)\.?|\.(?=\s)|\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ]))',
    re.MULTILINE,
)

# Aspas de fechamento após ponto que delimitam o corpo do último artigo
# (ex.: '.".' ou '."' em citações legislativas como '"Art. 216 ...".').
_CAUDA_RE = re.compile(r'\.["\u201c\u201d]\.?\s*$', re.MULTILINE)

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

    Marcadores de página são removidos antes de aplicar o regex para que
    marcações partidas entre páginas sejam reconhecidas integralmente.
    re.DOTALL + re.IGNORECASE já estão no _MARCA_RE compilado.
    """
    return _MARCA_RE.sub('', _PAG_RE.sub('', texto))


# ---------------------------------------------------------------------------
# Extração de títulos estruturais do bloco bruto
# ---------------------------------------------------------------------------

# Linha isolada em maiúsculas começando com DO/DA/DOS/DAS (título de seção avulso).
# Ex.: "DOS EDITAIS E SUAS PARTES". Deve estar sozinha na linha.
_SECAO_AVULSA_RE = re.compile(
    r'^(D(?:O|A|OS|AS)\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ ]+)\s*$',
    re.MULTILINE,
)

# Prefixos que impedem uma linha de ser o "nome" de um título estrutural
_NOME_INVALIDO_RE = re.compile(
    r'^(?:Art\.?|§|Parágrafo|[IVXLCDM]+\s*[.–\-])',
    re.IGNORECASE,
)


def _extrair_titulos(bloco: str) -> tuple[str, str, str]:
    """Remove linhas de título do bloco; retorna (bloco_limpo, capitulo, secao).

    Títulos estruturais: linhas iniciadas por CAPÍTULO/TÍTULO/SEÇÃO/SUBSEÇÃO
    (qualquer caixa). O nome pode estar na linha seguinte ou após uma ou mais
    linhas em branco. O nome é válido se começa com D+(o|a|os|as) ou estiver
    todo em maiúsculas, e não começar com Art/§/Parágrafo/numeral romano.

    Linhas isoladas DO/DA/DOS/DAS em maiúsculas (sem palavra-chave estrutural
    antes) viram seção avulsa (campo 'secao').

    Hierarquia:
    - TÍTULO  → zera capitulo e secao; define novo capitulo.
    - CAPÍTULO→ zera secao; define novo capitulo.
    - SEÇÃO/SUBSEÇÃO → define secao.
    """
    # Trabalha linha a linha para respeitar linhas em branco entre cabeçalho e nome.
    linhas = bloco.split('\n')
    resultado: list[str] = []
    capitulo: str | None = None  # None = sem alteração; "" = zerar; str = novo valor
    secao = ''
    i = 0
    palavra_chave_re = re.compile(
        r'^[ \t]*(CAP[ÍI]TULO|T[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O)\b',
        re.IGNORECASE,
    )
    nome_re = re.compile(
        r'^[ \t]*(?:D(?:O|A|OS|AS)\b|[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ]{2})',
    )

    while i < len(linhas):
        linha = linhas[i]
        m_kw = palavra_chave_re.match(linha)
        if m_kw:
            cabecalho = linha.strip()
            kw = m_kw.group(1).upper()
            # Procura próxima linha não-vazia para ser o nome
            j = i + 1
            while j < len(linhas) and not linhas[j].strip():
                j += 1
            nome = ''
            if j < len(linhas):
                candidato = linhas[j].strip()
                # Valida: começa com D+(o/a/os/as) OU todo em maiúsculas (sem acento minúsculo)
                # E NÃO começa com Art/§/Parágrafo/numeral romano
                parece_nome = (
                    re.match(r'^D(?:o|a|os|as|O|A|OS|AS)\b', candidato)
                    or (candidato == candidato.upper() and candidato.strip())
                )
                if parece_nome and not _NOME_INVALIDO_RE.match(candidato):
                    nome = candidato
                    # Remove linhas em branco entre cabeçalho e nome do resultado
                    # (já não serão adicionadas pois avançamos i até j)
                    i = j  # i será incrementado no final do loop → j+1

            titulo_completo = f"{cabecalho} {nome}".strip() if nome else cabecalho

            # Atualiza hierarquia
            if 'TIT' in kw or 'T\u00cdT' in kw or kw.startswith('T'):
                # TÍTULO: zera capitulo e secao (não vira o novo capitulo)
                capitulo = ''
                secao = ''
            elif 'CAP' in kw:
                # CAPÍTULO: define novo capitulo, zera secao
                capitulo = titulo_completo
                secao = ''
            else:
                # SEÇÃO / SUBSEÇÃO
                secao = titulo_completo
            i += 1
            continue

        # Verifica linha avulsa DO/DA/DOS/DAS em maiúsculas
        m_av = _SECAO_AVULSA_RE.match(linha)
        if m_av:
            secao = m_av.group(1).strip()
            i += 1
            continue

        resultado.append(linha)
        i += 1

    return '\n'.join(resultado), capitulo, secao


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
    """Detecta o tipo de alteração e as resoluções citadas num bloco de texto.

    Marcadores de página são removidos antes da busca para que marcações
    partidas entre páginas sejam detectadas (os marcadores não contêm ')',
    mas interrompem os \\s+ que ligam as palavras da marcação).
    """
    texto_s = _PAG_RE.sub('', texto)
    m = _MARCA_RE.search(texto_s)
    if not m:
        return '', []
    tipo = m.group(1)
    resols = _extrair_resolucoes(texto_s)
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

def _dividir_em_blocos_de_artigo(texto: str) -> list[tuple[int, str, str]]:
    """Retorna lista de (pos, numero_artigo, texto_bruto) na ordem do documento.

    Filtro monotônico: rejeita candidatos com número MENOR que o último aceito,
    para evitar tratar citações internas ("conforme art. 5º desta Norma") como
    novos artigos. Números iguais são permitidos (artigo com redação substituída).

    Regra de preâmbulo de aprovação: se aparece um "Art. 1" e o maior número
    visto até agora é <= 10, tudo que veio antes é preâmbulo e é descartado.
    Se o maior número visto já for > 10, é citação — o filtro monotônico cuida.
    """
    candidatos = [(m.start(), m.group(1)) for m in _ARTIGO_RE.finditer(texto)]

    posicoes: list[tuple[int, str]] = []  # (pos_no_texto, num_str)
    ultimo_num = -1
    for pos, num_str in candidatos:
        n = int(num_str)
        if n == 1 and ultimo_num != -1 and ultimo_num <= 10:
            # Novo Art. 1 após artigos de preâmbulo (máx <= 10): reiniciar.
            posicoes = []
            ultimo_num = -1
        if n >= ultimo_num:          # aceita igual (duplicata vigente) ou maior
            posicoes.append((pos, num_str))
            if n > ultimo_num:       # régua só avança quando cresce
                ultimo_num = n

    blocos = []
    for idx, (pos, num) in enumerate(posicoes):
        fim = posicoes[idx + 1][0] if idx + 1 < len(posicoes) else len(texto)
        blocos.append((pos, num, texto[pos:fim]))
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
    # 2. Normalizar espaço inseparável (U+00A0) → espaço comum antes de qualquer
    #    regex, para que linhas como " \u00a0Art. 18. Texto" sejam reconhecidas.
    texto = texto.replace('\u00a0', ' ')

    pagina_corrente = 1
    artigos_vistos: dict[str, dict] = {}

    # Metadados estruturais correntes (atualizados ao processar cada bloco)
    capitulo_corrente = ''
    secao_corrente = ''

    # Inicializa metadados com títulos que aparecem ANTES do primeiro artigo.
    blocos = _dividir_em_blocos_de_artigo(texto)
    if blocos:
        primeiro_pos = blocos[0][0]
        prefixo_global = texto[:primeiro_pos]
        _, cap_init, sec_init = _extrair_titulos(prefixo_global)
        if cap_init is not None:
            capitulo_corrente = cap_init
            secao_corrente = sec_init
        elif sec_init:
            secao_corrente = sec_init

    for pos_bloco, num, bloco in blocos:
        # Atualiza página corrente com a última página vista antes deste bloco
        pags_antes = [int(m.group(1)) for m in _PAG_RE.finditer(texto[:pos_bloco])]
        if pags_antes:
            pagina_corrente = pags_antes[-1]

        paginas = _paginas_do_bloco(bloco, pagina_corrente)
        if paginas:
            pagina_corrente = max(paginas)

        # Separar o bloco em:
        #   prefixo: texto antes de "Art. N" (pode conter títulos estruturais)
        #   corpo   : de "Art. N" em diante
        # Usamos _ARTIGO_RE para achar o início do "Art. N" dentro do bloco.
        m_art = _ARTIGO_RE.search(bloco)
        if m_art:
            prefixo = bloco[:m_art.start()]
            corpo = bloco[m_art.start():]
        else:
            prefixo = ''
            corpo = bloco

        # Títulos no prefixo → atualizam metadados do ARTIGO CORRENTE.
        if prefixo.strip():
            _, cap_pre, sec_pre = _extrair_titulos(prefixo)
            if cap_pre is not None:
                capitulo_corrente = cap_pre
                secao_corrente = sec_pre
            elif sec_pre:
                secao_corrente = sec_pre

        # Títulos no corpo → serão propagados para artigos SEGUINTES.
        bloco_sem_titulos, cap_encontrado, sec_encontrada = _extrair_titulos(corpo)

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
            # Mesmo revogado, propaga metadados do corpo para o próximo artigo.
            if cap_encontrado is not None:
                capitulo_corrente = cap_encontrado
                secao_corrente = sec_encontrada
            elif sec_encontrada:
                secao_corrente = sec_encontrada
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
        # Títulos encontrados no CORPO deste bloco pertencem aos artigos SEGUINTES.
        if cap_encontrado is not None:
            capitulo_corrente = cap_encontrado
            secao_corrente = sec_encontrada
        elif sec_encontrada:
            secao_corrente = sec_encontrada

    artigos = list(artigos_vistos.values())
    # Truncar cauda do ÚLTIMO artigo: remove texto posterior à primeira linha
    # que termina com aspas de fechamento após ponto ('.".' ou '."'),
    # descartando a resolução de aprovação, assinaturas e referências de processo.
    if artigos:
        ultimo = artigos[-1]
        artigos[-1] = {**ultimo, 'texto': _truncar_cauda(ultimo['texto'])}
    return artigos


def _truncar_cauda(texto: str) -> str:
    """Remove a cauda após o corpo do último artigo.

    Encontra a primeira linha que termina com aspas de fechamento após ponto
    ('.".', '."', '.".', '."'), mantém o ponto e descarta o restante.
    Se nenhuma linha terminar assim, devolve o texto intacto.
    """
    m = _CAUDA_RE.search(texto)
    if not m:
        return texto
    # m.start() aponta para o '.' antes das aspas; +1 inclui o ponto e exclui as aspas.
    return texto[:m.start() + 1].rstrip()
