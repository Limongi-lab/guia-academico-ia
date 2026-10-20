"""Alíneas no nível do caput (sem inciso acima): ex. Arts. 10 e 57 do Regimento UNIUBE.

Usa a mesma função de tests/test_artigos_longos.py:
    dividir_artigo(artigo, limite_artigo=1500, limite_grupo=800)
"""
from guia.ingestao.divisao import dividir_artigo

CAPUT = "Art. 10.  São atribuições do Diretor de Instituto:"
LETRAS = list("abcdefghijklmno")


def _enchimento(tamanho):
    return ("texto " * 1000)[:tamanho].strip()


def _alinea(letra, tamanho=150):
    return f"{letra}) ALI_{letra}: {_enchimento(tamanho)};"


def _artigo(texto):
    return {
        "artigo": "10",
        "texto": texto,
        "paginas": [5],
        "alteracoes": [],
        "capitulo": "Capítulo V DA ORGANIZAÇÃO E FUNCIONAMENTO DOS INSTITUTOS",
        "secao": "",
    }


def _lista_de_alineas(qtd=15, tamanho=150, separador="\n\n\n"):
    return CAPUT + separador + separador.join(_alinea(l, tamanho) for l in LETRAS[:qtd])


def test_alineas_sob_o_caput_dividem_o_artigo_e_repetem_o_caput():
    texto = _lista_de_alineas()
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto))
    assert len(res) > 1
    for r in res:
        assert r["texto"].startswith(CAPUT)


def test_nenhuma_alinea_se_perde_nem_se_duplica_e_a_ordem_se_mantem():
    res = dividir_artigo(_artigo(_lista_de_alineas()))
    for letra in LETRAS:
        assert sum(f"ALI_{letra}:" in r["texto"] for r in res) == 1
    ordem = [
        i
        for r in res
        for i, letra in enumerate(LETRAS)
        if f"ALI_{letra}:" in r["texto"]
    ]
    assert ordem == list(range(len(LETRAS)))


def test_cada_alinea_e_reconhecida_mesmo_com_linhas_em_branco_entre_elas():
    # com limite pequeno cada alínea vira um trecho; se alguma não for
    # reconhecida, fica colada na anterior e o total fica abaixo de 15
    res = dividir_artigo(_artigo(_lista_de_alineas()), limite_grupo=100)
    assert len(res) == 15


def test_alineas_sob_o_caput_funcionam_sem_linhas_em_branco_e_com_recuo():
    linhas = [CAPUT] + [("  " if i % 2 else "\u00a0") + _alinea(l) for i, l in enumerate(LETRAS)]
    texto = "\n".join(linhas)
    res = dividir_artigo(_artigo(texto), limite_grupo=100)
    assert len(res) == 15


def test_paragrafo_depois_de_alineas_fica_em_trecho_proprio():
    texto = "\n".join([
        CAPUT,
        *[_alinea(l, 200) for l in LETRAS[:8]],
        "§ 1º PARAG1: " + _enchimento(300) + ".",
    ])
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto))
    p = [r for r in res if "PARAG1:" in r["texto"]]
    assert len(p) == 1
    assert p[0]["texto"].startswith(CAPUT)
    assert "ALI_a:" not in p[0]["texto"]
    assert "ALI_h:" not in p[0]["texto"]


def test_alineas_dentro_de_paragrafo_ficam_no_paragrafo():
    texto = "\n".join([
        "Art. 10.  Regra geral do artigo.",
        f"I - MARCAI: {_enchimento(500)};",
        f"II - MARCAII: {_enchimento(500)};",
        "§ 1º Os critérios são:",
        f"a) PALI_a: {_enchimento(250)};",
        f"b) PALI_b: {_enchimento(250)}.",
    ])
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto))
    p = [r for r in res if "PALI_a:" in r["texto"]]
    assert len(p) == 1
    assert "PALI_b:" in p[0]["texto"]
    assert "§ 1º" in p[0]["texto"]
    assert "MARCAI:" not in p[0]["texto"]
