"""Páginas de serviço da PROGRAD (mesmo Drupal da FAGEN, com campos diferentes).

Diferenças cobertas, sobre extrair_pagina_fagen (guia.ingestao.pagina_fagen):
- taxonomia com vários links dentro de um único field-item;
- "Assunto" vem de field-name-field-categoria-servico;
- lista de legislações (field-name-field-legislacao) vira seção e entra nos anexos;
- contato no bloco field-name-field-uorg-superior, com e-mail, telefones, endereço e
  horário; os dois telefones vêm colados no HTML ("34 3291-898434 3291-8983");
- blocos de navegação (cartões de modalidades e serviços) não entram nas seções.
Em contato, as chaves "endereco" e "horario" só existem quando achadas (o contato da
FAGEN continua com 4 chaves).
"""
from guia.ingestao.pagina_fagen import extrair_pagina_fagen

URL = "https://prograd.ufu.br/estagio"

PAGINA = """<html><head>
<meta property="article:published_time" content="2016-03-24T13:28:56-03:00" />
<meta property="article:modified_time" content="2026-09-01T14:59:27-03:00" />
<title>Estágio | PROGRAD/UFU</title></head><body>
<div about="/estagio" class="node node-servico node-promoted view-mode-full ">
<div class="row"><div class="col-sm-12 ">
<div class="field field-name-content-type-name field-type-ds field-label-hidden identidade-conteudo"><div class="field-items"><div class="field-item even">PROGRAD</div></div></div>
<div class="field field-name-title field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even" property="dc:title"><h1 class="titulo">Estágio</h1></div></div></div>
<div class="field field-name-body field-type-text-with-summary field-label-hidden espacamento-campo"><div class="field-items"><div class="field-item even" property="content:encoded"><p>&nbsp;</p>

<p>O Estágio na Universidade Federal de Uberlândia é de responsabilidade do <a href="http://www.prograd.ufu.br/unidades-organizacionais/setor-de-estagio">Setor de Estágio (SESTA)</a>, vinculado à <a href="http://www.prograd.ufu.br/difdi">Divisão de Formação Discente (DIFDI)</a>, que tem como atribuição a formalização por meio dos Termos de Compromisso de Estágio (TCE),  conforme legislações vigentes, disponíveis abaixo.</p>

<p><strong>Instagram:</strong> <a href="https://www.instagram.com/estagioufu/">https://www.instagram.com/estagioufu/</a></p>
</div></div></div>
<div class="field field-name-rotulo-legislacao field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even"><div class="identidade-conteudo espacamento-campo">Legislações</div></div></div></div>
<div class="field field-name-field-legislacao field-type-entityreference field-label-hidden espacamento-campo"><div class="field-items"><div class="field-item even"><a href="/legislacoes/lei-no-11788-de-25092008-lei-federal-de-estagio">Lei Nº 11.788, de 25/09/2008 - Lei Federal de Estágio</a></div><div class="field-item odd"><a href="/legislacoes/resolucao-congrad-no-46-de-28032022-normas-gerais-da-graduacao-da-ufu">Resolução CONGRAD Nº 46, de 28/03/2022  - Normas Gerais da Graduação da UFU</a></div><div class="field-item even"><a href="/legislacoes/instrucao-normativa-sgpmgi-no-228-de-2-de-junho-de-2026-inclui-reserva-de-vagas-para">Instrução Normativa SGP/MGI Nº 228, de 2 de junho de 2026 (inclui reserva de vagas para estudantes indígenas e quilombolas em processos seletivos)</a></div></div></div>
</div></div>
<div class="row"><div class="col-sm-12 ">
<div class="field field-name-modalidades-de-estagio field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even"><section id="block-block-20" class="block block-block idg-destaques clearfix">
<h2 class="block-title">Modalidades de Estágio</h2>
<div class="content"><div class="row">
<div class="col-xs-6 col-sm-3"><a href="/estagio/externo"><div class="thumbnail"><div class="img-wrapper"><img title="Estágio Externo à UFU" alt="Estágio Externo à UFU" class="img-responsive" src="/sites/x/ufu_avaliacao_desempenho.svg"></div><div class="caption"><p>Estágio Externo à UFU</p></div></div></a></div>
</div>
<h2 class="block-title">Serviços Relacionados a Estágios</h2>
<div class="row">
<div class="col-xs-6 col-sm-3"><a href="/servicos/convenios-de-estagio"><div class="thumbnail"><div class="caption"><p>Convênios de Estágio</p></div></div></a></div>
</div></div></section></div></div></div>
</div></div>
<div class="row"><div class="col-sm-12 ">
<div class="field field-name-rotulo-uorg-responsavel field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even"><br><div class="identidade-conteudo">Responsável</div></div></div></div>
<div class="field field-name-field-uorg-superior field-type-entityreference field-label-hidden espacamento-campo"><div class="field-items"><div class="field-item even">
<div about="/unidades-organizacionais/setor-de-estagio" class="node node-uorg view-mode-conteudo_renderizado espacamento-campo"><div class="row"><div class="col-sm-12 ">
<div class="field field-name-title field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even" property="dc:title"><h4><a href="/unidades-organizacionais/setor-de-estagio">Setor de Estágio</a></h4></div></div></div><div class="field field-name-field-email field-type-email field-label-hidden email-icone"><div class="field-items"><div class="field-item even">estagio@prograd.ufu.br</div></div></div><br><i class="fa fa-phone-square fa-size"> </i> 34 3291-898434 3291-8983<br><div class="field field-name-endereco field-type-ds field-label-hidden separar-acima endereco-icone"><div class="field-items"><div class="field-item even">Av. João Naves de Ávila, 2121  - Bloco 3P - Sala(s) 09 - Bairro Santa Mônica</div></div></div><div class="field field-name-campus-cep field-type-ds field-label-hidden"><div class="field-items"><div class="field-item even">Campus Santa Mônica - Uberlândia-MG - CEP 38400-902</div></div></div><div class="field field-name-field-horario-de-atendimento field-type-text field-label-above separar-abaixo separar-acima espacamento-campo"><div class="field-label">Horário de atendimento: </div><div class="field-items"><div class="field-item even">De segunda a sexta das 8h às 12h e 13h às 17h (exceto feriados)</div></div></div>
</div></div></div></div></div></div>
<div class="field field-name-field-tags field-type-taxonomy-term-reference field-label-inline clearfix topicos"><div class="field-label">Tópicos: </div><div class="field-items"><div class="field-item even"><a href="/tags/estudante">estudante</a> <a href="/tags/estagio">estágio</a></div></div></div>
<div class="field field-name-field-publico-alvo field-type-taxonomy-term-reference field-label-inline clearfix"><div class="field-label">Público-alvo: </div><div class="field-items"><div class="field-item even"><a href="/publico-alvo/estudante">Estudante</a> <a href="/publico-alvo/unidade-academica">Unidade Acadêmica</a> <a href="/publico-alvo/comunidade-externa">Comunidade Externa</a></div></div></div>
<div class="field field-name-field-categoria-servico field-type-taxonomy-term-reference field-label-inline clearfix"><div class="field-label">Assunto: </div><div class="field-items"><div class="field-item even"><a href="/assunto/atendimento-ao-estudante">Atendimento ao estudante</a> <a href="/assunto/bolsas">Bolsas</a> <a href="/assunto-legislacao-e-servico/estagio">Estágio</a> <a href="/assunto-legislacao-e-servico/graduacao">Graduação</a> <a href="/assunto-legislacao-e-servico/processos-seletivos">Processos seletivos</a></div></div></div>
</div></div></div></body></html>"""


