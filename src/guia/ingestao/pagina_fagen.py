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
    contato         ({"setor", "email", "telefone", "ramal"[, "endereco", "horario"]} ou None)

Decisões de implementação:
- Usamos lxml.html.document_fromstring (reconhece HTML5 malformado).
- Script e style são removidos antes de qualquer extração.
- Campos de texto: divs com classe field-type-text-long ou field-type-text-with-summary,
  em ordem de documento; rótulo = div.field-label sem os dois pontos finais; body sem rótulo.
- Conversão para texto: <p> e <li> geram blocos; <br> vira \n; NBSP normalizado;
  parágrafos vazios descartados; blocos separados por linha em branco (\n\n).
- Listas: cada <li> vira linha começando com "- ".
- Anexos: coletados de todos os campos de texto + field-name-field-legislacao +
  tabela field-name-field-anexo; ignorados mailto:, tel:, #, whatsapp:; tornados absolutos
  com urljoin; deduplicados por (host sem "www.", path), mantendo a primeira ocorrência.
- Tipo de anexo: extensão do path ou "pagina".
- Contato: extraído de field-name-field-unidade-superior OU field-name-field-uorg-superior.
- Título: apenas de div.field-name-title h1; ausente → ValueError.
- Taxonomia: usa texto de cada <a> dentro de field-item se houver links; caso contrário,
  itertext do item inteiro.
- Legislações (field-name-field-legislacao) viram seção "- texto" por link;
  título da seção vem de field-name-rotulo-legislacao (fallback: "Legislações").
- Contato: telefones extraídos por regex (?:\\+\\d{2}\\s)?\\d{2}\\s\\d{4,5}-\\d{4},
  juntos por " / "; endereco e horario adicionados quando encontrados.
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
    # assunto: tenta field-name-field-assunto primeiro, depois field-name-field-categoria-servico
    "field-name-field-assunto": "assunto",
}
_CAMPO_ASSUNTO_FALLBACK = "field-name-field-categoria-servico"
_CAMPO_LEGISLACAO = "field-name-field-legislacao"
_CAMPO_ROTULO_LEGISLACAO = "field-name-rotulo-legislacao"
_CAMPOS_CONTATO = ("field-name-field-unidade-superior", "field-name-field-uorg-superior")
_TELEFONE_RE = re.compile(r"(?:\+\d{2}\s)?\d{2}\s\d{4,5}-\d{4}")


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

def _texto_itertext(el) -> str:
    """Junta pedaços de itertext com espaço (evita que texto de elementos adjacentes grude)."""
    return _normalizar_espaco(" ".join(el.itertext()))


def _extrair_contato(doc) -> dict | None:
    # Aceita field-name-field-unidade-superior OU field-name-field-uorg-superior
    bloco = None
    for classe in _CAMPOS_CONTATO:
        campos = doc.cssselect(f"div.{classe}")
        if campos:
            bloco = campos[0]
            break
    if bloco is None:
        return None

    # Setor: texto do primeiro <a> dentro de h4; fallback: primeiro <a> qualquer
    setor = ""
    h4_links = bloco.cssselect("h4 a")
    if h4_links:
        setor = _normalizar_espaco("".join(h4_links[0].itertext()))
    else:
        links_geral = bloco.cssselect("div.field-name-title a")
        if links_geral:
            setor = _normalizar_espaco("".join(links_geral[0].itertext()))

    # E-mail
    email = ""
    email_divs = bloco.cssselect("div.field-name-field-email div.field-item")
    if email_divs:
        email = _normalizar_espaco("".join(email_divs[0].itertext()))
    else:
        # fallback: procura em info-contato-2
        info = bloco.cssselect("div.field-name-info-contato-2")
        if info:
            for div in info[0].cssselect("div"):
                texto_div = _texto_itertext(div)
                if "@" in texto_div and not email:
                    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", texto_div)
                    if m:
                        email = m.group(0)

    # Telefones: todas as ocorrências do padrão, unidas por " / "
    texto_bloco = _texto_itertext(bloco)
    fones = _TELEFONE_RE.findall(texto_bloco)
    telefone: str | None = " / ".join(fones) if fones else None

    # Ramal (mantido por compatibilidade com FAGEN)
    ramal: str | None = None
    m_ramal = re.search(r"Ramal[:\s]+(\d+)", texto_bloco, re.IGNORECASE)
    if m_ramal:
        ramal = m_ramal.group(1)

    if not setor and not email:
        return None

    contato: dict = {"setor": setor, "email": email, "telefone": telefone, "ramal": ramal}

    # Endereço (field-name-endereco + field-name-campus-cep)
    partes_end: list[str] = []
    for classe_end in ("field-name-endereco", "field-name-campus-cep"):
        divs_end = bloco.cssselect(f"div.{classe_end} div.field-item")
        if divs_end:
            t = _normalizar_espaco("".join(divs_end[0].itertext()))
            if t:
                partes_end.append(t)
    if partes_end:
        contato["endereco"] = " - ".join(partes_end)

    # Horário de atendimento
    horario_divs = bloco.cssselect(
        "div.field-name-field-horario-de-atendimento div.field-item"
    )
    if horario_divs:
        h = _normalizar_espaco("".join(horario_divs[0].itertext()))
        if h:
            contato["horario"] = h

    return contato


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

