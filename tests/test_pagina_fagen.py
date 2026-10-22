"""Extração de páginas de serviço da FAGEN (Drupal) a partir do HTML bruto.

Contrato:
    extrair_pagina_fagen(html: str, url: str | None = None) -> dict
em guia.ingestao.pagina_fagen. Chaves do dict:
    titulo (str), publicado_em / atualizado_em (str ISO "AAAA-MM-DD" ou None),
    publico_alvo / curso / assunto (list[str]),
    secoes (list[{"titulo": str, "texto": str}]) em ordem de página,
    anexos (list[{"texto", "url", "tipo"}]),
    contato ({"setor", "email", "telefone", "ramal"} ou None).
"""
import pytest

from guia.ingestao.pagina_fagen import extrair_pagina_fagen

URL_TCC = "https://fagen.ufu.br/servicos/trabalho-de-conclusao-de-curso-0"
URL_ESTAGIO = "https://fagen.ufu.br/servicos/estagio-supervisionado"

DOCX_WWW = "https://www.fagen.ufu.br/system/files/conteudo/formulario_tcc_ggi095.docx"
DOCX_SEM_WWW = "https://fagen.ufu.br/system/files/conteudo/formulario_tcc_ggi095.docx"
PDF_TCC = "http://www.fagen.ufu.br/system/files/conteudo/passo_a_passo_tcc_ggi095.pdf"

AUTOR = """
<div class="field field-name-autor-publicacao-alteracao field-type-ds field-label-hidden publicacao"><div class="field-items"><div class="field-item even"><div class="row compartilhar">
<div class="col-xs-12 col-sm-6">
    por <strong>Portal FAGEN</strong><br>Publicado: 17/08/2021 - 00:00<br>Última modificação: __ULTIMA__  </div>
<div class="col-xs-12 col-sm-6"><a href="https://www.facebook.com/sharer.php" class="service-links-facebook-share">Compartilhe no Facebook</a>
<a href="whatsapp://send?text=https://fagen.ufu.br/servicos/x" data-action="share/whatsapp/share">Whatsapp</a>
<script>(function(d, s, id) { var js = d.getElementsByTagName(s)[0]; })(document, 'script', 'facebook-jssdk');</script>
<style>#widgets-element-widgets_custom-markup { display: none; }</style></div>
</div></div></div></div>
"""


def _pagina(titulo, campos, ultima="02/06/2026 - 15:33", com_datas=True):
    autor = AUTOR.replace("__ULTIMA__", ultima) if com_datas else ""
    return f"""<html><body><div class="col-sm-12 ">
<div class="field field-name-campo-dinamico field-type-ds field-label-hidden identidade-conteudo"><div class="field-items"><div class="field-item even"><p>Serviço</p></div></div></div>
<div class="field field-name-title field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even" property="dc:title"><h1 class="titulo">{titulo}</h1></div></div></div>
{autor}
<div class="espacamento-campos">{campos}</div>
</div></body></html>"""


TAXONOMIA = """
<div class="field field-name-field-publico-alvo field-type-taxonomy-term-reference field-label-inline clearfix"><div class="field-label">Público-alvo: </div><div class="field-items"><div class="field-item even"><a href="/publico-alvo/estudante">Estudante</a></div></div></div>
<div class="field field-name-field-curso field-type-taxonomy-term-reference field-label-inline clearfix"><div class="field-label">Curso: </div><div class="field-items"><div class="field-item even"><a href="/graduacao-0">Gestão da Informação</a></div><div class="field-item odd"><a href="/graduacao-1">Administração</a></div></div></div>
<div class="field field-name-field-assunto field-type-taxonomy-term-reference field-label-inline clearfix"><div class="field-label">Assunto: </div><div class="field-items"><div class="field-item even"><a href="/assunto/documentos">Documentos</a></div></div></div>
"""

SETOR = """
<div class="field field-name-field-unidade-superior field-type-entityreference field-label-above"><div class="field-label">Setor responsável: </div><div class="field-items"><div class="field-item even">
<div about="/unidades/setor/coordenacao-de-estagio-e-trabalho-de-curso" class="node node-uorg"><div class="row"><div class="col-sm-12 ">
<div class="field field-name-title field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even" property="dc:title"><p><a href="/unidades/setor/coordenacao-de-estagio-e-trabalho-de-curso">Coordenação de Estágio e Trabalho de Curso</a></p></div></div></div>
<div class="field field-name-info-contato-2 field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even"><div><i class="fa fa-fw fa-envelope-square"></i>  estagio@fagen.ufu.br</div><div><i class="fa fa-fw fa-phone-square"></i>  +55 34 3230-9481</div><div><i class="fa fa-fw "></i> <strong>Ramal:</strong> 9481</div></div></div></div>
</div></div></div></div></div></div>
"""

TABELA_ANEXOS = f"""
<div class="field field-name-field-anexo field-type-file field-label-hidden"><div class="field-items"><div class="field-item even"><div class="table-responsive">
<table class="table"><thead><tr><th>Anexo</th><th>Tamanho</th> </tr></thead><tbody>
<tr><td><span class="file"><img class="file-icon" alt="Arquivo" src="/modules/file/icons/x-office-document.png"> <a href="{DOCX_SEM_WWW}" type="application/vnd.openxmlformats-officedocument.wordprocessingml.document; length=15938">formulario_tcc_ggi095.docx</a></span></td><td>15.56 KB</td> </tr>
</tbody></table></div></div></div></div>
"""

