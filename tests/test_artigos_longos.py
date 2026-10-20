"""Testes da divisão de artigos longos em trechos (um artigo -> vários trechos).

Contrato:
    dividir_artigo(artigo, limite_artigo=1500, limite_grupo=800) -> list[dict]
em guia.ingestao.divisao.
"""
import copy

import pytest

from guia.ingestao.divisao import dividir_artigo

CAPUT = (
    "Art. 2º Para efeito da aplicação destas Normas,\n"
    "serão adotadas as seguintes definições:"
)
ROMANOS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def _enchimento(tamanho):
    return ("texto " * 1000)[:tamanho].strip()


def _inciso(romano, tamanho=300, sep="-"):
    return f"{romano} {sep} MARCA{romano}: {_enchimento(tamanho)};"


def _paragrafo(rotulo, marca, tamanho=600):
    return f"{rotulo} PARAG{marca}: {_enchimento(tamanho)}."


def _artigo(texto, numero="2"):
    return {
        "artigo": numero,
        "texto": texto,
        "paginas": [3, 4],
        "alteracoes": [],
        "capitulo": "CAPÍTULO I DAS DEFINIÇÕES",
        "secao": "",
    }


def _lista_de_definicoes(qtd=12, tamanho=300):
    incisos = [_inciso(r, tamanho) for r in ROMANOS[:qtd]]
    return CAPUT + "\n" + "\n".join(incisos)


# ---------- quando NÃO dividir ----------

@pytest.mark.parametrize("numero", ["5", 5])
def test_artigo_curto_fica_inteiro(numero):
    texto = "Art. 5º Texto curto.\n§ 1º Outro texto curto."
    res = dividir_artigo(_artigo(texto, numero))
    assert len(res) == 1
    assert res[0]["texto"] == texto
    assert res[0]["id"] == "art-5#1"
    assert res[0]["parte"] == 1
    assert res[0]["total_partes"] == 1


def test_artigo_com_exatamente_1500_caracteres_fica_inteiro():
    texto = _lista_de_definicoes(qtd=3, tamanho=100)
    texto += "x" * (1500 - len(texto))
    assert len(texto) == 1500
    assert len(dividir_artigo(_artigo(texto))) == 1


def test_artigo_com_1501_caracteres_e_dividido():
    texto = _lista_de_definicoes(qtd=3, tamanho=100)
    texto += "x" * (1501 - len(texto))
    assert len(texto) == 1501
    assert len(dividir_artigo(_artigo(texto))) > 1


def test_artigo_longo_sem_incisos_nem_paragrafos_nao_e_cortado():
    texto = "Art. 9º " + _enchimento(3000)
    res = dividir_artigo(_artigo(texto, "9"))
    assert len(res) == 1
    assert res[0]["texto"] == texto
    assert res[0]["id"] == "art-9#1"


# ---------- incisos ----------

def test_cada_trecho_repete_o_caput():
    res = dividir_artigo(_artigo(_lista_de_definicoes()))
    assert len(res) > 1
    for r in res:
        assert r["texto"].startswith(CAPUT)


def test_nenhum_inciso_se_perde_nem_se_duplica():
    res = dividir_artigo(_artigo(_lista_de_definicoes()))
    for romano in ROMANOS:
        assert sum(f"MARCA{romano}:" in r["texto"] for r in res) == 1


def test_ids_partes_e_ordem():
    res = dividir_artigo(_artigo(_lista_de_definicoes()))
    n = len(res)
    assert [r["id"] for r in res] == [f"art-2#{i}" for i in range(1, n + 1)]
    assert [r["parte"] for r in res] == list(range(1, n + 1))
    assert all(r["total_partes"] == n for r in res)
    posicoes = [
        i
        for r in res
        for i, romano in enumerate(ROMANOS)
        if f"MARCA{romano}:" in r["texto"]
    ]
    assert posicoes == list(range(12))


def test_agrupa_incisos_ate_o_limite_do_grupo():
    # cada inciso tem ~320 caracteres: cabem 2 por trecho (~640); 3 passariam de 800
    res = dividir_artigo(_artigo(_lista_de_definicoes(12, 300)))
    assert len(res) == 6
    for r in res:
        corpo = r["texto"][len(CAPUT):].strip()
        assert len(corpo) <= 800


def test_limites_sao_configuraveis():
    art = _artigo(_lista_de_definicoes(12, 300))
    um_por_trecho = dividir_artigo(art, limite_grupo=300)
    assert len(um_por_trecho) == 12
    inteiro = dividir_artigo(art, limite_artigo=100_000)
    assert len(inteiro) == 1
    assert inteiro[0]["texto"] == art["texto"]