def _r():
    return extrair_pagina_fagen(PAGINA, URL)


def test_titulo_e_datas_da_prograd():
    r = _r()
    assert r["titulo"] == "Estágio"
    assert r["atualizado_em"] == "2026-09-01"
    assert r["publicado_em"] == "2016-03-24"


def test_taxonomia_com_varios_links_num_unico_item_vira_lista():
    r = _r()
    assert r["publico_alvo"] == ["Estudante", "Unidade Acadêmica", "Comunidade Externa"]
    assert r["assunto"] == [
        "Atendimento ao estudante", "Bolsas", "Estágio", "Graduação", "Processos seletivos",
    ]
    assert r["curso"] == []


def test_secoes_sao_o_corpo_e_a_lista_de_legislacoes():
    secoes = _r()["secoes"]
    assert [s["titulo"] for s in secoes] == ["", "Legislações"]
    assert secoes[0]["texto"] == (
        "O Estágio na Universidade Federal de Uberlândia é de responsabilidade do "
        "Setor de Estágio (SESTA), vinculado à Divisão de Formação Discente (DIFDI), "
        "que tem como atribuição a formalização por meio dos Termos de Compromisso de "
        "Estágio (TCE), conforme legislações vigentes, disponíveis abaixo.\n\n"
        "Instagram: https://www.instagram.com/estagioufu/"
    )
    assert secoes[1]["texto"] == (
        "- Lei Nº 11.788, de 25/09/2008 - Lei Federal de Estágio\n"
        "- Resolução CONGRAD Nº 46, de 28/03/2022 - Normas Gerais da Graduação da UFU\n"
        "- Instrução Normativa SGP/MGI Nº 228, de 2 de junho de 2026 (inclui reserva de "
        "vagas para estudantes indígenas e quilombolas em processos seletivos)"
    )


