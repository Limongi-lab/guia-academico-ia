"""Páginas por trecho.

Parte 1 (parser): dividir_em_artigos passa a devolver "marcas_pagina" em cada artigo:
    lista de [posicao, pagina], onde posicao é o índice, em artigo["texto"], do primeiro
    caractere não vazio que pertence àquela página. A primeira marca é sempre [0, pagina].
Parte 2 (divisão): dividir_artigo usa "marcas_pagina" para calcular as páginas de cada
    trecho (só as páginas do corpo do trecho; o caput repetido não conta).
"""
import copy

import pytest

from guia.ingestao.divisao import dividir_artigo
from guia.ingestao.resolucoes import dividir_em_artigos

# ======================= PARTE 1: parser =======================

DOC = (
    "=== página 1 ===\n"
    "Art. 1º Primeira regra do documento.\n"
    "Art. 2º Segunda regra começa na página um\n"
    "=== página 2 ===\n"
    "e continua na página dois.\n"
    "Art. 3º Terceira regra começa na página dois\n"
    "=== página 3 ===\n"
    "continua na página três\n"
    "=== página 4 ===\n"
    "e termina na página quatro.\n"
    "Art. 4º Quarta regra inteira na página quatro.\n"
    "=== página 5 ===\n"
    "Art. 5º Quinta regra inteira na página cinco.\n"
    "Art. 6º Sexta regra, só para não ser a última.\n"
)


def _por_numero():
    return {a["artigo"]: a for a in dividir_em_artigos(DOC)}


def _marcas(artigo):
    return [tuple(m) for m in artigo["marcas_pagina"]]


def test_artigo_numa_pagina_so_tem_uma_marca():
    a = _por_numero()["1"]
    assert _marcas(a) == [(0, 1)]
    assert a["paginas"] == [1]


def test_artigo_que_cruza_pagina_marca_onde_a_nova_pagina_comeca():
    a = _por_numero()["2"]
    assert a["paginas"] == [1, 2]
    marcas = _marcas(a)
    assert len(marcas) == 2
    assert marcas[0] == (0, 1)
    pos, pagina = marcas[1]
    assert pagina == 2
    assert a["texto"][pos:].startswith("e continua na página dois")


def test_artigo_que_cruza_varias_paginas():
    a = _por_numero()["3"]
    marcas = _marcas(a)
    assert [p for _, p in marcas] == [2, 3, 4]
    assert marcas[0][0] == 0
    inicios = ["continua na página três", "e termina na página quatro"]
    for (pos, _), inicio in zip(marcas[1:], inicios):
        assert a["texto"][pos:].startswith(inicio)


def test_artigo_logo_depois_de_um_marcador_pertence_a_essa_pagina():
    a = _por_numero()["5"]
    assert _marcas(a) == [(0, 5)]
    assert a["paginas"] == [5]


def test_invariantes_das_marcas_em_todos_os_artigos():
    for a in dividir_em_artigos(DOC):
        marcas = _marcas(a)
        assert marcas and marcas[0][0] == 0
        posicoes = [p for p, _ in marcas]
        assert posicoes == sorted(set(posicoes))
        for pos, pagina in marcas:
            assert 0 <= pos < len(a["texto"])
            assert not a["texto"][pos].isspace()
            assert pagina in a["paginas"]
        assert "=== página" not in a["texto"]


# ======================= PARTE 2: divisão =======================

CAPUT = (
    "Art. 2º Para efeito destas Normas,\n"
    "serão adotadas as seguintes definições:"
)
ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def _enchimento(tamanho):
    return ("texto " * 1000)[:tamanho].strip()


def _inciso(romano, tamanho=300, recuo=""):
    return f"{recuo}{romano} - MARCA{romano}: {_enchimento(tamanho)};"


def _lista(qtd=12, tamanho=300):
    return CAPUT + "\n" + "\n".join(_inciso(r, tamanho) for r in ROMANOS[:qtd])


