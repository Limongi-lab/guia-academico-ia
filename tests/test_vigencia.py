"""Testes da regra de vigência das resoluções consolidadas da UFU.

Os trechos abaixo são cópias curtas de atos oficiais (Res. CONGRAD 46/2022,
versão consolidada impressa do SEI em 18/04/2024), com a mesma formatação que
o PyMuPDF extrai. Ficam dentro do teste porque data/ não é versionado: o teste
precisa rodar em qualquer máquina.
"""
import pytest

from guia.ingestao.resolucoes import dividir_em_artigos

TEXTO = """\
=== página 7 ===
Art. 12. Poderão ser criados novos componentes curriculares quando houver:
I – criação de novos cursos, novos graus ou ênfases;
II – mudança curricular;
Parágrafo único. Nos casos mencionados nos incisos II a VI, o processo de criação ou
extinção de componentes curriculares ocorrerá por aprovação do Colegiado de Curso, mediante a
proposição do NDE e o parecer do Conselho da Unidade Acadêmica, cabendo a sua aprovação no
CONGRAD, exceto nos casos previstos no art. 17 desta Norma.
Parágrafo único. Nos casos mencionados nos incisos II a VI, o processo de criação ou
extinção de componentes curriculares ocorrerá por aprovação do Colegiado de Curso, mediante a
proposição do NDE e o parecer do Conselho da Unidade Acadêmica, cabendo a sua aprovação no
CONGRAD, exceto nos casos previstos no art. 18 desta Norma. (Redação dada pela Resolução CONGRAD
nº 78, de 16 de novembro de 2022)
=== página 14 ===
Art. 41. Deverão constar nos editais para o preenchimento de vagas pelo processo de
Transferência Facultativa as seguintes exigências mínimas necessárias aos candidatos, observado o que
dispõe o art. 40 desta Norma, no que couber:
I – o candidato deve estar cursando na UFU ou em outra IES um curso afim ao curso
pretendido, conforme definição das grandes áreas do Conselho Nacional de Desenvolvimento Científico e
Tecnológico - CNPq;
II – o candidato deve ter sido aprovado em todos os componentes curriculares do 1º ano,
ou do 1º e 2º semestres ou 1º, 2º e 3º quadrimestres do curso de origem;
II – o candidato deve estar com vínculo junto à IES de origem; e (Redação dada pela
Resolução CONGRAD nº 120, de 29 de novembro de 2023)
III – o candidato não poderá ter integralizado 75% (setenta e cinco por cento) do curso de
origem; e (Revogado pela Resolução CONGRAD nº 120, de 29 de novembro de 2023)
IV – o candidato deverá integralizar o currículo no tempo máximo previsto no Projeto
Pedagógico do curso para o qual pleiteia transferência, contando-se o tempo decorrido desde que iniciou
o curso em que estava matriculado na IES de origem.
=== página 16 ===
Art. 50. O ingresso de candidatos para preenchimento das vagas remanescentes será
realizado, anualmente, no primeiro semestre.
Art. 50. O ingresso de candidatos para preenchimento das vagas remanescentes será
realizado, semestralmente, havendo vagas ociosas. (Redação dada pela Resolução CONGRAD nº 120, de
29 de novembro de 2023)
§ 1º Haverá até duas chamadas sucessivas, além da primeira, para matrícula dos
candidatos classificados para preenchimento de vagas ofertadas. (Revogado pela Resolução CONGRAD nº
78, de 16 de novembro de 2022)
§ 2º O ingressante na modalidade Portador de Diploma de Curso Superior não possui
prioridade de matrícula e não precisa, necessariamente, ser matriculado em disciplinas do primeiro
período.
=== página 17 ===
Art. 53. O ingresso de candidatos para preenchimento das vagas ociosas será realizado,
anualmente, no primeiro semestre.
Art. 53. O ingresso de candidatos para preenchimento das vagas remanescentes será
realizado, semestralmente, havendo vagas ociosas. (Redação dada pela Resolução CONGRAD nº 120, de
29 de novembro de 2023)
=== página 29 ===
Art. 99. O estudante matriculado poderá requerer, por meio eletrônico, o trancamento
18/04/2024, 13:16 SEI/UFU - 5346187 - Resolução
https://www.sei.ufu.br/sei/controlador.php?acao=documento_imprimir_web&acao_origem=arvore_visualizar&id_documento=5967542&infra_si… 29/52
=== página 30 ===
parcial ou geral de matrícula.
Parágrafo único. O deferimento do trancamento implica na inteira responsabilidade pelo
estudante das consequências decorrentes de seu pedido.
=== página 43 ===
Art. 179. O tempo para dilação de prazo para integralização curricular, incluída a
prorrogação, não poderá exceder 50% (cinquenta por cento) do limite máximo fixado no Projeto
Pedagógico do Curso.
Art. 179. Da decisão que indeferir a dilação caberá recurso: (Redação dada pela Resolução
CONGRAD nº 127, de 19 de fevereiro de 2024)
I - do Coordenador ao Colegiado de Curso;(Incluído pela Resolução CONGRAD nº 127, de 19 de
fevereiro de 2024)
II - do Colegiado de Curso ao Conselho da Unidade; e (Incluído pela Resolução CONGRAD nº 127, de 19 de
fevereiro de 2024)
"""