def test_blocos_de_navegacao_nao_vazam_para_as_secoes():
    texto = " ".join(s["texto"] for s in _r()["secoes"])
    assert "Serviços Relacionados a Estágios" not in texto
    assert "Modalidades de Estágio" not in texto
    assert "Convênios de Estágio" not in texto


def test_legislacoes_entram_nos_anexos_com_url_absoluta():
    assert _r()["anexos"] == [
        {
            "texto": "Setor de Estágio (SESTA)",
            "url": "http://www.prograd.ufu.br/unidades-organizacionais/setor-de-estagio",
            "tipo": "pagina",
        },
        {
            "texto": "Divisão de Formação Discente (DIFDI)",
            "url": "http://www.prograd.ufu.br/difdi",
            "tipo": "pagina",
        },
        {
            "texto": "https://www.instagram.com/estagioufu/",
            "url": "https://www.instagram.com/estagioufu/",
            "tipo": "pagina",
        },
        {
            "texto": "Lei Nº 11.788, de 25/09/2008 - Lei Federal de Estágio",
            "url": "https://prograd.ufu.br/legislacoes/lei-no-11788-de-25092008-lei-federal-de-estagio",
            "tipo": "pagina",
        },
        {
            "texto": "Resolução CONGRAD Nº 46, de 28/03/2022 - Normas Gerais da Graduação da UFU",
            "url": "https://prograd.ufu.br/legislacoes/resolucao-congrad-no-46-de-28032022-normas-gerais-da-graduacao-da-ufu",
            "tipo": "pagina",
        },
        {
            "texto": "Instrução Normativa SGP/MGI Nº 228, de 2 de junho de 2026 (inclui reserva de vagas para estudantes indígenas e quilombolas em processos seletivos)",
            "url": "https://prograd.ufu.br/legislacoes/instrucao-normativa-sgpmgi-no-228-de-2-de-junho-de-2026-inclui-reserva-de-vagas-para",
            "tipo": "pagina",
        },
    ]


def test_contato_da_prograd_com_telefones_colados_endereco_e_horario():
    assert _r()["contato"] == {
        "setor": "Setor de Estágio",
        "email": "estagio@prograd.ufu.br",
        "telefone": "34 3291-8984 / 34 3291-8983",
        "ramal": None,
        "endereco": (
            "Av. João Naves de Ávila, 2121 - Bloco 3P - Sala(s) 09 - Bairro Santa Mônica - "
            "Campus Santa Mônica - Uberlândia-MG - CEP 38400-902"
        ),
        "horario": "De segunda a sexta das 8h às 12h e 13h às 17h (exceto feriados)",
    }
