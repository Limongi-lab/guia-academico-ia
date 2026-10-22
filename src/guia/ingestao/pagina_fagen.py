"""Extração de páginas de serviço da FAGEN (Drupal) a partir do HTML bruto.

Contrato público:
    extrair_pagina_fagen(html: str, url: str | None = None) -> dict

Chaves do dict retornado:
    titulo          (str)
    publicado_em    (str ISO "AAAA-MM-DD" ou None)
    atualizado_em   (str ISO "AAAA-MM-DD" ou None)
    publico_alvo    (list[str])
    curso           (list[str])
    assunto         (list[str])
    secoes          (list[{"titulo": str, "texto": str}])  – ordem de página
    anexos          (list[{"texto": str, "url": str, "tipo": str}])
    contato         ({"setor", "email", "telefone", "ramal"} ou None)

Decisões de implementação:
- Usamos lxml.html.document_fromstring (reconhece HTML5 malformado).
- Script e style são removidos antes de qualquer extração.
- Campos de texto: divs com classe field-type-text-long ou field-type-text-with-summary,
  em ordem de documento; rótulo = div.field-label sem os dois pontos finais; body sem rótulo.
- Conversão para texto: <p> e <li> geram blocos; <br> vira \n; NBSP normalizado;
  parágrafos vazios descartados; blocos separados por linha em branco (\n\n).
- Listas: cada <li> vira linha começando com "- ".
- Anexos: coletados de todos os campos de texto + tabela field-name-field-anexo;
  ignorados mailto:, tel:, #, whatsapp:; tornados absolutos com urljoin;
  deduplicados por (host sem "www.", path), mantendo a primeira ocorrência.
- Tipo de anexo: extensão do path ou "pagina".
- Contato: extraído do campo field-name-field-unidade-superior.
- Título: apenas de div.field-name-title h1; ausente → ValueError.
"""

import re
from urllib.parse import urljoin, urlparse

import lxml.html

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_NBSP = "\u00a0"
_EXT_CONHECIDAS = {
    "pdf", "doc", "docx", "xls", "xlsx", "odt", "ods", "odp",
    "ppt", "pptx", "zip", "rar", "txt", "csv",
}
_IGNORAR_PREFIXOS = ("mailto:", "tel:", "whatsapp:", "#")
_CLASSE_BODY = "field-name-body"
_CAMPO_TAXONOMIA = {
    "field-name-field-publico-alvo": "publico_alvo",
    "field-name-field-curso": "curso",
    "field-name-field-assunto": "assunto",
}


# ---------------------------------------------------------------------------
# Helpers gerais
# ---------------------------------------------------------------------------

def _normalizar_espaco(texto: str) -> str:
    return re.sub(r"[\u00a0\s]+", " ", texto).strip()


def _chave_dedup(url: str) -> tuple[str, str]:
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/")
    return (host, path)


def _tipo_de_url(url: str) -> str:
    path = urlparse(url).path
    nome = path.split("/")[-1]
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    return ext if ext in _EXT_CONHECIDAS else "pagina"


def _remover_tags(doc) -> None:
    for tag in doc.xpath(".//script | .//style"):
        tag.getparent().remove(tag)


# ---------------------------------------------------------------------------
# Conversão de HTML → texto estruturado
# ---------------------------------------------------------------------------

def _texto_inline(el) -> str:
    """Coleta texto inline recursivamente; <br> vira \n."""
    partes: list[str] = []
    if el.text:
        partes.append(el.text.replace(_NBSP, " "))
    for filho in el:
        if filho.tag == "br":
            partes.append("\n")
        else:
            partes.append(_texto_inline(filho))
        if filho.tail:
            partes.append(filho.tail.replace(_NBSP, " "))
    return "".join(partes)


