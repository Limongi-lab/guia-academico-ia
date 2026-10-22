"""Divisão de documentos de procedimento ("passo a passo") em passos.

Contrato público:
    dividir_passos(texto: str) -> list[dict]

Cada dict contém:
    passo     (int)       – número sequencial (1, 2, 3, …)
    ator      (str)       – conteúdo dos parênteses, espaços normalizados
    texto     (str)       – texto completo do passo (primeira linha + continuação),
                            espaços normalizados por linha, quebras de linha preservadas
    paginas   (list[int]) – páginas do documento em que o passo aparece
    titulo_doc (str)      – linhas antes do passo 1, unidas com " - "

Regras de parsing:
- Um novo passo começa em uma linha cujo texto normalizado bate com
  ^(\\d{1,2})º\\s*\\(([^)]*)\\) E cujo número é exatamente o esperado
  (próximo da sequência: começa em 1 e aumenta de 1).
- Qualquer linha com esse formato mas fora de sequência é texto comum.
- Marcadores "=== página N ===" são descartados do texto; o número N é
  registrado e associado à próxima linha de conteúdo.
- Linhas vazias (após normalização) são descartadas.
- Espaços e NBSP (\u00a0) são normalizados para espaço simples em cada linha.
- Se não houver passo 1, retorna lista vazia.
"""

import re

_PASSO_RE = re.compile(r"^(\d{1,2})º\s*\(([^)]*)\)")
_PAGINA_RE = re.compile(r"^===\s*página\s+(\d+)\s*===", re.IGNORECASE)


def _norm(linha: str) -> str:
    """Normaliza NBSP e espaços múltiplos para espaço simples; strip."""
    return re.sub(r"[\u00a0\s]+", " ", linha).strip()


def dividir_passos(texto: str) -> list[dict]:
    """Divide um texto de passo a passo em lista de dicts por passo.

    Args:
        texto: Conteúdo bruto do .txt, com marcadores "=== página N ===".

    Returns:
        Lista de dicts (passo, ator, texto, paginas, titulo_doc) em ordem.
        Lista vazia se não encontrar passo 1.
    """
    linhas_brutas = texto.splitlines()

    # --- pré-processamento: normaliza e associa página pendente ---
    # Produz lista de (linha_normalizada, pagina_atual | None)
    # A página associada a uma linha é a página "corrente" no momento
    # em que ela aparece (marcadores atualizam a página ANTES da próxima linha).
    linhas: list[tuple[str, int | None]] = []  # (texto, pagina)
    pagina_corrente: int | None = None
    pagina_pendente: int | None = None  # página do próximo marcador ainda não consumida

    for linha_bruta in linhas_brutas:
        norm = _norm(linha_bruta)

        # Marcador de página → apenas atualiza página pendente, não vira linha
        m_pag = _PAGINA_RE.match(norm)
        if m_pag:
            pagina_pendente = int(m_pag.group(1))
            continue

        # Linha vazia → descarta
        if not norm:
            continue

        # Linha de conteúdo: consome a página pendente (se houver)
        if pagina_pendente is not None:
            pagina_corrente = pagina_pendente
            pagina_pendente = None

        linhas.append((norm, pagina_corrente))

    # --- separação em título + passos ---
    titulo_linhas: list[str] = []
    passos: list[dict] = []
    proximo_passo = 1
    passo_atual: dict | None = None

    for norm, pagina in linhas:
        m = _PASSO_RE.match(norm)
        if m and int(m.group(1)) == proximo_passo:
            # Fecha o passo anterior
            if passo_atual is not None:
                passos.append(passo_atual)

            ator = _norm(m.group(2))
            # Reconstrói o texto do cabeçalho do passo com espaços normalizados
            # (remove espaços extras antes do ')' que fecha o ator)
            texto_passo = re.sub(r"\s+\)", ")", norm)
            passo_atual = {
                "passo": proximo_passo,
                "ator": ator,
                "texto": texto_passo,
                "paginas": [pagina] if pagina is not None else [],
                "titulo_doc": "",  # preenchido depois
            }
            proximo_passo += 1
        else:
            if passo_atual is None:
                # Ainda estamos no cabeçalho / título
                titulo_linhas.append(norm)
            else:
                # Continuação do passo atual
                passo_atual["texto"] += "\n" + norm
                if pagina is not None and pagina not in passo_atual["paginas"]:
                    passo_atual["paginas"].append(pagina)

    # Fecha o último passo
    if passo_atual is not None:
        passos.append(passo_atual)

    # Se não encontrou o passo 1, retorna vazio
    if not passos:
        return []

    titulo_doc = " - ".join(titulo_linhas)
    for p in passos:
        p["titulo_doc"] = titulo_doc

    return passos