def _valores_taxonomia(items) -> list[str]:
    """Extrai valores de uma lista de field-items.

    Se o item contiver <a>, retorna o texto de cada link separadamente;
    caso contrário, retorna o itertext do item como um único valor.
    """
    valores: list[str] = []
    for item in items:
        links = item.cssselect("a")
        if links:
            for a in links:
                t = _normalizar_espaco("".join(a.itertext()))
                if t:
                    valores.append(t)
        else:
            t = _normalizar_espaco("".join(item.itertext()))
            if t:
                valores.append(t)
    return valores


def _extrair_taxonomia(doc) -> dict[str, list[str]]:
    resultado: dict[str, list[str]] = {k: [] for k in _CAMPO_TAXONOMIA.values()}
    for classe, chave in _CAMPO_TAXONOMIA.items():
        campos = doc.cssselect(f"div.{classe}")
        if not campos:
            continue
        items = campos[0].cssselect("div.field-item")
        resultado[chave] = _valores_taxonomia(items)
    # Fallback para assunto: tenta field-name-field-categoria-servico se vazio
    if not resultado["assunto"]:
        campos = doc.cssselect(f"div.{_CAMPO_ASSUNTO_FALLBACK}")
        if campos:
            items = campos[0].cssselect("div.field-item")
            resultado["assunto"] = _valores_taxonomia(items)
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

    # 5. Seções (campos de texto + legislações) em ordem de documento + coleta de anexos
    secoes: list[dict] = []
    vistos_anexos: dict[tuple, dict] = {}
    todos_anexos: list[dict] = []

    # Seleciona campos de texto E campo de legislação, todos em ordem de documento
    campos_relevantes = doc.xpath(
        "//div[contains(@class,'field-type-text-long') or "
        "contains(@class,'field-type-text-with-summary') or "
        f"contains(@class,'{_CAMPO_LEGISLACAO}')]"
    )

    for campo in campos_relevantes:
        classes = set((campo.get("class") or "").split())

        # Campo de legislações → vira seção com linhas "- <texto do link>"
        if _CAMPO_LEGISLACAO in classes:
            # Título da seção: vem de field-name-rotulo-legislacao ou "Legislações"
            rotulo_leg = "Legislações"
            rotulo_divs = doc.cssselect(f"div.{_CAMPO_ROTULO_LEGISLACAO} div.field-item")
            if rotulo_divs:
                t = _normalizar_espaco("".join(rotulo_divs[0].itertext()))
                if t:
                    rotulo_leg = t

            linhas: list[str] = []
            for a in campo.cssselect("a[href]"):
                texto_link = _normalizar_espaco("".join(a.itertext()))
                if texto_link:
                    linhas.append(f"- {texto_link}")

            if linhas:
                secoes.append({"titulo": rotulo_leg, "texto": "\n".join(linhas)})

            # Links de legislação também vão para os anexos
            novos = _processar_links(_links_de_elem(campo), url, vistos_anexos)
            todos_anexos.extend(novos)
            continue

        # Campo de texto comum
        if _CAMPO_LEGISLACAO in classes:
            continue  # já tratado acima (redundante, mas seguro)

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