def _elem_para_blocos(elem) -> list[str]:
    """Converte um elemento em lista de blocos de texto."""
    blocos: list[str] = []

    def _visitar(el):
        tag = el.tag if isinstance(el.tag, str) else ""

        if tag in ("ul", "ol"):
            linhas: list[str] = []
            for li in el.findall(".//li"):
                t = _normalizar_espaco(_texto_inline(li))
                if t:
                    linhas.append(f"- {t}")
            if linhas:
                blocos.append("\n".join(linhas))
            return  # não descer nos filhos

        if tag == "p":
            t = _normalizar_espaco(_texto_inline(el))
            if t:
                blocos.append(t)
            return

        for filho in el:
            _visitar(filho)

    _visitar(elem)
    return blocos


def _campo_para_texto(field_div) -> str:
    items = field_div.cssselect("div.field-items div.field-item")
    if not items:
        return ""
    blocos: list[str] = []
    for item in items:
        blocos.extend(_elem_para_blocos(item))
    blocos = [b.strip() for b in blocos if b.strip()]
    return "\n\n".join(blocos)


# ---------------------------------------------------------------------------
# Extração de anexos
# ---------------------------------------------------------------------------

def _links_de_elem(elem) -> list[tuple[str, str]]:
    links = []
    for a in elem.cssselect("a[href]"):
        href = (a.get("href") or "").strip()
        texto = _normalizar_espaco("".join(a.itertext()))
        if href:
            links.append((texto, href))
    return links


def _processar_links(
    raw_links: list[tuple[str, str]],
    base_url: str | None,
    vistos: dict[tuple, dict],
) -> list[dict]:
    novos: list[dict] = []
    for texto, href in raw_links:
        if any(href.startswith(p) for p in _IGNORAR_PREFIXOS):
            continue
        url = urljoin(base_url, href) if base_url else href
        chave = _chave_dedup(url)
        if chave in vistos:
            continue
        anexo = {"texto": texto, "url": url, "tipo": _tipo_de_url(url)}
        vistos[chave] = anexo
        novos.append(anexo)
    return novos


# ---------------------------------------------------------------------------
# Extração de contato
# ---------------------------------------------------------------------------

def _extrair_contato(doc) -> dict | None:
    campo = doc.cssselect("div.field-name-field-unidade-superior")
    if not campo:
        return None
    bloco = campo[0]

    setor = ""
    titulo_emb = bloco.cssselect("div.field-name-title a")
    if titulo_emb:
        setor = _normalizar_espaco("".join(titulo_emb[0].itertext()))

    email = telefone = ramal = ""
    info = bloco.cssselect("div.field-name-info-contato-2")
    if info:
        for div in info[0].cssselect("div"):
            texto_div = _normalizar_espaco("".join(div.itertext()))
            if "@" in texto_div and not email:
                m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", texto_div)
                if m:
                    email = m.group(0)
            elif re.search(r"\+\d", texto_div) and not telefone:
                m = re.search(r"[\+\d][\d\s\-]+", texto_div)
                if m:
                    telefone = m.group(0).strip()
            elif "Ramal" in texto_div and not ramal:
                m = re.search(r"Ramal[:\s]+(\d+)", texto_div, re.IGNORECASE)
                if m:
                    ramal = m.group(1)

    if not setor and not email:
        return None

    return {"setor": setor, "email": email, "telefone": telefone, "ramal": ramal}


# ---------------------------------------------------------------------------
# Extração de datas
# ---------------------------------------------------------------------------

_DATA_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_DATA_ISO_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _meta_content(doc, property_name: str) -> str | None:
    """Retorna o conteúdo de <meta property="…"> ou None."""
    for m in doc.cssselect(f'meta[property="{property_name}"]'):
        return m.get("content") or None
    return None


def _data_de_meta(doc, *properties: str) -> str | None:
    """Tenta cada property em ordem; retorna AAAA-MM-DD ou None."""
    for prop in properties:
        valor = _meta_content(doc, prop)
        if valor:
            m = _DATA_ISO_RE.match(valor)
            if m:
                return m.group(1)
    return None