@pytest.fixture(scope="module")
def trechos():
    return dividir_em_artigos(TEXTO)


def pegar(trechos, numero):
    achados = [t for t in trechos if t["artigo"] == numero]
    assert len(achados) == 1, f"esperava 1 trecho para o Art. {numero}, achei {len(achados)}"
    return achados[0]


def normalizar(texto):
    """Junta quebras de linha, porque o PDF quebra frases no meio."""
    return " ".join(texto.split())


# (artigo, deve conter, não pode conter)
CASOS = [
    ("12", ["art. 18 desta Norma"], ["art. 17 desta Norma"]),
    (
        "41",
        [
            "deve estar com vínculo junto à IES de origem",
            "deverá integralizar o currículo no tempo máximo",
        ],
        [
            "75% (setenta e cinco por cento)",  # inciso III revogado
            "aprovado em todos os componentes curriculares do 1º ano",  # inciso II antigo
        ],
    ),
    (
        "50",
        ["semestralmente, havendo vagas ociosas", "não possui prioridade de matrícula"],
        ["anualmente, no primeiro semestre", "Haverá até duas chamadas sucessivas"],
    ),
    ("53", ["semestralmente, havendo vagas ociosas"], ["anualmente, no primeiro semestre"]),
    (
        "179",
        ["Da decisão que indeferir a dilação caberá recurso"],
        ["não poderá exceder 50%"],
    ),
]


@pytest.mark.parametrize("numero, deve, nao_pode", CASOS)
def test_so_a_redacao_vigente(trechos, numero, deve, nao_pode):
    texto = normalizar(pegar(trechos, numero)["texto"])
    for trecho in deve:
        assert trecho in texto, f"Art. {numero} deveria conter: {trecho!r}"
    for trecho in nao_pode:
        assert trecho not in texto, f"Art. {numero} não deveria conter: {trecho!r}"


def test_um_trecho_por_artigo(trechos):
    numeros = [t["artigo"] for t in trechos]
    assert len(numeros) == len(set(numeros))
    assert set(numeros) == {"12", "41", "50", "53", "99", "179"}


def test_marcacoes_de_alteracao_saem_do_texto(trechos):
    for t in trechos:
        texto = normalizar(t["texto"])
        for marca in ("(Redação dada", "(Revogado", "(Incluído"):
            assert marca not in texto, f"Art. {t['artigo']} ainda tem {marca}"


def test_alteracoes_ficam_registradas_nos_metadados(trechos):
    alteracoes = pegar(trechos, "50")["alteracoes"]
    assert any("120" in a for a in alteracoes)


def test_rodape_do_sei_sai_e_artigo_entre_paginas_guarda_as_duas(trechos):
    t = pegar(trechos, "99")
    texto = normalizar(t["texto"])
    assert "SEI/UFU" not in texto
    assert "sei.ufu.br" not in texto
    assert "trancamento parcial ou geral de matrícula" in texto
    assert t["paginas"] == [29, 30]

TEXTO_ORDINAIS = """\
=== página 1 ===
Art. 1º Esta Norma disciplina a organização acadêmica dos cursos de graduação.
Art. 2º Os cursos de graduação terão duração definida no Projeto Pedagógico.
Parágrafo único. O prazo poderá ser prorrogado nos termos desta Norma.
Art. 10. Compete ao Colegiado de Curso aprovar o Projeto Pedagógico.
"""

TEXTO_CONTADOR = """\
=== página 16 ===
Art. 50. O ingresso será realizado, semestralmente, havendo vagas ociosas.
16/52
§ 2º O ingressante não possui prioridade de matrícula.
"""


