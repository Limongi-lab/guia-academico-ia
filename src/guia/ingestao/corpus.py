"""Leitura e carga do corpus (fontes.json + trechos JSONL) no banco.

Funcoes publicas:
  ler_corpus(fontes, dir_trechos)  -> dict   (sem banco, sem embedder)
  carregar_corpus(conn, fontes, dir_trechos, embedder, modelo, lote=32) -> dict
"""
import json
from pathlib import Path

from guia.ingestao.carga import ingerir_documento


def ler_corpus(fontes: list[dict], dir_trechos) -> dict:
    """Le e valida o corpus sem tocar no banco.

    Parametros
    ----------
    fontes:
        Lista de dicts de fontes.json (id, instituicao, titulo, url, tipo,
        data_ref, prioridade).
    dir_trechos:
        Path ou str para o diretorio que contem os arquivos <id>.jsonl.

    Retorna
    -------
    {
      "documentos": [(fonte, trechos), ...],   # so fontes com >= 1 trecho
      "sem_trechos": [ids],                    # fonte sem arquivo ou arquivo vazio
      "sem_fonte":   [nomes],                  # .jsonl da pasta sem fonte correspondente
    }

    Levanta
    -------
    ValueError
        - Se uma linha de qualquer .jsonl nao for JSON valido (mensagem inclui
          o nome do arquivo e "linha N").
        - Se um trecho tiver doc_id diferente do id da fonte (mensagem inclui
          o nome do arquivo e o id do trecho).

    Nenhum dado e carregado antes da validacao completa de todos os arquivos.
    """
    dir_trechos = Path(dir_trechos)

    # Conjunto de ids de fontes para detectar arquivos orfaos
    ids_fontes = {f["id"] for f in fontes}

    # Arquivos .jsonl presentes na pasta
    arquivos_presentes = {p.stem for p in dir_trechos.glob("*.jsonl")}

    documentos: list[tuple[dict, list[dict]]] = []
    sem_trechos: list[str] = []

    # Valida e le todos os arquivos ANTES de montar o resultado
    trechos_por_id: dict[str, list[dict]] = {}
    for fonte in fontes:
        doc_id = fonte["id"]
        arquivo = dir_trechos / f"{doc_id}.jsonl"

        if not arquivo.exists():
            sem_trechos.append(doc_id)
            continue

        trechos: list[dict] = []
        texto = arquivo.read_text(encoding="utf-8")
        for n_linha, linha in enumerate(texto.splitlines(), start=1):
            # Ignora linhas em branco ou com apenas espacos
            if not linha.strip():
                continue
            try:
                trecho = json.loads(linha)
            except json.JSONDecodeError as erro:
                raise ValueError(
                    f"{arquivo.name}, linha {n_linha}: JSON invalido ({erro})"
                ) from erro

            # Valida que o doc_id do trecho confere com a fonte
            if trecho.get("doc_id") != doc_id:
                raise ValueError(
                    f"{arquivo.name}: trecho com doc_id inesperado "
                    f"'{trecho.get('id')}' (esperado doc_id='{doc_id}')."
                )
            trechos.append(trecho)

        if not trechos:
            sem_trechos.append(doc_id)
        else:
            trechos_por_id[doc_id] = trechos

    # Monta lista de documentos na ordem original de fontes
    for fonte in fontes:
        doc_id = fonte["id"]
        if doc_id in trechos_por_id:
            documentos.append((fonte, trechos_por_id[doc_id]))

    # Arquivos orfaos: presentes na pasta mas sem fonte correspondente
    sem_fonte = sorted(arquivos_presentes - ids_fontes)

    return {
        "documentos": documentos,
        "sem_trechos": sem_trechos,
        "sem_fonte": sem_fonte,
    }


def carregar_corpus(
    conn,
    fontes: list[dict],
    dir_trechos,
    embedder,
    modelo: str,
    lote: int = 32,
) -> dict:
    """Valida e carrega o corpus completo no banco.

    Chama ler_corpus (valida TUDO antes de gravar qualquer coisa) e depois
    ingerir_documento para cada documento com trechos.

    Parametros
    ----------
    conn:
        Conexao psycopg aberta com autocommit=True.
    fontes:
        Lista de dicts de fontes.json.
    dir_trechos:
        Path ou str para o diretorio com os arquivos <id>.jsonl.
    embedder:
        Callable(textos: list[str]) -> list[list[float]].
    modelo:
        Nome do modelo (gravado em trechos.embedding_modelo).
    lote:
        Tamanho do batch de embeddings.

    Retorna
    -------
    {
      "por_documento": {id: stats de ingerir_documento},
      "totais": {inseridos, atualizados, inalterados, removidos, embeddings_gerados},
      "sem_trechos": [...],
      "sem_fonte": [...],
    }

    Arquivo vazio NAO apaga os trechos ja gravados do documento (vai para sem_trechos).
    """
    # Valida todo o corpus antes de qualquer gravacao
    corpus = ler_corpus(fontes, dir_trechos)

    chaves_totais = ["inseridos", "atualizados", "inalterados", "removidos", "embeddings_gerados"]
    totais: dict[str, int] = {k: 0 for k in chaves_totais}
    por_documento: dict[str, dict] = {}

    for fonte, trechos in corpus["documentos"]:
        stats = ingerir_documento(conn, fonte, trechos, embedder, modelo, lote)
        por_documento[fonte["id"]] = stats
        for chave in chaves_totais:
            totais[chave] += stats.get(chave, 0)

    return {
        "por_documento": por_documento,
        "totais": totais,
        "sem_trechos": corpus["sem_trechos"],
        "sem_fonte": corpus["sem_fonte"],
    }
