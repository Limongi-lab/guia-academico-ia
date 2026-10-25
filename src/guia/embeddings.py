"""Adaptador de modelo de embeddings para o contrato do projeto.

Contrato público:
  NOME_MODELO  – valor gravado em trechos.embedding_modelo ("bge-m3")
  MODELO_HF    – identificador do modelo no Hugging Face ("BAAI/bge-m3")
  criar_embedder(modelo, lote=16) -> embedder
  carregar_bge_m3(dispositivo="cpu", max_seq_length=1024) -> modelo SentenceTransformer
"""
import math
from collections.abc import Callable

NOME_MODELO = "bge-m3"
MODELO_HF = "BAAI/bge-m3"

# Dimensão esperada dos vetores (deve coincidir com carga.DIMENSAO)
_DIMENSAO = 1024


def _norma_l2(vetor: list[float]) -> float:
    """Calcula a norma L2 de um vetor."""
    return math.sqrt(sum(x * x for x in vetor))


def criar_embedder(
    modelo,
    lote: int = 16,
) -> Callable[[list[str]], list[list[float]]]:
    """Envolve *modelo* num callable com o contrato do projeto.

    Parâmetros
    ----------
    modelo:
        Qualquer objeto com .encode(textos, batch_size=..., **kwargs) que
        devolva uma matriz (numpy ou lista de listas) com uma linha por texto.
    lote:
        Tamanho do batch repassado ao modelo via batch_size=.

    Retorna
    -------
    embedder(textos: list[str]) -> list[list[float]]
        - Lista vazia -> [] sem chamar o modelo.
        - Cada vetor tem _DIMENSAO floats Python puros, norma L2 = 1.
        - ValueError se o modelo devolver numero errado de vetores,
          dimensao diferente de _DIMENSAO, ou um vetor nulo.
    """

    def embedder(textos: list[str]) -> list[list[float]]:
        # Lista vazia: devolve imediatamente, sem acionar o modelo
        if not textos:
            return []

        # Obtem a matriz do modelo (pode ser numpy ou lista de listas)
        saida_modelo = modelo.encode(textos, batch_size=lote, show_progress_bar=False)

        # Converte para lista de listas de floats Python puros
        try:
            # numpy array: converte linha a linha
            matriz: list[list[float]] = [
                [float(x) for x in linha] for linha in saida_modelo
            ]
        except TypeError:
            # ja eh iteravel de iteraveis
            matriz = [[float(x) for x in linha] for linha in saida_modelo]

        # Valida numero de vetores devolvidos
        if len(matriz) != len(textos):
            raise ValueError(
                f"O modelo devolveu {len(matriz)} vetor(es) para {len(textos)} texto(s)."
            )

        # Valida dimensao e normaliza cada vetor
        resultado: list[list[float]] = []
        for idx, vetor in enumerate(matriz):
            if len(vetor) != _DIMENSAO:
                raise ValueError(
                    f"Vetor {idx} tem dimensao {len(vetor)}, esperado {_DIMENSAO}."
                )
            norma = _norma_l2(vetor)
            if norma == 0.0:
                raise ValueError(
                    f"Vetor nulo recebido do modelo (indice {idx}): "
                    "nao e possivel normalizar."
                )
            resultado.append([x / norma for x in vetor])

        return resultado

    return embedder


def carregar_bge_m3(dispositivo: str = "cpu", max_seq_length: int = 1024):
    """Carrega o modelo BGE-M3 via sentence_transformers.

    A importacao de sentence_transformers (e portanto de torch) ocorre
    somente dentro desta funcao, de modo que ``import guia.embeddings`` nao
    arrasta torch para o processo.

    Parametros
    ----------
    dispositivo:
        Dispositivo PyTorch a usar ("cpu", "cuda", "mps", ...).
    max_seq_length:
        Comprimento maximo de sequencia em tokens.

    Retorna
    -------
    Instancia de SentenceTransformer pronta para uso em criar_embedder().
    """
    # Importacao local: nao pode ficar no topo do modulo (puxaria torch)
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(MODELO_HF, device=dispositivo)
    modelo.max_seq_length = max_seq_length
    return modelo
