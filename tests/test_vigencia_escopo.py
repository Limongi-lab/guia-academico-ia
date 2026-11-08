from guia.ingestao.resolucoes import dividir_em_artigos

ART_157 = """\
=== página 39 ===
Art. 157. O exame de suficiência será concedido, em um ou mais componentes
curriculares, ao estudante que demonstre excepcional rendimento acadêmico a partir do atendimento de
todas as seguintes condições:
I – ter cumprido os pré-requisitos estabelecidos para os componentes curriculares para os
quais solicita exame de suficiência;
II – não ter aprovação ou reprovação nos componentes curriculares para os quais solicita
exame de suficiência;
III – não ter realizado exame de suficiência nos mesmos componentes curriculares para os
quais solicita exame de suficiência; e
IV – ter CRA geral igual ou superior a 85 (oitenta e cinco) pontos.
§ 1º Não poderá ser aplicado exame de suficiência para os seguintes componentes
curriculares:
I – atividades acadêmicas complementares; e
I – atividades acadêmicas complementares; (Redação dada pela Resolução CONGRAD nº
78, de 16 de novembro de 2022)
II –  atividades curriculares de extensão.
II – atividades curriculares de extensão; (Redação dada pela Resolução CONGRAD nº 78, de
16 de novembro de 2022)
III – estágios obrigatórios; (Incluído pela Resolução CONGRAD nº 78, de 16 de novembro de
2022)
IV – práticas especificas; e (Incluído pela Resolução CONGRAD nº 78, de 16 de novembro
de 2022)
V – Trabalho de Conclusão de Curso. (Incluído pela Resolução CONGRAD nº 78, de 16 de novembro
de 2022)
§ 2º O Colegiado poderá aprovar norma específica que estabeleça outros componentes
curriculares para os quais o exame de suficiência não será aplicado.
=== página 40 ===
Art. 158. Texto qualquer do artigo seguinte.
"""

CAPUT_E_PARAGRAFOS = """\
=== página 5 ===
Art. 200. Os requisitos são os seguintes:
I – requisito alfa do caput;
II – requisito beta do caput;
§ 1º Dos documentos:
I – documento gama do primeiro parágrafo;
II – documento delta do primeiro parágrafo;
§ 2º Dos prazos:
I – prazo epsilon do segundo parágrafo;
Art. 201. Texto qualquer do artigo seguinte.
"""

PARAGRAFO_UNICO = """\
=== página 5 ===
Art. 210. Os casos são:
I – caso alfa do caput;
II – caso beta do caput;
Parágrafo único. Dos incisos:
I – inciso gama do paragrafo unico;
II – inciso delta do paragrafo unico;
Art. 211. Texto qualquer do artigo seguinte.
"""

SUBSTITUICAO_NO_CAPUT = """\
=== página 5 ===
Art. 220. As condições são:
I – condição alfa antiga;
I – condição alfa nova; (Redação dada pela Resolução CONGRAD nº 120, de 29 de novembro de 2023)
II – condição beta do caput;
§ 1º Das exceções:
I – exceção gama do paragrafo;
II – exceção delta do paragrafo;
Art. 221. Texto qualquer do artigo seguinte.
"""

PARAGRAFO_SUBSTITUIDO = """\
=== página 5 ===
Art. 230. As regras são:
I – regra alfa do caput;
§ 1º Das exceções antigas:
I – exceção antiga um;
II – exceção antiga dois;
§ 1º Das exceções novas: (Redação dada pela Resolução CONGRAD nº 78, de 16 de novembro de 2022)
I – exceção nova um;
II – exceção nova dois;
Art. 231. Texto qualquer do artigo seguinte.
"""

REVOGADO_NO_PARAGRAFO = """\
=== página 5 ===
Art. 240. As regras são:
I – regra alfa do caput;
II – regra beta do caput;
§ 1º Das exceções:
I – exceção gama do paragrafo;
II – exceção delta revogada; (Revogado pela Resolução CONGRAD nº 78, de 16 de novembro de 2022)
Art. 241. Texto qualquer do artigo seguinte.
"""


def _texto(documento, numero):
    achados = [t for t in dividir_em_artigos(documento) if t["artigo"] == numero]
    assert len(achados) == 1
    return " ".join(achados[0]["texto"].split())


def test_art_157_mantem_os_quatro_incisos_do_caput():
    texto = _texto(ART_157, "157")
    assert "ter cumprido os pré-requisitos estabelecidos" in texto
    assert "não ter aprovação ou reprovação nos componentes" in texto
    assert "não ter realizado exame de suficiência nos mesmos componentes" in texto
    assert "ter CRA geral igual ou superior a 85 (oitenta e cinco) pontos" in texto


def test_art_157_mantem_os_incisos_vigentes_do_paragrafo_primeiro_uma_vez_so():
    texto = _texto(ART_157, "157")
    assert texto.count("atividades acadêmicas complementares") == 1
    assert texto.count("atividades curriculares de extensão") == 1
    assert "estágios obrigatórios" in texto
    assert "práticas especificas" in texto
    assert "Trabalho de Conclusão de Curso" in texto
    assert "O Colegiado poderá aprovar norma específica" in texto


def test_art_157_nao_deixa_marcacoes_no_texto():
    texto = _texto(ART_157, "157")
    for marca in ("(Redação dada", "(Revogado", "(Incluído"):
        assert marca not in texto


def test_art_157_continua_com_um_trecho_por_artigo():
    numeros = [t["artigo"] for t in dividir_em_artigos(ART_157)]
    assert numeros == ["157", "158"]


def test_incisos_com_o_mesmo_numero_em_escopos_diferentes_sao_todos_mantidos():
    texto = _texto(CAPUT_E_PARAGRAFOS, "200")
    for parte in ("requisito alfa do caput", "requisito beta do caput",
                  "documento gama do primeiro parágrafo", "documento delta do primeiro parágrafo",
                  "prazo epsilon do segundo parágrafo"):
        assert parte in texto


def test_incisos_do_paragrafo_unico_nao_apagam_os_do_caput():
    texto = _texto(PARAGRAFO_UNICO, "210")
    for parte in ("caso alfa do caput", "caso beta do caput",
                  "inciso gama do paragrafo unico", "inciso delta do paragrafo unico"):
        assert parte in texto


def test_substituicao_no_caput_remove_so_a_versao_antiga_do_caput():
    texto = _texto(SUBSTITUICAO_NO_CAPUT, "220")
    assert "condição alfa antiga" not in texto
    assert "condição alfa nova" in texto
    assert "condição beta do caput" in texto
    assert "exceção gama do paragrafo" in texto
    assert "exceção delta do paragrafo" in texto


def test_paragrafo_substituido_leva_consigo_os_incisos_antigos():
    texto = _texto(PARAGRAFO_SUBSTITUIDO, "230")
    assert "regra alfa do caput" in texto
    assert "exceção antiga um" not in texto
    assert "exceção antiga dois" not in texto
    assert "Das exceções antigas" not in texto
    assert "exceção nova um" in texto
    assert "exceção nova dois" in texto


def test_inciso_revogado_no_paragrafo_sai_sem_afetar_o_caput():
    texto = _texto(REVOGADO_NO_PARAGRAFO, "240")
    assert "regra alfa do caput" in texto
    assert "regra beta do caput" in texto
    assert "exceção gama do paragrafo" in texto
    assert "exceção delta revogada" not in texto