def test_inciso_maior_que_o_limite_nao_e_cortado():
    grande = _inciso("II", 1400)
    texto = "\n".join([CAPUT, _inciso("I", 100), grande, _inciso("III", 100)])
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto))
    assert sum(grande in r["texto"] for r in res) == 1


def test_alineas_ficam_com_o_inciso_pai():
    blocos = []
    for r in ROMANOS[:6]:
        blocos.append(_inciso(r, 100))
        blocos.append(f"a) ALINEA_{r}_a: {_enchimento(120)};")
        blocos.append(f"b) ALINEA_{r}_b: {_enchimento(120)};")
    texto = CAPUT + "\n" + "\n".join(blocos)
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto), limite_grupo=100)
    assert len(res) == 6
    for r in ROMANOS[:6]:
        pedaco = [p for p in res if f"MARCA{r}:" in p["texto"]]
        assert len(pedaco) == 1
        assert f"ALINEA_{r}_a:" in pedaco[0]["texto"]
        assert f"ALINEA_{r}_b:" in pedaco[0]["texto"]


def test_reconhece_incisos_com_recuo_nbsp_e_travessao():
    prefixos = ["", "  ", "\u00a0", "\u00a0\u00a0 "]
    seps = ["-", "–"]
    incisos = [
        prefixos[i % 4] + _inciso(r, 200, seps[i % 2]) for i, r in enumerate(ROMANOS)
    ]
    texto = CAPUT + "\n" + "\n".join(incisos)
    assert len(texto) > 1500
    # com limite pequeno, cada inciso vira um trecho: se algum não for
    # reconhecido, ele fica colado no anterior e o total fica abaixo de 12
    res = dividir_artigo(_artigo(texto), limite_grupo=100)
    assert len(res) == 12
    for r in res:
        assert r["texto"].startswith(CAPUT)


# ---------- parágrafos ----------

def test_cada_paragrafo_vira_trecho_proprio_com_o_caput():
    texto = "\n".join([
        CAPUT,
        _inciso("I", 300),
        _inciso("II", 300),
        _paragrafo("§ 1º", "1"),
        _paragrafo("§ 2º", "2"),
    ])
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto))
    p1 = [r for r in res if "PARAG1:" in r["texto"]]
    p2 = [r for r in res if "PARAG2:" in r["texto"]]
    assert len(p1) == 1 and len(p2) == 1
    assert p1[0]["id"] != p2[0]["id"]
    for r in (p1[0], p2[0]):
        assert r["texto"].startswith(CAPUT)
        assert "MARCAI:" not in r["texto"]
        assert "MARCAII:" not in r["texto"]
    for r in res:
        if "MARCAI:" in r["texto"] or "MARCAII:" in r["texto"]:
            assert "PARAG" not in r["texto"]


def test_paragrafo_unico_vira_trecho_proprio():
    texto = "\n".join([
        CAPUT,
        _inciso("I", 500),
        _inciso("II", 500),
        _paragrafo("Parágrafo único.", "U", 450),
    ])
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto))
    pu = [r for r in res if "PARAGU:" in r["texto"]]
    assert len(pu) == 1
    assert pu[0]["texto"].startswith(CAPUT)
    assert "MARCAI:" not in pu[0]["texto"]
    assert "MARCAII:" not in pu[0]["texto"]


def test_incisos_de_um_paragrafo_ficam_no_proprio_paragrafo():
    texto = "\n".join([
        CAPUT,
        _inciso("I", 400),
        _inciso("II", 400),
        "§ 1º Nos casos de que trata o caput, aplica-se o seguinte:",
        f"I - SUBI: {_enchimento(300)};",
        f"II - SUBII: {_enchimento(300)};",
        _paragrafo("§ 2º", "2", 200),
    ])
    assert len(texto) > 1500
    res = dividir_artigo(_artigo(texto))
    sub = [r for r in res if "SUBI:" in r["texto"]]
    assert len(sub) == 1
    assert "SUBII:" in sub[0]["texto"]
    assert "§ 1º" in sub[0]["texto"]
    assert "MARCAI:" not in sub[0]["texto"]
    assert "PARAG2:" not in sub[0]["texto"]


# ---------- metadados ----------

def test_metadados_sao_preservados_e_entrada_nao_e_alterada():
    art = _artigo(_lista_de_definicoes())
    original = copy.deepcopy(art)
    res = dividir_artigo(art)
    assert art == original
    for r in res:
        for chave in ("artigo", "paginas", "alteracoes", "capitulo", "secao"):
            assert r[chave] == art[chave]
        assert {"id", "parte", "total_partes", "texto"} <= set(r)