def test_artigos_de_1_a_9_usam_ordinal_sem_ponto():
    trechos = dividir_em_artigos(TEXTO_ORDINAIS)
    assert [t["artigo"] for t in trechos] == ["1", "2", "10"]
    assert "Esta Norma disciplina" in trechos[0]["texto"]
    assert "Parágrafo único" in normalizar(trechos[1]["texto"])


def test_contador_de_paginas_do_sei_sai_do_texto():
    trechos = dividir_em_artigos(TEXTO_CONTADOR)
    texto = normalizar(trechos[0]["texto"])
    assert "16/52" not in texto
    assert "§ 2º" in texto

TEXTO_SEM_PONTO = """\
=== página 49 ===
Art. 201. A guarda e o arquivamento de documentos acadêmicos seguem as regras de temporalidade.

Art 202. O Plano de Ensino preliminar deverá ser entregue à Coordenação antes da matrícula. (Revogado pela Resolução CONGRAD Nº 107, de 07 de junho de 2023)
"""

TEXTO_MARCACAO_PARTIDA = """\
=== página 46 ===
Art. 188. A análise da equivalência será feita por meio da comparação da carga horária.
§ 3º Para o reconhecimento da equivalência, a Coordenação poderá propor a Complementação de Estudos se: (Redação dada pela Resolução
46/52
CONGRAD nº 78, de 16 de novembro de 2022)
I – faltar até 1/3 (um terço) da carga horária exigida; e/ou
"""

TEXTO_COM_TITULOS = """\
=== página 28 ===
Art. 98. O ajuste de renovação da matrícula poderá ser deferido em casos previstos.
§ 3º O prazo para ajuste se estenderá até o 12º dia letivo. (Incluído pela Resolução CONGRAD Nº 107, de 07 de junho de 2023)

CAPÍTULO VIII
DO TRANCAMENTO DE MATRÍCULA
Art. 99. O estudante matriculado poderá requerer o trancamento de matrícula.
"""


def test_art_sem_ponto_nao_contamina_o_artigo_anterior():
    trechos = dividir_em_artigos(TEXTO_SEM_PONTO)
    assert [t["artigo"] for t in trechos] == ["201"]  # 202 é revogado e some
    texto = normalizar(trechos[0]["texto"])
    assert "Plano de Ensino" not in texto
    assert "(Revogado" not in texto


def test_marcacao_partida_pelo_contador_de_paginas_sai_inteira():
    t = dividir_em_artigos(TEXTO_MARCACAO_PARTIDA)[0]
    texto = normalizar(t["texto"])
    assert "Redação dada" not in texto
    assert "CONGRAD" not in texto
    assert "faltar até 1/3" in texto
    assert any("78" in a for a in t["alteracoes"])


def test_marcacao_com_N_maiusculo_e_reconhecida():
    t = dividir_em_artigos(TEXTO_COM_TITULOS)[0]
    assert "(Incluído" not in normalizar(t["texto"])
    assert any("107" in a for a in t["alteracoes"])


def test_titulo_sai_do_artigo_anterior_e_vira_metadado_do_seguinte():
    art98, art99 = dividir_em_artigos(TEXTO_COM_TITULOS)
    assert "CAPÍTULO" not in art98["texto"]
    assert "TRANCAMENTO" not in art98["texto"]
    assert "CAPÍTULO VIII" in art99["capitulo"]
    assert "TRANCAMENTO DE MATRÍCULA" in art99["capitulo"]

TEXTO_REGIMENTO = """\
=== página 5 ===
Art. 12  Os cursos de graduação são organizados em currículos plenos.

Art. 13  Os cursos de graduação são administrados por um Diretor de Curso, e os
demais cursos por um Coordenador, conforme o Estatuto.
Art. 14  A Universidade manterá cursos de pós-graduação, conforme este Regimento.
"""

TEXTO_CITACAO_NO_INICIO_DA_LINHA = """\
=== página 5 ===
Art. 12. A aprovação seguirá os critérios definidos, ressalvado o disposto
Art. 18 desta Norma e demais exceções previstas.
Art. 13. Compete ao Colegiado aprovar o Projeto Pedagógico.
"""


def test_artigo_sem_ponto_depois_do_numero_no_regimento_uniube():
    trechos = dividir_em_artigos(TEXTO_REGIMENTO)
    assert [t["artigo"] for t in trechos] == ["12", "13", "14"]
    texto = normalizar(trechos[1]["texto"])
    assert "Diretor de Curso" in texto
    assert "demais cursos" in texto


