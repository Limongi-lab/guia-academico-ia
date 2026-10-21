"""Extração da tabela de atividades complementares da página FAGEN.

Contrato público:
    extrair_atividades(html: str) -> list[dict]

Cada dict contém:
    codigo       (str)  – ex. "ATCO0369"
    atividade    (str)  – nome da atividade, espaços normalizados
    limite_horas (int)  – número inteiro de horas
    comprovacao  (str)  – texto de comprovação, espaços normalizados

Regras:
- Identifica a tabela correta pelo cabeçalho que contenha "Código" (th ou td).
- Ignora linhas cujo código não case com [A-Z]{4}\\d{4} após strip/upper.
- Normaliza todo espaço em branco (inclusive NBSP U+00A0) para espaço simples.
- Levanta ValueError com o código no texto se limite_horas for ilegível.
- Linhas duplicadas são mantidas na ordem original (não são removidas em silêncio).
"""

import re

import lxml.html

# Padrão de código válido: 4 letras maiúsculas + 4 dígitos
_CODIGO_RE = re.compile(r"^[A-Z]{4}\d{4}$")
# Captura o número de horas: "30 horas", "1 hora", "  40   horas "
_HORAS_RE = re.compile(r"(\d+)\s+horas?", re.IGNORECASE)


def _texto(celula) -> str:
    """Junta todos os fragmentos de texto de um elemento, separados por espaço,
    e normaliza múltiplos espaços (incluindo NBSP) para um único espaço."""
    partes = " ".join(celula.itertext())
    # Substitui NBSP (U+00A0) e qualquer sequência de espaços/tabs/newlines por espaço
    normalizado = re.sub(r"[\u00a0\s]+", " ", partes)
    return normalizado.strip()


def _tem_cabecalho_atividades(tabela) -> bool:
    """Retorna True se a primeira linha da tabela contiver 'Código' em alguma célula."""
    primeira_linha = tabela.find(".//tr")
    if primeira_linha is None:
        return False
    for celula in primeira_linha.findall("th") + primeira_linha.findall("td"):
        if "digo" in _texto(celula):  # cobre "Código" e variações de encoding
            return True
    return False


def extrair_atividades(html: str) -> list[dict]:
    """Extrai as atividades complementares da tabela FAGEN a partir do HTML bruto.

    Args:
        html: String com o HTML completo da página.

    Returns:
        Lista de dicts com chaves: codigo, atividade, limite_horas, comprovacao.
        Preserva a ordem da página. Linhas sem código ATCO válido são ignoradas.
        Levanta ValueError se limite_horas for ilegível para um código válido.
    """
    doc = lxml.html.fromstring(html)

    # Localiza a tabela correta pelo cabeçalho
    tabela_alvo = None
    for tabela in doc.findall(".//table"):
        if _tem_cabecalho_atividades(tabela):
            tabela_alvo = tabela
            break

    if tabela_alvo is None:
        return []

    resultado = []
    for tr in tabela_alvo.findall(".//tbody/tr"):
        tds = tr.findall("td")
        if len(tds) < 4:
            continue  # linhas colspanned ou incompletas

        codigo_bruto = _texto(tds[0]).upper().strip()
        if not _CODIGO_RE.match(codigo_bruto):
            continue  # linha de totais, observações, etc.

        codigo = codigo_bruto
        atividade = _texto(tds[1])
        limite_texto = _texto(tds[2])
        comprovacao = _texto(tds[3])

        m = _HORAS_RE.search(limite_texto)
        if not m:
            raise ValueError(
                f"Limite de horas ilegível para {codigo!r}: {limite_texto!r}"
            )
        limite_horas = int(m.group(1))

        resultado.append(
            {
                "codigo": codigo,
                "atividade": atividade,
                "limite_horas": limite_horas,
                "comprovacao": comprovacao,
            }
        )

    return resultado
