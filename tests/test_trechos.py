"""Registro único de trecho (artigo, passo, seção de página) para o banco.

Contrato, em guia.ingestao.trechos:
    formatar_paginas(paginas) -> str                    ("p. 2", "p. 7-8", "p. 2-3, 5" ou "")
    montar_trecho_artigo(parte_artigo, doc) -> dict      (parte_artigo vem de dividir_artigo)
    montar_trecho_passo(passo, doc) -> dict              (passo vem de dividir_passos)
    montar_trechos_pagina(pagina, doc, limite=1500) -> list[dict]  (pagina vem de extrair_pagina_fagen)
"doc" é a entrada da fonte em fontes.json (id, instituicao, titulo, url, tipo, data_ref, prioridade).
Todo registro tem as chaves: id, doc_id, local_id, tipo_doc, instituicao, titulo_doc, url,
data_ref, prioridade, paginas, localizacao, citacao, texto, pai_id, parte, total_partes,
hash_texto, metadados. O local_id sempre termina em "#<parte>". Trechos irmãos (mesma
unidade lógica) compartilham o pai_id.
"""
import copy
import hashlib

import pytest

from guia.ingestao.trechos import (
    formatar_paginas,
    montar_trecho_artigo,
    montar_trecho_passo,
    montar_trechos_pagina,
)


