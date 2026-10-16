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