ORIENTACOES_TCC = f"""
<div class="field field-name-field-orientacoes field-type-text-long field-label-above"><div class="field-label">Orientações: </div><div class="field-items"><div class="field-item even"><p>
<strong>Trabalho de Conclusão de Curso - Curso : Gestão da Informação - GGI 095</strong></p>
<p>&nbsp;</p>
<p><strong><span class="file"><a href="{DOCX_WWW}">1 - Formulário Digital de Registro de Matrícula - GGI095</a></span></strong></p>
<p>
<strong><a href="{PDF_TCC}" target="_blank">2 - PASSO A PASSO - Matrícula Interna - GGI 095</a></strong><br>
 </p>
</div></div></div>
"""

TCC = _pagina("Trabalho de Conclusão de Curso", TAXONOMIA + ORIENTACOES_TCC + SETOR + TABELA_ANEXOS)

CORPO = """
<div class="field field-name-body field-type-text-with-summary field-label-hidden"><div class="field-items"><div class="field-item even" property="content:encoded"><p>O estágio é uma prática importante de integração entre a Universidade e a empresa.</p>
<p>O Curso conta com o estágio em duas modalidades:&nbsp;Obrigatório e Não Obrigatório.</p>
</div></div></div>
"""

REQUISITOS = """
<div class="field field-name-field-requisitos field-type-text-long field-label-above"><div class="field-label">Requisitos: </div><div class="field-items"><div class="field-item even"><p>Para ser considerado como Estágio Supervisionado, o estudante deverá estagiar em áreas como:</p>
<ul><li>Análise de dados</li>
<li>Gestão de Projetos</li>
<li>Outras, desde que aprovadas pelo Colegiado do Curso.</li>
</ul></div></div></div>
"""

ORIENTACOES_ESTAGIO = """
<div class="field field-name-field-orientacoes field-type-text-long field-label-above"><div class="field-label">Orientações: </div><div class="field-items"><div class="field-item even">
<p><strong>Estágio Obrigatório - Curso : Gestão da Informação - GGI042</strong></p>
<p><strong><span class="file"><a href="/system/files/conteudo/formulario_estagio_ggi042.docx" title="1 - Formulário">1 - Formulário Digital de Registro de Matrícula - GGI 042</a></span></strong></p>
<p><a href="http://www.fagen.ufu.br/system/files/conteudo/02_passo_a_passo_estagio_ggi042.pdf" target="_blank">2 - PASSO A PASSO - Matrícula Interna - GGI042</a></p>
<p>Orientações e Documentos do Setor de Estágio da UFU (SESTA)</p>
<ul><li><a href="https://exemplo.ufu.br/estagio-externo">Estágio Externo</a></li></ul>
<p>Dúvidas: <a href="mailto:estagio@fagen.ufu.br">estagio@fagen.ufu.br</a> ou veja o <a href="#topo">topo</a>.</p>
</div></div></div>
"""

ESTAGIO = _pagina(
    "Estágio Supervisionado",
    TAXONOMIA + CORPO + REQUISITOS + ORIENTACOES_ESTAGIO,
    ultima="26/08/2024 - 16:02",
)


# ---------- título, datas, metadados ----------

def test_titulo_vem_do_h1_e_nao_do_titulo_do_setor_embutido():
    assert extrair_pagina_fagen(TCC, URL_TCC)["titulo"] == "Trabalho de Conclusão de Curso"


def test_datas_viram_iso():
    r = extrair_pagina_fagen(TCC, URL_TCC)
    assert r["publicado_em"] == "2021-08-17"
    assert r["atualizado_em"] == "2026-06-02"
    assert extrair_pagina_fagen(ESTAGIO, URL_ESTAGIO)["atualizado_em"] == "2024-08-26"


def test_sem_datas_na_pagina_ficam_none_e_o_resto_vazio():
    r = extrair_pagina_fagen(_pagina("Página mínima", "", com_datas=False))
    assert r["publicado_em"] is None and r["atualizado_em"] is None
    assert r["secoes"] == [] and r["anexos"] == [] and r["contato"] is None
    assert r["publico_alvo"] == [] and r["curso"] == [] and r["assunto"] == []


def test_taxonomia_vira_listas_de_texto():
    r = extrair_pagina_fagen(TCC, URL_TCC)
    assert r["publico_alvo"] == ["Estudante"]
    assert r["curso"] == ["Gestão da Informação", "Administração"]
    assert r["assunto"] == ["Documentos"]


def test_pagina_sem_titulo_falha_alto():
    with pytest.raises(ValueError):
        extrair_pagina_fagen("<html><body><p>Nada de FAGEN aqui</p></body></html>")


# ---------- seções ----------