def _sha(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


# ---------- páginas ----------

@pytest.mark.parametrize(
    "paginas,esperado",
    [
        ([], ""),
        ([2], "p. 2"),
        ([2, 2], "p. 2"),
        ([7, 8], "p. 7-8"),
        ([1, 2, 3], "p. 1-3"),
        ([2, 4], "p. 2, 4"),
        ([2, 3, 5], "p. 2-3, 5"),
        ([3, 1, 2], "p. 1-3"),
    ],
)
def test_formatar_paginas(paginas, esperado):
    assert formatar_paginas(paginas) == esperado


# ---------- artigo ----------

DOC_NORMAS = {
    "id": "ufu-normas-gerais-graduacao",
    "instituicao": "ufu",
    "titulo": "Normas Gerais da Graduação da UFU (Res. CONGRAD 46/2022)",
    "url": "https://exemplo.ufu.br/normas.pdf",
    "tipo": "pdf",
    "data_ref": "2024-04-18",
    "prioridade": 1,
}


def _peca(artigo="2", paginas=None, **extra):
    base = {
        "artigo": artigo,
        "texto": f"Art. {artigo}º Texto do artigo.",
        "paginas": [2] if paginas is None else paginas,
        "alteracoes": ["Resolução CONGRAD nº 78/2022"],
        "capitulo": "CAPÍTULO I DAS DEFINIÇÕES",
        "secao": "",
        "id": f"art-{artigo}#3",
        "parte": 3,
        "total_partes": 13,
    }
    base.update(extra)
    return base


def test_trecho_de_artigo_completo():
    r = montar_trecho_artigo(_peca(), DOC_NORMAS)
    assert r == {
        "id": "ufu-normas-gerais-graduacao/art-2#3",
        "doc_id": "ufu-normas-gerais-graduacao",
        "local_id": "art-2#3",
        "tipo_doc": "resolucao",
        "instituicao": "ufu",
        "titulo_doc": DOC_NORMAS["titulo"],
        "url": DOC_NORMAS["url"],
        "data_ref": "2024-04-18",
        "prioridade": 1,
        "paginas": [2],
        "localizacao": {"capitulo": "CAPÍTULO I DAS DEFINIÇÕES", "secao": "", "artigo": "2"},
        "citacao": "Art. 2º, p. 2",
        "texto": "Art. 2º Texto do artigo.",
        "pai_id": "ufu-normas-gerais-graduacao/art-2",
        "parte": 3,
        "total_partes": 13,
        "hash_texto": _sha("Art. 2º Texto do artigo."),
        "metadados": {"alteracoes": ["Resolução CONGRAD nº 78/2022"]},
    }


def test_numero_do_artigo_pode_vir_como_int():
    r = montar_trecho_artigo(_peca(artigo=2, id="art-2#3"), DOC_NORMAS)
    assert r["localizacao"]["artigo"] == "2"
    assert r["pai_id"] == "ufu-normas-gerais-graduacao/art-2"
    assert r["citacao"] == "Art. 2º, p. 2"


@pytest.mark.parametrize(
    "artigo,paginas,esperado",
    [
        ("1", [1], "Art. 1º, p. 1"),
        ("9", [3], "Art. 9º, p. 3"),
        ("10", [3], "Art. 10, p. 3"),
        ("20", [7, 8], "Art. 20, p. 7-8"),
        ("30", [2, 4], "Art. 30, p. 2, 4"),
        ("5", [], "Art. 5º"),
    ],
)
def test_citacao_do_artigo_usa_ordinal_so_ate_o_9(artigo, paginas, esperado):
    r = montar_trecho_artigo(_peca(artigo=artigo, paginas=paginas, id=f"art-{artigo}#1"), DOC_NORMAS)
    assert r["citacao"] == esperado


@pytest.mark.parametrize(
    "data_ref,esperado",
    [
        ("2024-04-18", "2024-04-18"),
        ("2022-05", "2022-05"),
        ("2015", "2015"),
        ("A confirmar", None),
        ("", None),
    ],
)
def test_data_ref_so_aceita_formato_de_data(data_ref, esperado):
    doc = dict(DOC_NORMAS, data_ref=data_ref)
    assert montar_trecho_artigo(_peca(), doc)["data_ref"] == esperado


def test_artigo_nao_altera_a_entrada():
    peca, doc = _peca(), dict(DOC_NORMAS)
    original = (copy.deepcopy(peca), copy.deepcopy(doc))
    r = montar_trecho_artigo(peca, doc)
    r["paginas"].append(99)
    r["metadados"]["alteracoes"].append("x")
    assert (peca, doc) == original


# ---------- passo ----------

DOC_PASSO = {
    "id": "fagen-gi-estagio-passo-a-passo",
    "instituicao": "ufu",
    "titulo": "Passo a passo - matrícula interna em Estágio Obrigatório GGI042 (FAGEN)",
    "url": "http://www.fagen.ufu.br/system/files/conteudo/02_passo_a_passo.pdf",
    "tipo": "pdf",
    "data_ref": "A confirmar",
    "prioridade": 1,
}

PASSO = {
    "passo": 4,
    "ator": "ALUNO",
    "texto": "4º (ALUNO) Enviar e-mail para a Coordenação.",
    "paginas": [1, 2],
    "titulo_doc": "PASSO A PASSO - FORMALIZAÇÃO DE DISCIPLINA - ESTÁGIO OBRIGATÓRIO - GGI042",
}


def test_trecho_de_passo_completo():
    r = montar_trecho_passo(PASSO, DOC_PASSO)
    assert r == {
        "id": "fagen-gi-estagio-passo-a-passo/passo-4#1",
        "doc_id": "fagen-gi-estagio-passo-a-passo",
        "local_id": "passo-4#1",
        "tipo_doc": "procedimento",
        "instituicao": "ufu",
        "titulo_doc": DOC_PASSO["titulo"],
        "url": DOC_PASSO["url"],
        "data_ref": None,
        "prioridade": 1,
        "paginas": [1, 2],
        "localizacao": {"passo": 4, "ator": "ALUNO"},
        "citacao": "Passo 4 (ALUNO), p. 1-2",
        "texto": "4º (ALUNO) Enviar e-mail para a Coordenação.",
        "pai_id": "fagen-gi-estagio-passo-a-passo",
        "parte": 1,
        "total_partes": 1,
        "hash_texto": _sha("4º (ALUNO) Enviar e-mail para a Coordenação."),
        "metadados": {"titulo_no_documento": PASSO["titulo_doc"]},
    }


# ---------- página ----------

DOC_PAG = {
    "id": "fagen-gi-estagio",
    "instituicao": "ufu",
    "titulo": "Estágio Supervisionado - Gestão da Informação (página FAGEN)",
    "url": "https://fagen.ufu.br/servicos/estagio-supervisionado",
    "tipo": "html",
    "data_ref": "A confirmar",
    "prioridade": 1,
}

CONTATO_FAGEN = {
    "setor": "Coordenação de Estágio e Trabalho de Curso",
    "email": "estagio@fagen.ufu.br",
    "telefone": "+55 34 3230-9481",
    "ramal": "9481",
}

CONTATO_PROGRAD = {
    "setor": "Setor de Estágio",
    "email": "estagio@prograd.ufu.br",
    "telefone": "34 3291-8984 / 34 3291-8983",
    "ramal": None,
    "endereco": "Av. João Naves de Ávila, 2121 - Bloco 3P - Sala(s) 09 - Bairro Santa Mônica",
    "horario": "De segunda a sexta das 8h às 12h e 13h às 17h (exceto feriados)",
}

META = {
    "curso": ["Gestão da Informação"],
    "publico_alvo": ["Estudante"],
    "assunto": ["Documentos"],
}


def _pagina(secoes, contato=None, atualizado="2024-08-26"):
    return {
        "titulo": "Estágio Supervisionado",
        "publicado_em": "2021-08-17",
        "atualizado_em": atualizado,
        "publico_alvo": ["Estudante"],
        "curso": ["Gestão da Informação"],
        "assunto": ["Documentos"],
        "secoes": secoes,
        "anexos": [],
        "contato": contato,
    }


def _bloco(marca, tamanho):
    return (f"{marca} " + "texto " * 300)[:tamanho].strip()


def test_um_trecho_por_secao_com_registro_completo():
    secoes = [
        {"titulo": "", "texto": "Primeiro parágrafo.\n\nSegundo parágrafo."},
        {"titulo": "Requisitos", "texto": "Lista:\n\n- a\n- b"},
    ]
    r = montar_trechos_pagina(_pagina(secoes), DOC_PAG)
    assert [t["local_id"] for t in r] == ["secao-1#1", "secao-2#1"]
    assert [t["citacao"] for t in r] == ["Texto principal", "Requisitos"]
    assert r[0]["texto"] == "Primeiro parágrafo.\n\nSegundo parágrafo."
    assert r[1] == {
        "id": "fagen-gi-estagio/secao-2#1",
        "doc_id": "fagen-gi-estagio",
        "local_id": "secao-2#1",
        "tipo_doc": "pagina",
        "instituicao": "ufu",
        "titulo_doc": DOC_PAG["titulo"],
        "url": DOC_PAG["url"],
        "data_ref": "2024-08-26",
        "prioridade": 1,
        "paginas": [],
        "localizacao": {"tipo": "secao", "secao": "Requisitos"},
        "citacao": "Requisitos",
        "texto": "Lista:\n\n- a\n- b",
        "pai_id": "fagen-gi-estagio/secao-2",
        "parte": 1,
        "total_partes": 1,
        "hash_texto": _sha("Lista:\n\n- a\n- b"),
        "metadados": META,
    }


def test_secoes_vazias_sao_puladas_e_a_numeracao_segue_a_pagina():
    secoes = [
        {"titulo": "", "texto": "   \n "},
        {"titulo": "Requisitos", "texto": "Texto."},
    ]
    r = montar_trechos_pagina(_pagina(secoes), DOC_PAG)
    assert [t["local_id"] for t in r] == ["secao-2#1"]


def test_contato_da_fagen_vira_o_ultimo_trecho():
    secoes = [{"titulo": "Orientações", "texto": "Texto."}]
    r = montar_trechos_pagina(_pagina(secoes, CONTATO_FAGEN), DOC_PAG)
    ultimo = r[-1]
    assert [t["local_id"] for t in r] == ["secao-1#1", "contato#1"]
    assert ultimo["id"] == "fagen-gi-estagio/contato#1"
    assert ultimo["citacao"] == "Contato"
    assert ultimo["localizacao"] == {"tipo": "contato"}
    assert ultimo["pai_id"] == "fagen-gi-estagio/contato"
    assert ultimo["metadados"] == META
    assert ultimo["texto"] == (
        "Contato: Coordenação de Estágio e Trabalho de Curso\n"
        "E-mail: estagio@fagen.ufu.br\n"
        "Telefone: +55 34 3230-9481 (ramal 9481)"
    )
    assert ultimo["hash_texto"] == _sha(ultimo["texto"])


def test_contato_da_prograd_inclui_endereco_e_horario():
    r = montar_trechos_pagina(_pagina([], CONTATO_PROGRAD), DOC_PAG)
    assert len(r) == 1
    assert r[0]["texto"] == (
        "Contato: Setor de Estágio\n"
        "E-mail: estagio@prograd.ufu.br\n"
        "Telefone: 34 3291-8984 / 34 3291-8983\n"
        "Endereço: Av. João Naves de Ávila, 2121 - Bloco 3P - Sala(s) 09 - Bairro Santa Mônica\n"
        "Horário de atendimento: De segunda a sexta das 8h às 12h e 13h às 17h (exceto feriados)"
    )


def test_sem_contato_nao_gera_trecho_de_contato():
    r = montar_trechos_pagina(_pagina([{"titulo": "", "texto": "Texto."}]), DOC_PAG)
    assert [t["local_id"] for t in r] == ["secao-1#1"]


@pytest.mark.parametrize(
    "atualizado,data_ref_fonte,esperado",
    [
        ("2024-08-26", "A confirmar", "2024-08-26"),
        (None, "2023-01-16", "2023-01-16"),
        (None, "A confirmar", None),
    ],
)
def test_data_ref_da_pagina_cai_para_a_da_fonte(atualizado, data_ref_fonte, esperado):
    doc = dict(DOC_PAG, data_ref=data_ref_fonte)
    r = montar_trechos_pagina(_pagina([{"titulo": "", "texto": "Texto."}], atualizado=atualizado), doc)
    assert r[0]["data_ref"] == esperado


def test_secao_longa_e_dividida_por_paragrafos_sem_cortar_nenhum():
    p1, p2, p3 = _bloco("BLOCO1", 700), _bloco("BLOCO2", 700), _bloco("BLOCO3", 700)
    secoes = [{"titulo": "Regras", "texto": f"{p1}\n\n{p2}\n\n{p3}"}]
    r = montar_trechos_pagina(_pagina(secoes), DOC_PAG)
    assert [t["local_id"] for t in r] == ["secao-1#1", "secao-1#2"]
    assert [(t["parte"], t["total_partes"]) for t in r] == [(1, 2), (2, 2)]
    assert r[0]["texto"] == f"{p1}\n\n{p2}"
    assert r[1]["texto"] == p3
    assert {t["pai_id"] for t in r} == {"fagen-gi-estagio/secao-1"}
    assert {t["citacao"] for t in r} == {"Regras"}


def test_introducao_de_lista_fica_junto_com_a_lista():
    grande = _bloco("GRANDE", 900)
    intro = _bloco("INTRO", 300).rstrip(".") + ":"
    lista = "- ITEM1 " + "x" * 190 + "\n- ITEM2 " + "y" * 190
    secoes = [{"titulo": "", "texto": f"{grande}\n\n{intro}\n\n{lista}"}]
    r = montar_trechos_pagina(_pagina(secoes), DOC_PAG)
    assert len(r) == 2
    com_intro = [t for t in r if "INTRO" in t["texto"]]
    assert len(com_intro) == 1 and "- ITEM1" in com_intro[0]["texto"]


def test_bloco_maior_que_o_limite_nao_e_cortado():
    gigante = _bloco("GIGANTE", 3000)
    r = montar_trechos_pagina(_pagina([{"titulo": "", "texto": gigante}]), DOC_PAG)
    assert len(r) == 1 and r[0]["texto"] == gigante


def test_limite_e_configuravel():
    blocos = [_bloco(f"B{i}", 300) for i in range(3)]
    secoes = [{"titulo": "", "texto": "\n\n".join(blocos)}]
    assert len(montar_trechos_pagina(_pagina(secoes), DOC_PAG)) == 1
    assert len(montar_trechos_pagina(_pagina(secoes), DOC_PAG, limite=500)) == 3


def test_pagina_nao_altera_a_entrada():
    pagina = _pagina([{"titulo": "", "texto": "Texto."}], CONTATO_FAGEN)
    doc = dict(DOC_PAG)
    original = (copy.deepcopy(pagina), copy.deepcopy(doc))
    r = montar_trechos_pagina(pagina, doc)
    r[0]["metadados"]["curso"].append("x")
    assert (pagina, doc) == original