def test_citacao_no_inicio_da_linha_nao_vira_artigo():
    trechos = dividir_em_artigos(TEXTO_CITACAO_NO_INICIO_DA_LINHA)
    assert [t["artigo"] for t in trechos] == ["12", "13"]
    assert "Art. 18 desta Norma" in normalizar(trechos[0]["texto"])

TEXTO_NBSP = (
    "=== página 8 ===\n"
    "Art. 17. O currículo poderá ser alterado nos seguintes casos:\n"
    "§ 2º A documentação será definida pela PROGRAD.\n"
    " \u00a0Art. 18. O currículo poderá ser alterado com parecer da PROGRAD, nos seguintes casos:\n"
    "I – alteração de pré-requisitos;\n"
    "Art. 19. A alteração dos optativos poderá ser feita pelo Colegiado.\n"
)

TEXTO_RECUO = (
    "=== página 9 ===\n"
    "Art. 45.  A frequência é obrigatória.\n\n"
    "        Art. 46.  A avaliação é parte integrante do processo ensino-aprendizagem.\n\n"
    "                § 1º  A avaliação é feita abrangendo frequência e aproveitamento.\n\n"
    "        Art. 47.  O resultado dos pontos obtidos é apurado com o seguinte procedimento:\n"
    "Art. 48.   A avaliação das atividades complementares é regulamentada por normas próprias.\n"
)

TEXTO_MARCACAO_ENTRE_PAGINAS = """\
=== página 46 ===
Art. 188. A análise da equivalência será feita pela comparação da carga horária.
§ 3º A Coordenação poderá propor a Complementação de Estudos se: (Redação dada pela Resolução
18/04/2024, 13:16 SEI/UFU - 5346187 - Resolução
https://www.sei.ufu.br/sei/controlador.php?acao=documento_imprimir_web&id_documento=5967542&infra_si… 46/52
=== página 47 ===
18/04/2024, 13:16 SEI/UFU - 5346187 - Resolução
CONGRAD nº 78, de 16 de novembro de 2022)
I – faltar até 1/3 (um terço) da carga horária exigida; e/ou
"""

TEXTO_COM_CAUDA = """\
=== página 51 ===
Art. 215. Por caso fortuito, o estudante pode interpor recurso.
Art. 216. Os casos omissos nesta Resolução serão resolvidos pelo CONGRAD.".

Art. 2º O art. 2º da Resolução nº 05/2016, do Conselho de Graduação, passa a vigorar com
a seguinte redação:
“Art. 2º A Colação de Grau é ato oficial, público e obrigatório.”.

Art. 3º Revoga-se a Resolução nº 15/2011, do Conselho de Graduação.

Art. 4º Esta Resolução entra em vigor na data de sua publicação.

VALDER STEFFEN JUNIOR
Presidente

Referência: Processo nº 23117.055414/2021-05
SEI nº 5346187
"""


def test_artigo_com_nbsp_no_inicio_da_linha_e_reconhecido():
    trechos = dividir_em_artigos(TEXTO_NBSP)
    assert [t["artigo"] for t in trechos] == ["17", "18", "19"]
    assert "parecer da PROGRAD" not in normalizar(trechos[0]["texto"])
    assert "alteração de pré-requisitos" in normalizar(trechos[1]["texto"])


def test_artigo_com_recuo_no_regimento_uniube():
    trechos = dividir_em_artigos(TEXTO_RECUO)
    assert [t["artigo"] for t in trechos] == ["45", "46", "47", "48"]
    assert "A avaliação é parte integrante" not in normalizar(trechos[0]["texto"])
    assert "A avaliação é parte integrante" in normalizar(trechos[1]["texto"])


def test_marcacao_partida_entre_paginas_sai_inteira():
    t = dividir_em_artigos(TEXTO_MARCACAO_ENTRE_PAGINAS)[0]
    texto = normalizar(t["texto"])
    assert "Redação dada" not in texto
    assert "CONGRAD" not in texto
    assert "faltar até 1/3" in texto
    assert any("78" in a for a in t["alteracoes"])
    assert t["paginas"] == [46, 47]


