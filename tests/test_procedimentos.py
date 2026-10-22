"""Divisão de documentos de procedimento ("passo a passo") em passos.

Contrato:
    dividir_passos(texto: str) -> list[dict]
em guia.ingestao.procedimentos. O texto de entrada é o .txt extraído do PDF, com
marcadores "=== página N ===". Cada passo é um dict:
    passo (int), ator (str), texto (str), paginas (list[int]), titulo_doc (str)
"""
from guia.ingestao.procedimentos import dividir_passos

TEXTO = (
    "=== página 1 ===\n"
    "PASSO A PASSO - FORMALIZAÇÃO DE DISCIPLINA\n"
    "ESTÁGIO OBRIGATÓRIO - GESTÃO DA INFORMAÇÃO - GGI042\n"
    "1º (ALUNO)  Acessar o site da FAGEN (http://www.fagen.ufu.br/fagen/estagio-\n"
    "supervisionado) e baixar o formulário.\n"
    "2º    (ALUNO)  Cadastrar no sistema SEI-\n"
    "UFU como USUÁRIO EXTERNO.\n"
    "3º     (ALUNO)    Preencher o formulário.\n"
    "4º   (ALUNO)    Enviar e-mail para a Coordenação (estagio@fagen.ufu.br), anexando:\n"
    "1 -  O formulário preenchido;\n"
    "2 - Quando optar por:\n"
    "a) ESTÁGIO REGULAR - Cópia do Termo de Compromisso; OU\n"
    "b) EQUIVALÊNCIA DE ESTÁGIO - uma das opções:\n"
    "i) Vínculo Empregatício superior a 12 meses - Cópia da Carteira profissional; OU\n"
    "\n"
    "\n"
    "=== página 2 ===\n"
    "ii) Iniciação Científica - Cópia do termo de concessão; OU\n"
    "iii) Servidor Público - Cópia do termo de posse.\n"
    "5º   (COORDENAÇÃO DE ESTÁGIO)    Receberá o formulário e abrirá o processo no SEI.\n"
    "6º   (ALUNO E PROFESSOR ORIENTADOR )    Assinarão o formulário no SEI.\n"
)

TITULO = (
    "PASSO A PASSO - FORMALIZAÇÃO DE DISCIPLINA - "
    "ESTÁGIO OBRIGATÓRIO - GESTÃO DA INFORMAÇÃO - GGI042"
)


def test_divide_em_passos_numerados_e_extrai_o_ator():
    r = dividir_passos(TEXTO)
    assert [p["passo"] for p in r] == [1, 2, 3, 4, 5, 6]
    assert [p["ator"] for p in r] == [
        "ALUNO", "ALUNO", "ALUNO", "ALUNO",
        "COORDENAÇÃO DE ESTÁGIO", "ALUNO E PROFESSOR ORIENTADOR",
    ]


def test_texto_do_passo_normaliza_espacos_e_mantem_as_quebras_de_linha():
    r = dividir_passos(TEXTO)
    assert r[0]["texto"] == (
        "1º (ALUNO) Acessar o site da FAGEN (http://www.fagen.ufu.br/fagen/estagio-\n"
        "supervisionado) e baixar o formulário."
    )
    assert r[1]["texto"] == "2º (ALUNO) Cadastrar no sistema SEI-\nUFU como USUÁRIO EXTERNO."
    assert r[5]["texto"] == "6º (ALUNO E PROFESSOR ORIENTADOR) Assinarão o formulário no SEI."


def test_subitens_ficam_dentro_do_passo_e_o_texto_atravessa_a_pagina():
    passo4 = dividir_passos(TEXTO)[3]["texto"]
    assert passo4 == (
        "4º (ALUNO) Enviar e-mail para a Coordenação (estagio@fagen.ufu.br), anexando:\n"
        "1 - O formulário preenchido;\n"
        "2 - Quando optar por:\n"
        "a) ESTÁGIO REGULAR - Cópia do Termo de Compromisso; OU\n"
        "b) EQUIVALÊNCIA DE ESTÁGIO - uma das opções:\n"
        "i) Vínculo Empregatício superior a 12 meses - Cópia da Carteira profissional; OU\n"
        "ii) Iniciação Científica - Cópia do termo de concessão; OU\n"
        "iii) Servidor Público - Cópia do termo de posse."
    )


def test_paginas_de_cada_passo():
    r = dividir_passos(TEXTO)
    assert [p["paginas"] for p in r] == [[1], [1], [1], [1, 2], [2], [2]]


def test_marcadores_de_pagina_nao_aparecem_no_texto():
    assert all("=== página" not in p["texto"] for p in dividir_passos(TEXTO))


def test_titulo_do_documento_vai_em_todos_os_passos():
    assert all(p["titulo_doc"] == TITULO for p in dividir_passos(TEXTO))


def test_numero_fora_de_sequencia_nao_abre_passo_novo():
    texto = (
        "1º (ALUNO) Primeiro.\n"
        "2º (ALUNO) Segundo.\n"
        "7º (COORDENAÇÃO) citação solta no meio do passo.\n"
        "3º (ALUNO) Terceiro.\n"
    )
    r = dividir_passos(texto)
    assert [p["passo"] for p in r] == [1, 2, 3]
    assert "7º (COORDENAÇÃO) citação solta no meio do passo." in r[1]["texto"]


def test_formato_com_hifen_apos_o_ator_passos_de_dois_digitos_e_subitens():
    linhas = ["PASSO A PASSO - TRABALHO DE CONCLUSÃO - GGI095"]
    linhas.append("1º (PROFESSOR ORIENTADOR) - Solicitar que o discente se matricule.")
    for n in range(2, 10):
        linhas.append(f"{n}º (ALUNO) Faz a etapa {n}.")
    linhas += [
        "10º (PROFESSOR ORIENTADOR) Reabrirá o processo e considerará:",
        "I - O documento inserido;",
        "i) Caso os membros sejam do mesmo Departamento;",
        "ii) Caso sejam de Departamentos diferentes.",
        "11º (PROFESSORES BANCA EXAMINADORA) Assinarão a ata.",
    ]
    r = dividir_passos("\n".join(linhas))
    assert [p["passo"] for p in r] == list(range(1, 12))
    assert r[0]["ator"] == "PROFESSOR ORIENTADOR"
    assert r[0]["texto"] == "1º (PROFESSOR ORIENTADOR) - Solicitar que o discente se matricule."
    assert r[9]["ator"] == "PROFESSOR ORIENTADOR"
    assert "i) Caso os membros sejam do mesmo Departamento;" in r[9]["texto"]
    assert "ii) Caso sejam de Departamentos diferentes." in r[9]["texto"]
    assert r[10]["ator"] == "PROFESSORES BANCA EXAMINADORA"


def test_sem_marcadores_de_pagina_as_paginas_ficam_vazias():
    r = dividir_passos("TÍTULO\n1º (ALUNO) Faz isto.\n2º (ALUNO) Faz aquilo.")
    assert [p["paginas"] for p in r] == [[], []]


def test_texto_sem_passos_ou_sem_o_passo_1_devolve_lista_vazia():
    assert dividir_passos("Um texto qualquer\nsem passos numerados.") == []
    assert dividir_passos("2º (ALUNO) Começa no 2.\n3º (ALUNO) Segue.") == []