def _extrair_datas(doc) -> tuple[str | None, str | None]:
    campo = doc.cssselect("div.field-name-autor-publicacao-alteracao")
    if campo:
        texto = " ".join(campo[0].itertext())
        datas = _DATA_RE.findall(texto)
        def _fmt(t):
            return f"{t[2]}-{t[1]}-{t[0]}"
        publicado = _fmt(datas[0]) if len(datas) > 0 else None
        atualizado = _fmt(datas[1]) if len(datas) > 1 else None
        return publicado, atualizado
    # Fallback: meta tags (bloco visível ausente)
    atualizado = _data_de_meta(doc, "article:modified_time", "og:updated_time")
    publicado = _data_de_meta(doc, "article:published_time")
    return publicado, atualizado


# ---------------------------------------------------------------------------
# Extração de taxonomia
# ---------------------------------------------------------------------------

def _extrair_taxonomia(doc) -> dict[str, list[str]]:
    resultado: dict[str, list[str]] = {k: [] for k in _CAMPO_TAXONOMIA.values()}
    for classe, chave in _CAMPO_TAXONOMIA.items():
        campos = doc.cssselect(f"div.{classe}")
        if not campos:
            continue
        items = campos[0].cssselect("div.field-item")
        resultado[chave] = [_normalizar_espaco("".join(i.itertext())) for i in items]
    return resultado


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def extrair_pagina_fagen(html: str, url: str | None = None) -> dict:
    """Extrai dados estruturados de uma página de serviço da FAGEN (Drupal).

    Args:
        html: HTML bruto da página.
        url:  URL canônica da página (usado para tornar links relativos absolutos).

    Returns:
        Dict com chaves: titulo, publicado_em, atualizado_em, publico_alvo,
        curso, assunto, secoes, anexos, contato.

    Raises:
        ValueError: se não encontrar h1 dentro de div.field-name-title.
    """
    doc = lxml.html.document_fromstring(html)

    # 1. Remove script/style antes de qualquer extração
    _remover_tags(doc)

    # 2. Título obrigatório
    titulos = doc.cssselect("div.field-name-title h1")
    if not titulos:
        raise ValueError("Título não encontrado: div.field-name-title h1 ausente.")
    titulo = _normalizar_espaco("".join(titulos[0].itertext()))

    # 3. Datas
    publicado_em, atualizado_em = _extrair_datas(doc)

    # 4. Taxonomia
    taxonomia = _extrair_taxonomia(doc)

    # 5. Seções + coleta de anexos dos campos de texto
    secoes: list[dict] = []
    vistos_anexos: dict[tuple, dict] = {}
    todos_anexos: list[dict] = []

    campos_texto = doc.xpath(
        "//div[contains(@class,'field-type-text-long') or "
        "contains(@class,'field-type-text-with-summary')]"
    )

    for campo in campos_texto:
        classes = set((campo.get("class") or "").split())

        # Rótulo: body não tem; demais têm div.field-label
        rotulo = ""
        if _CLASSE_BODY not in classes:
            labels = campo.cssselect("div.field-label")
            if labels:
                rotulo = _normalizar_espaco("".join(labels[0].itertext()))
                rotulo = rotulo.rstrip(":").strip()

        texto = _campo_para_texto(campo)
        if texto:
            secoes.append({"titulo": rotulo, "texto": texto})

        novos = _processar_links(_links_de_elem(campo), url, vistos_anexos)
        todos_anexos.extend(novos)

    # 6. Links da tabela de anexos
    for tabela_div in doc.cssselect("div.field-name-field-anexo"):
        novos = _processar_links(_links_de_elem(tabela_div), url, vistos_anexos)
        todos_anexos.extend(novos)

    # 7. Contato
    contato = _extrair_contato(doc)

    return {
        "titulo": titulo,
        "publicado_em": publicado_em,
        "atualizado_em": atualizado_em,
        **taxonomia,
        "secoes": secoes,
        "anexos": todos_anexos,
        "contato": contato,
    }
