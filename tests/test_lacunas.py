import copy
import json
from pathlib import Path

import pytest

from guia.geracao import TOKEN_RECUSA, montar_prompt
from guia.ingestao.lacunas import PREFIXO_LACUNA, aplicar_lacunas

DOC = "doc-a"
MARCA = PREFIXO_LACUNA + " do PDF: formula em imagem]"
ANCORA_CRA = "A fórmula para cálculo do CRA é:"
ANCORA_MGA = "A fórmula para cálculo do MGA é:"


def _artigo(numero, texto):
    return {"artigo": numero, "texto": texto, "paginas": [32, 33], "alteracoes": ["120"],
            "capitulo": "CAPÍTULO I", "secao": "SEÇÃO II"}


def _artigos():
    return [
        _artigo("121", "Art. 121. Texto qualquer antes da formula."),
        _artigo("122", f"Art. 122. {ANCORA_CRA}\n\nonde:\nCHc: carga horária cursada.\n"),
        _artigo("123", f"Art. 123. {ANCORA_MGA}"),
        _artigo("124", "Art. 124. Texto qualquer depois da formula."),
    ]


def _lacuna(artigo, ancora, doc_id=DOC, marca=MARCA):
    return {"doc_id": doc_id, "artigo": artigo, "ancora": ancora, "marca": marca}


def _por_numero(artigos):
    return {a["artigo"]: a for a in artigos}


def test_marca_entra_logo_depois_da_ancora_e_antes_do_resto_do_artigo():
    r = _por_numero(aplicar_lacunas(_artigos(), [_lacuna("122", ANCORA_CRA)], DOC))
    texto = r["122"]["texto"]
    assert f"{ANCORA_CRA}\n{MARCA}" in texto
    assert texto.index(MARCA) < texto.index("onde:")
    assert texto.count(MARCA) == 1


def test_ancora_no_fim_do_texto_recebe_a_marca_no_fim():
    r = _por_numero(aplicar_lacunas(_artigos(), [_lacuna("123", ANCORA_MGA)], DOC))
    assert r["123"]["texto"] == f"Art. 123. {ANCORA_MGA}\n{MARCA}"


def test_artigos_sem_lacuna_ficam_identicos():
    original = _artigos()
    r = _por_numero(aplicar_lacunas(original, [_lacuna("122", ANCORA_CRA)], DOC))
    assert r["121"] == original[0] and r["123"] == original[2] and r["124"] == original[3]


def test_ordem_e_quantidade_de_artigos_sao_preservadas():
    r = aplicar_lacunas(_artigos(), [_lacuna("122", ANCORA_CRA), _lacuna("123", ANCORA_MGA)], DOC)
    assert [a["artigo"] for a in r] == ["121", "122", "123", "124"]


def test_demais_campos_do_artigo_sao_preservados():
    r = _por_numero(aplicar_lacunas(_artigos(), [_lacuna("122", ANCORA_CRA)], DOC))
    a = r["122"]
    assert a["paginas"] == [32, 33] and a["alteracoes"] == ["120"]
    assert a["capitulo"] == "CAPÍTULO I" and a["secao"] == "SEÇÃO II"


def test_entrada_nao_e_alterada():
    artigos = _artigos()
    copia = copy.deepcopy(artigos)
    lacunas = [_lacuna("122", ANCORA_CRA)]
    lacunas_copia = copy.deepcopy(lacunas)
    aplicar_lacunas(artigos, lacunas, DOC)
    assert artigos == copia and lacunas == lacunas_copia


def test_duas_lacunas_no_mesmo_artigo_sao_aplicadas():
    artigos = [_artigo("130", "Art. 130. Primeira: X1 e segunda: X2 fim.")]
    lacunas = [_lacuna("130", "Primeira: X1", marca="[conteúdo não extraído A]"),
               _lacuna("130", "segunda: X2", marca="[conteúdo não extraído B]")]
    texto = aplicar_lacunas(artigos, lacunas, DOC)[0]["texto"]
    assert "Primeira: X1\n[conteúdo não extraído A] e segunda: X2\n[conteúdo não extraído B] fim." in texto


def test_lacuna_de_outro_documento_e_ignorada_sem_erro():
    lacunas = [_lacuna("122", "frase que nao existe aqui", doc_id="doc-b")]
    assert aplicar_lacunas(_artigos(), lacunas, DOC) == _artigos()


def test_sem_lacunas_devolve_os_mesmos_artigos():
    assert aplicar_lacunas(_artigos(), [], DOC) == _artigos()


def test_ancora_ausente_levanta_valueerror_com_documento_e_artigo():
    with pytest.raises(ValueError, match="doc-a.*122"):
        aplicar_lacunas(_artigos(), [_lacuna("122", "texto que nao existe")], DOC)


def test_ancora_repetida_levanta_valueerror():
    artigos = [_artigo("140", "Art. 140. repete aqui e repete aqui.")]
    with pytest.raises(ValueError, match="140"):
        aplicar_lacunas(artigos, [_lacuna("140", "repete aqui")], DOC)


def test_artigo_inexistente_levanta_valueerror():
    with pytest.raises(ValueError, match="999"):
        aplicar_lacunas(_artigos(), [_lacuna("999", ANCORA_CRA)], DOC)


def test_arquivo_lacunas_json_do_repositorio_e_valido():
    caminho = Path(__file__).resolve().parent.parent / "lacunas.json"
    lacunas = json.loads(caminho.read_text(encoding="utf-8"))
    assert lacunas
    for item in lacunas:
        assert set(item) == {"doc_id", "artigo", "ancora", "marca"}
        assert all(isinstance(v, str) and v for v in item.values())
        assert item["marca"].startswith(PREFIXO_LACUNA)
    pares = {(i["doc_id"], i["artigo"]) for i in lacunas}
    assert ("ufu-normas-gerais-graduacao", "122") in pares
    assert ("ufu-normas-gerais-graduacao", "123") in pares


def test_prompt_manda_recusar_quando_ha_marca_de_lacuna():
    blocos = [{"indice": 1, "citacao": "Art. 122, p. 32", "texto": f"Art. 122. {ANCORA_CRA}\n{MARCA}"}]
    system, _ = montar_prompt("Qual a fórmula do CRA?", blocos)
    assert PREFIXO_LACUNA in system
    assert system.count(TOKEN_RECUSA) >= 2
