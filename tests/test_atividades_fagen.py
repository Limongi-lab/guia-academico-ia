"""Extração da tabela de atividades complementares da FAGEN (Gestão da Informação).

Contrato:
    extrair_atividades(html: str) -> list[dict]
em guia.ingestao.atividades_fagen. Cada dict tem:
    codigo (str, ex. "ATCO0369"), atividade (str), limite_horas (int), comprovacao (str)
"""
import pytest

from guia.ingestao.atividades_fagen import extrair_atividades

CABECALHO = (
    "<thead><tr><th>Código</th><th>Nome da Atividade</th>"
    "<th>Limite por Atividade</th><th>Comprovação</th></tr></thead>"
)

PAGINA = f"""
<html><body>
<h1>Atividades Complementares</h1>
<table>
{CABECALHO}
<tbody>
<tr><td>ATCO0369</td><td>Organização de evento acadêmico na UFU</td><td>30 horas</td><td>Certificado ou declaração</td></tr>
<tr><td>ATCO1052</td><td>Visita técnica em Uberlândia</td><td>5 horas</td><td>Certificado ou declaração</td></tr>
<tr><td>ATCO0782</td><td>Participante de Estágio Não-Obrigatório</td><td>50 horas</td><td>Contrato de trabalho ou Carteira</td></tr>
</tbody>
</table>
<table>
<thead><tr><th>Anexo</th><th>Tamanho</th></tr></thead>
<tbody><tr><td><a href="x.pdf">atividadescomplementares_revisado.pdf</a></td><td>163.08 KB</td></tr></tbody>
</table>
</body></html>
"""


def _html(*linhas, cabecalho=CABECALHO):
    return f"<html><body><table>{cabecalho}<tbody>{''.join(linhas)}</tbody></table></body></html>"


def _linha(codigo, atividade, limite, comprovacao="Certificado ou declaração"):
    return (
        f"<tr><td>{codigo}</td><td>{atividade}</td>"
        f"<td>{limite}</td><td>{comprovacao}</td></tr>"
    )


def test_extrai_as_linhas_na_ordem_da_pagina():
    assert extrair_atividades(PAGINA) == [
        {
            "codigo": "ATCO0369",
            "atividade": "Organização de evento acadêmico na UFU",
            "limite_horas": 30,
            "comprovacao": "Certificado ou declaração",
        },
        {
            "codigo": "ATCO1052",
            "atividade": "Visita técnica em Uberlândia",
            "limite_horas": 5,
            "comprovacao": "Certificado ou declaração",
        },
        {
            "codigo": "ATCO0782",
            "atividade": "Participante de Estágio Não-Obrigatório",
            "limite_horas": 50,
            "comprovacao": "Contrato de trabalho ou Carteira",
        },
    ]


def test_ignora_outras_tabelas_da_pagina():
    codigos = [a["codigo"] for a in extrair_atividades(PAGINA)]
    assert len(codigos) == 3
    assert all(c.startswith("ATCO") for c in codigos)


def test_cabecalho_em_td_em_vez_de_th_tambem_funciona():
    cab = (
        "<tr><td><strong>Código</strong></td><td>Nome da Atividade</td>"
        "<td>Limite por Atividade</td><td>Comprovação</td></tr>"
    )
    res = extrair_atividades(_html(_linha("ATCO0072", "Atividade de monitoria", "50 horas"), cabecalho=cab))
    assert [a["codigo"] for a in res] == ["ATCO0072"]


def test_normaliza_espacos_nbsp_quebras_e_tags_internas():
    linha = (
        "<tr><td>ATCO0537</td>"
        "<td>Participação em evento\n   acadêmico&nbsp;na UFU <br>com apresentação</td>"
        "<td>&nbsp;20  horas </td>"
        "<td><p>Comprovante de</p><p>apresentação</p></td></tr>"
    )
    (a,) = extrair_atividades(_html(linha))
    assert a["atividade"] == "Participação em evento acadêmico na UFU com apresentação"
    assert a["limite_horas"] == 20
    assert a["comprovacao"] == "Comprovante de apresentação"


@pytest.mark.parametrize(
    "texto,esperado",
    [("5 horas", 5), ("50 horas", 50), ("1 hora", 1), ("  40   horas ", 40)],
)
def test_limite_em_horas_vira_inteiro(texto, esperado):
    (a,) = extrair_atividades(_html(_linha("ATCO0001", "Teste", texto)))
    assert a["limite_horas"] == esperado
    assert isinstance(a["limite_horas"], int)


def test_codigo_e_normalizado():
    (a,) = extrair_atividades(_html(_linha("  atco0072 ", "Monitoria", "50 horas")))
    assert a["codigo"] == "ATCO0072"


def test_linhas_sem_codigo_valido_sao_ignoradas():
    res = extrair_atividades(_html(
        _linha("ATCO0369", "Evento", "30 horas"),
        "<tr><td></td><td></td><td></td><td></td></tr>",
        _linha("Total", "Soma", "100 horas"),
        "<tr><td colspan='4'>Observação sobre o quadro</td></tr>",
        _linha("ATCO1052", "Visita", "5 horas"),
    ))
    assert [a["codigo"] for a in res] == ["ATCO0369", "ATCO1052"]


def test_limite_ilegivel_com_codigo_valido_falha_com_o_codigo_na_mensagem():
    with pytest.raises(ValueError, match="ATCO0999"):
        extrair_atividades(_html(_linha("ATCO0999", "Atividade", "a critério do colegiado")))


def test_sem_tabela_de_atividades_devolve_lista_vazia():
    assert extrair_atividades("<html><body><p>Sem tabela</p></body></html>") == []


def test_codigos_repetidos_nao_somem_em_silencio():
    res = extrair_atividades(_html(
        _linha("ATCO0369", "Evento A", "30 horas"),
        _linha("ATCO0369", "Evento B", "20 horas"),
    ))
    assert [a["limite_horas"] for a in res] == [30, 20]