def test_secoes_seguem_a_ordem_da_pagina_e_o_corpo_nao_tem_rotulo():
    r = extrair_pagina_fagen(ESTAGIO, URL_ESTAGIO)
    assert [s["titulo"] for s in r["secoes"]] == ["", "Requisitos", "Orientações"]


def test_corpo_vira_paragrafos_separados_por_linha_em_branco_com_nbsp_normalizado():
    corpo = extrair_pagina_fagen(ESTAGIO, URL_ESTAGIO)["secoes"][0]["texto"]
    assert corpo == (
        "O estágio é uma prática importante de integração entre a Universidade e a empresa.\n\n"
        "O Curso conta com o estágio em duas modalidades: Obrigatório e Não Obrigatório."
    )


def test_lista_vira_linhas_com_hifen():
    req = extrair_pagina_fagen(ESTAGIO, URL_ESTAGIO)["secoes"][1]["texto"]
    assert req == (
        "Para ser considerado como Estágio Supervisionado, o estudante deverá estagiar em áreas como:\n\n"
        "- Análise de dados\n"
        "- Gestão de Projetos\n"
        "- Outras, desde que aprovadas pelo Colegiado do Curso."
    )


def test_paragrafos_vazios_e_br_final_somem_e_o_texto_do_link_permanece():
    (secao,) = extrair_pagina_fagen(TCC, URL_TCC)["secoes"]
    assert secao["titulo"] == "Orientações"
    assert secao["texto"] == (
        "Trabalho de Conclusão de Curso - Curso : Gestão da Informação - GGI 095\n\n"
        "1 - Formulário Digital de Registro de Matrícula - GGI095\n\n"
        "2 - PASSO A PASSO - Matrícula Interna - GGI 095"
    )


def test_orientacoes_do_estagio_mantem_texto_de_links_lista_e_email():
    texto = extrair_pagina_fagen(ESTAGIO, URL_ESTAGIO)["secoes"][2]["texto"]
    assert texto == (
        "Estágio Obrigatório - Curso : Gestão da Informação - GGI042\n\n"
        "1 - Formulário Digital de Registro de Matrícula - GGI 042\n\n"
        "2 - PASSO A PASSO - Matrícula Interna - GGI042\n\n"
        "Orientações e Documentos do Setor de Estágio da UFU (SESTA)\n\n"
        "- Estágio Externo\n\n"
        "Dúvidas: estagio@fagen.ufu.br ou veja o topo."
    )


def test_ruido_de_compartilhamento_nao_vaza_para_texto_nem_anexos():
    for pagina, url in ((TCC, URL_TCC), (ESTAGIO, URL_ESTAGIO)):
        r = extrair_pagina_fagen(pagina, url)
        texto_total = " ".join(s["texto"] for s in r["secoes"])
        assert "getElementsByTagName" not in texto_total
        assert "widgets-element" not in texto_total
        assert not any(
            "facebook" in a["url"] or "whatsapp" in a["url"] for a in r["anexos"]
        )


# ---------- anexos ----------

def test_anexos_do_tcc_sem_duplicata_entre_o_texto_e_a_tabela_de_anexos():
    # o mesmo formulário aparece no texto (com www) e na tabela (sem www)
    assert extrair_pagina_fagen(TCC, URL_TCC)["anexos"] == [
        {
            "texto": "1 - Formulário Digital de Registro de Matrícula - GGI095",
            "url": DOCX_WWW,
            "tipo": "docx",
        },
        {
            "texto": "2 - PASSO A PASSO - Matrícula Interna - GGI 095",
            "url": PDF_TCC,
            "tipo": "pdf",
        },
    ]


def test_links_relativos_viram_absolutos_e_mailto_e_ancora_sao_ignorados():
    assert extrair_pagina_fagen(ESTAGIO, URL_ESTAGIO)["anexos"] == [
        {
            "texto": "1 - Formulário Digital de Registro de Matrícula - GGI 042",
            "url": "https://fagen.ufu.br/system/files/conteudo/formulario_estagio_ggi042.docx",
            "tipo": "docx",
        },
        {
            "texto": "2 - PASSO A PASSO - Matrícula Interna - GGI042",
            "url": "http://www.fagen.ufu.br/system/files/conteudo/02_passo_a_passo_estagio_ggi042.pdf",
            "tipo": "pdf",
        },
        {
            "texto": "Estágio Externo",
            "url": "https://exemplo.ufu.br/estagio-externo",
            "tipo": "pagina",
        },
    ]


def test_sem_url_da_pagina_links_relativos_ficam_como_estao():
    urls = [a["url"] for a in extrair_pagina_fagen(ESTAGIO)["anexos"]]
    assert urls[0] == "/system/files/conteudo/formulario_estagio_ggi042.docx"


# ---------- contato ----------

def test_contato_do_setor_responsavel():
    assert extrair_pagina_fagen(TCC, URL_TCC)["contato"] == {
        "setor": "Coordenação de Estágio e Trabalho de Curso",
        "email": "estagio@fagen.ufu.br",
        "telefone": "+55 34 3230-9481",
        "ramal": "9481",
    }


def test_sem_bloco_de_setor_contato_e_none():
    assert extrair_pagina_fagen(ESTAGIO, URL_ESTAGIO)["contato"] is None