def _artigo(texto, marcas=None, paginas=None):
    art = {
        "artigo": "2",
        "texto": texto,
        "paginas": paginas or [1, 2, 3, 4],
        "alteracoes": [],
        "capitulo": "",
        "secao": "",
    }
    if marcas is not None:
        art["marcas_pagina"] = marcas
    return art


def _marcas_nos_incisos(texto, quebras):
    marcas = [[0, 1]]
    for romano, pagina in quebras.items():
        marcas.append([texto.index(f"{romano} - MARCA{romano}:"), pagina])
    return sorted(marcas)


def _pagina_do_inciso(romano, quebras):
    pagina = 1
    for r in ROMANOS:
        if r in quebras:
            pagina = quebras[r]
        if r == romano:
            return pagina


@pytest.mark.parametrize(
    "quebras", [{"V": 2, "IX": 3}, {"II": 2, "V": 3, "VI": 4}]
)
def test_cada_trecho_tem_as_paginas_dos_incisos_que_contem(quebras):
    texto = _lista()
    res = dividir_artigo(_artigo(texto, _marcas_nos_incisos(texto, quebras)))
    assert len(res) > 1
    for r in res:
        contidos = [rom for rom in ROMANOS if f"MARCA{rom}:" in r["texto"]]
        esperado = sorted({_pagina_do_inciso(rom, quebras) for rom in contidos})
        assert r["paginas"] == esperado


def test_a_pagina_do_caput_nao_vaza_para_os_trechos():
    texto = _lista()
    marcas = [[0, 1], [texto.index("I - MARCAI:"), 3]]
    res = dividir_artigo(_artigo(texto, marcas))
    assert len(res) > 1
    for r in res:
        assert r["paginas"] == [3]


def test_inciso_com_recuo_logo_depois_da_quebra_nao_herda_a_pagina_anterior():
    incisos = [_inciso(r, 200, recuo="  ") for r in ROMANOS[:8]]
    texto = CAPUT + "\n" + "\n".join(incisos)
    assert len(texto) > 1500
    marcas = [[0, 1], [texto.index("V - MARCAV:"), 2]]
    res = dividir_artigo(_artigo(texto, marcas), limite_grupo=100)
    assert len(res) == 8
    por_romano = {
        rom: r for rom in ROMANOS[:8] for r in res if f"MARCA{rom}:" in r["texto"]
    }
    assert por_romano["IV"]["paginas"] == [1]
    assert por_romano["V"]["paginas"] == [2]


def test_paragrafo_tem_a_pagina_onde_ele_esta():
    texto = "\n".join([
        CAPUT,
        _inciso("I", 450),
        _inciso("II", 450),
        "§ 1º PARAG1: " + _enchimento(600) + ".",
    ])
    assert len(texto) > 1500
    marcas = [[0, 1], [texto.index("§ 1º"), 2]]
    res = dividir_artigo(_artigo(texto, marcas))
    p = [r for r in res if "PARAG1:" in r["texto"]]
    assert len(p) == 1 and p[0]["paginas"] == [2]
    for r in res:
        if "MARCAI:" in r["texto"] or "MARCAII:" in r["texto"]:
            assert r["paginas"] == [1]


def test_artigo_inteiro_mantem_as_paginas_do_artigo():
    texto = "Art. 5º Texto curto.\n§ 1º Outro texto curto."
    art = _artigo(texto, [[0, 1], [21, 2]], paginas=[1, 2])
    res = dividir_artigo(art)
    assert len(res) == 1
    assert res[0]["paginas"] == [1, 2]


def test_sem_marcas_todos_os_trechos_herdam_as_paginas_do_artigo():
    res = dividir_artigo(_artigo(_lista(), marcas=None, paginas=[4, 5]))
    assert len(res) > 1
    assert all(r["paginas"] == [4, 5] for r in res)


def test_trechos_nao_carregam_marcas_e_a_entrada_nao_muda():
    texto = _lista()
    art = _artigo(texto, _marcas_nos_incisos(texto, {"V": 2}))
    original = copy.deepcopy(art)
    res = dividir_artigo(art)
    assert art == original
    assert all("marcas_pagina" not in r for r in res)
