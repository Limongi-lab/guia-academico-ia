"""Embedder: adaptador de modelo (tipo SentenceTransformer) para o contrato do projeto.

Contrato (guia.embeddings):
  NOME_MODELO = "bge-m3"            (valor gravado em trechos.embedding_modelo)
  MODELO_HF = "BAAI/bge-m3"         (id do modelo no Hugging Face)
  criar_embedder(modelo, lote=16) -> embedder
      `modelo` é qualquer objeto com .encode(textos, batch_size=..., **kwargs) que devolve
      uma matriz (numpy ou lista de listas) com uma linha por texto.
      embedder(textos: list[str]) -> list[list[float]]
        - lista vazia -> [] sem chamar o modelo
        - cada vetor tem DIMENSAO (1024) floats do Python (não numpy) e norma L2 = 1
        - passa batch_size=lote ao modelo
        - ValueError se o modelo devolver número errado de vetores, dimensão diferente
          de 1024 ou um vetor nulo
  carregar_bge_m3(dispositivo="cpu", max_seq_length=1024) -> modelo
      importa sentence_transformers só quando chamada (importar guia.embeddings não pode
      puxar torch). Não é testada aqui: o sandbox não acessa o Hugging Face.
"""
import hashlib
import math
import subprocess
import sys

import numpy as np
import pytest

from guia.embeddings import MODELO_HF, NOME_MODELO, criar_embedder
from guia.ingestao.carga import DIMENSAO


class ModeloFalso:
    """Imita SentenceTransformer.encode: devolve vetores NÃO normalizados."""

    def __init__(self, dim=DIMENSAO, escala=3.0, formato="numpy", linhas=None, nulo=False):
        self.dim = dim
        self.escala = escala
        self.formato = formato
        self.linhas = linhas  # força número de linhas diferente do pedido
        self.nulo = nulo
        self.chamadas = []

    def encode(self, textos, **kwargs):
        self.chamadas.append((list(textos), kwargs))
        n = len(textos) if self.linhas is None else self.linhas
        matriz = []
        for i in range(n):
            if self.nulo:
                matriz.append([0.0] * self.dim)
                continue
            semente = hashlib.md5(f"{i}-{textos[i % len(textos)]}".encode()).digest()
            linha = [((semente[j % 16] + j) % 7 + 1) * self.escala for j in range(self.dim)]
            matriz.append(linha)
        if self.formato == "numpy":
            return np.array(matriz, dtype=np.float32)
        return matriz


def test_constantes_do_modelo():
    assert NOME_MODELO == "bge-m3"
    assert MODELO_HF == "BAAI/bge-m3"


def test_devolve_lista_de_listas_de_floats_do_python_com_dimensao_certa():
    emb = criar_embedder(ModeloFalso())
    saida = emb(["um texto", "outro texto", "terceiro"])
    assert isinstance(saida, list) and len(saida) == 3
    for vetor in saida:
        assert isinstance(vetor, list) and len(vetor) == DIMENSAO
        assert all(type(x) is float for x in vetor)


@pytest.mark.parametrize("formato", ["numpy", "lista"])
def test_normaliza_para_norma_um_mesmo_se_o_modelo_nao_normaliza(formato):
    emb = criar_embedder(ModeloFalso(escala=7.5, formato=formato))
    for vetor in emb(["a", "b"]):
        assert math.sqrt(sum(x * x for x in vetor)) == pytest.approx(1.0, abs=1e-6)


def test_preserva_a_ordem_dos_textos():
    modelo = ModeloFalso()
    emb = criar_embedder(modelo)
    juntos = emb(["alfa", "beta"])
    sozinho = emb(["alfa"])[0]
    # o falso gera a linha 0 a partir do texto 0: a primeira linha de "juntos" bate com "sozinho"
    assert juntos[0] == pytest.approx(sozinho)
    assert juntos[0] != pytest.approx(juntos[1])


def test_lista_vazia_devolve_vazio_sem_chamar_o_modelo():
    modelo = ModeloFalso()
    assert criar_embedder(modelo)([]) == []
    assert modelo.chamadas == []


def test_passa_o_tamanho_de_lote_ao_modelo():
    modelo = ModeloFalso()
    criar_embedder(modelo, lote=4)(["a", "b", "c"])
    assert len(modelo.chamadas) == 1
    textos, kwargs = modelo.chamadas[0]
    assert textos == ["a", "b", "c"]
    assert kwargs["batch_size"] == 4


def test_lote_padrao_e_16():
    modelo = ModeloFalso()
    criar_embedder(modelo)(["a"])
    assert modelo.chamadas[0][1]["batch_size"] == 16


def test_dimensao_errada_levanta_valueerror():
    with pytest.raises(ValueError, match="1024"):
        criar_embedder(ModeloFalso(dim=8))(["a"])


def test_numero_de_vetores_errado_levanta_valueerror():
    with pytest.raises(ValueError):
        criar_embedder(ModeloFalso(linhas=1))(["a", "b", "c"])


def test_vetor_nulo_levanta_valueerror():
    with pytest.raises(ValueError, match="nulo"):
        criar_embedder(ModeloFalso(nulo=True))(["a"])


def test_importar_guia_embeddings_nao_importa_sentence_transformers():
    codigo = (
        "import sys, guia.embeddings; "
        "sys.exit(1 if 'sentence_transformers' in sys.modules or 'torch' in sys.modules else 0)"
    )
    resultado = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert resultado.returncode == 0, resultado.stderr