def test_cauda_depois_do_ultimo_artigo_e_descartada():
    trechos = dividir_em_artigos(TEXTO_COM_CAUDA)
    assert [t["artigo"] for t in trechos] == ["215", "216"]
    texto = normalizar(trechos[1]["texto"])
    assert texto.endswith("resolvidos pelo CONGRAD.")
    for lixo in ("Colação", "Revoga-se", "VALDER", "Referência", "SEI nº"):
        assert lixo not in texto

TEXTO_COM_APROVACAO = """\
=== página 1 ===
Art. 1º Aprovar as Normas Gerais de Estágio, na forma do Anexo desta Resolução.
Art. 2º Ficam revogadas:
I – a Resolução nº 24/2012, do Conselho de Graduação.
Art. 3º Esta Resolução entra em vigor na data de sua publicação.
ANEXO
NORMAS GERAIS DE ESTÁGIO
Art. 1º Estas Normas disciplinam o estágio dos estudantes de graduação.
Art. 2º O estágio é ato educativo escolar supervisionado.
Art. 3º O estágio pode ser obrigatório ou não obrigatório.
"""

TEXTO_CITACAO_DE_ARTIGO_1 = """\
=== página 1 ===
Art. 1º Estas Normas disciplinam o estágio.
Art. 2º O estágio é ato educativo.
Art. 12. O estágio obedece à legislação, em especial ao disposto
Art. 1º da Lei nº 11.788, de 25 de setembro de 2008, e demais exceções.
Art. 13. Compete à Coordenação acompanhar o estágio.
"""

TEXTO_TITULO_COM_LINHA_EM_BRANCO = """\
=== página 10 ===
Art. 28. O ano letivo terá, no mínimo, 200 dias de trabalhos acadêmicos efetivos.
 
CAPÍTULO II

DO PERÍODO LETIVO ESPECIAL

Art. 29. O período letivo especial destina-se ao oferecimento de componentes curriculares.
"""

TEXTO_TITULO_CAIXA_ALTA_ISOLADO = """\
=== página 12 ===
Art. 38. O ingresso nos cursos é feito por uma das seguintes formas.

DOS EDITAIS E SUAS PARTES

Art. 39. Caberá à DIRPS a responsabilidade pela elaboração dos editais.
"""

TEXTO_CAPITULO_CAIXA_MISTA = """\
=== página 2 ===
Art. 1º Este Regimento disciplina as atividades comuns da Universidade.

Capítulo II

DA ORGANIZAÇÃO DIDÁTICA

Art. 2º Os cursos de graduação são organizados em currículos plenos.
"""


def test_preambulo_de_aprovacao_e_descartado():
    trechos = dividir_em_artigos(TEXTO_COM_APROVACAO)
    assert [t["artigo"] for t in trechos] == ["1", "2", "3"]
    assert "Estas Normas disciplinam" in normalizar(trechos[0]["texto"])
    texto2 = normalizar(trechos[1]["texto"])
    assert "ato educativo" in texto2
    assert "Ficam revogadas" not in texto2


def test_citacao_de_artigo_1_no_corpo_nao_reinicia_a_contagem():
    trechos = dividir_em_artigos(TEXTO_CITACAO_DE_ARTIGO_1)
    assert [t["artigo"] for t in trechos] == ["1", "2", "12", "13"]
    assert "Art. 1º da Lei nº 11.788" in normalizar(trechos[2]["texto"])


def test_titulo_separado_do_nome_por_linha_em_branco():
    art28, art29 = dividir_em_artigos(TEXTO_TITULO_COM_LINHA_EM_BRANCO)
    assert "CAPÍTULO" not in art28["texto"]
    assert "ESPECIAL" not in art28["texto"]
    assert "CAPÍTULO II" in art29["capitulo"]
    assert "DO PERÍODO LETIVO ESPECIAL" in art29["capitulo"]


def test_titulo_em_caixa_alta_isolado_vira_secao():
    art38, art39 = dividir_em_artigos(TEXTO_TITULO_CAIXA_ALTA_ISOLADO)
    assert "DOS EDITAIS" not in art38["texto"]
    assert "DOS EDITAIS E SUAS PARTES" in art39["secao"]


def test_capitulo_com_caixa_mista_e_linha_em_branco():
    art1, art2 = dividir_em_artigos(TEXTO_CAPITULO_CAIXA_MISTA)
    assert "Capítulo" not in art1["texto"]
    assert "DA ORGANIZAÇÃO DIDÁTICA" not in art1["texto"]
    assert "Capítulo II" in art2["capitulo"]
    assert "DA ORGANIZAÇÃO DIDÁTICA" in art2["capitulo"]