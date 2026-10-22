"""Datas de páginas que não têm o bloco visível "Última modificação" (ex.: PROGRAD).

A data vem das meta tags do cabeçalho. Ordem de prioridade para a data de atualização:
bloco visível > article:modified_time > og:updated_time > None.
A data de publicação usa article:published_time quando o bloco visível não existe.
Função testada: extrair_pagina_fagen (guia.ingestao.pagina_fagen).
"""
from guia.ingestao.pagina_fagen import extrair_pagina_fagen

BLOCO_VISIVEL = """
<div class="field field-name-autor-publicacao-alteracao field-type-ds field-label-hidden publicacao"><div class="field-items"><div class="field-item even"><div class="row compartilhar">
<div class="col-xs-12 col-sm-6">por <strong>Portal FAGEN</strong><br>Publicado: 17/08/2021 - 00:00<br>Última modificação: 26/08/2024 - 16:02</div>
</div></div></div></div>
"""


def _html(metas="", bloco=""):
    return f"""<html><head>{metas}<title>Estágio | PROGRAD/UFU</title></head><body>
<div class="field field-name-title field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even" property="dc:title"><h1 class="titulo">Estágio</h1></div></div></div>
{bloco}
</body></html>"""


META_COMPLETA = (
    '<meta property="article:published_time" content="2016-03-24T13:28:56-03:00" />'
    '<meta property="article:modified_time" content="2026-09-01T14:59:27-03:00" />'
    '<meta property="og:updated_time" content="2026-09-02T10:00:00-03:00" />'
)


def test_sem_bloco_visivel_a_data_vem_das_meta_tags():
    r = extrair_pagina_fagen(_html(metas=META_COMPLETA))
    assert r["atualizado_em"] == "2026-09-01"
    assert r["publicado_em"] == "2016-03-24"


def test_bloco_visivel_tem_prioridade_sobre_as_meta_tags():
    r = extrair_pagina_fagen(_html(metas=META_COMPLETA, bloco=BLOCO_VISIVEL))
    assert r["atualizado_em"] == "2024-08-26"
    assert r["publicado_em"] == "2021-08-17"


def test_og_updated_time_e_usado_quando_falta_article_modified_time():
    metas = '<meta property="og:updated_time" content="2025-03-10T08:15:00-03:00" />'
    r = extrair_pagina_fagen(_html(metas=metas))
    assert r["atualizado_em"] == "2025-03-10"
    assert r["publicado_em"] is None


def test_meta_invalida_ou_ausente_deixa_a_data_como_none():
    metas = '<meta property="article:modified_time" content="ontem" />'
    r = extrair_pagina_fagen(_html(metas=metas))
    assert r["atualizado_em"] is None and r["publicado_em"] is None
    r2 = extrair_pagina_fagen(_html())
    assert r2["atualizado_em"] is None and r2["publicado_em"] is None
