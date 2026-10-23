import copy
import hashlib
import re
from typing import Optional

_DATA_RE = re.compile(r'^\d{4}(-\d{2}(-\d{2})?)?$')


def _validar_data_ref(valor) -> Optional[str]:
    """Retorna o valor se bater com ^\d{4}(-\d{2}(-\d{2})?)?$; senao None."""
    if valor and isinstance(valor, str) and _DATA_RE.match(valor):
        return valor
    return None


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


# ---------------------------------------------------------------------------
# formatar_paginas
# ---------------------------------------------------------------------------

def formatar_paginas(paginas: list) -> str:
    """Formata lista de inteiros em string de paginas.

    Paginas sao deduplicadas e ordenadas; consecutivas viram faixa.
    """
    uniq = sorted(set(paginas))
    if not uniq:
        return ''
    grupos = []
    inicio = uniq[0]
    fim = uniq[0]
    for n in uniq[1:]:
        if n == fim + 1:
            fim = n
        else:
            grupos.append((inicio, fim))
            inicio = fim = n
    grupos.append((inicio, fim))
    partes = [str(a) if a == b else f'{a}-{b}' for a, b in grupos]
    return 'p. ' + ', '.join(partes)


# ---------------------------------------------------------------------------
# montar_trecho_artigo
# ---------------------------------------------------------------------------

def montar_trecho_artigo(parte_artigo: dict, doc: dict) -> dict:
    """Monta o registro unificado de um trecho de artigo.

    parte_artigo vem de dividir_artigo.
    doc e a entrada de fontes.json.
    """
    pa = parte_artigo
    artigo_str = str(pa['artigo'])
    num_artigo = int(artigo_str) if artigo_str.isdigit() else None
    ordinal = 'º' if num_artigo is not None and 1 <= num_artigo <= 9 else ''

    paginas_fmt = formatar_paginas(pa.get('paginas', []))
    citacao_partes = [f'Art. {artigo_str}{ordinal}']
    if paginas_fmt:
        citacao_partes.append(paginas_fmt)
    citacao = ', '.join(citacao_partes)

    local_id = pa['id']
    pai_id_local = local_id.rsplit('#', 1)[0]
    doc_id = doc['id']

    return {
        'id': f'{doc_id}/{local_id}',
        'doc_id': doc_id,
        'local_id': local_id,
        'tipo_doc': 'resolucao',
        'instituicao': doc['instituicao'],
        'titulo_doc': doc['titulo'],
        'url': doc['url'],
        'data_ref': _validar_data_ref(doc.get('data_ref')),
        'prioridade': doc['prioridade'],
        'paginas': list(pa.get('paginas', [])),
        'localizacao': {
            'capitulo': pa.get('capitulo', ''),
            'secao': pa.get('secao', ''),
            'artigo': artigo_str,
        },
        'citacao': citacao,
        'texto': pa['texto'],
        'pai_id': f'{doc_id}/{pai_id_local}',
        'parte': pa['parte'],
        'total_partes': pa['total_partes'],
        'hash_texto': _sha256(pa['texto']),
        'metadados': {'alteracoes': list(pa.get('alteracoes', []))},
    }


# ---------------------------------------------------------------------------
# montar_trecho_passo
# ---------------------------------------------------------------------------

def montar_trecho_passo(passo: dict, doc: dict) -> dict:
    """Monta o registro unificado de um trecho de passo a passo.

    passo vem de dividir_passos.
    doc e a entrada de fontes.json.
    """
    p = passo
    num = p['passo']
    ator = p.get('ator', '')
    paginas_fmt = formatar_paginas(p.get('paginas', []))

    ator_parte = f' ({ator})' if ator else ''
    citacao_partes = [f'Passo {num}{ator_parte}']
    if paginas_fmt:
        citacao_partes.append(paginas_fmt)
    citacao = ', '.join(citacao_partes)

    doc_id = doc['id']
    local_id = f'passo-{num}#1'

    return {
        'id': f'{doc_id}/{local_id}',
        'doc_id': doc_id,
        'local_id': local_id,
        'tipo_doc': 'procedimento',
        'instituicao': doc['instituicao'],
        'titulo_doc': doc['titulo'],
        'url': doc['url'],
        'data_ref': _validar_data_ref(doc.get('data_ref')),
        'prioridade': doc['prioridade'],
        'paginas': list(p.get('paginas', [])),
        'localizacao': {'passo': num, 'ator': ator},
        'citacao': citacao,
        'texto': p['texto'],
        'pai_id': doc_id,
        'parte': 1,
        'total_partes': 1,
        'hash_texto': _sha256(p['texto']),
        'metadados': {'titulo_no_documento': p.get('titulo_doc', '')},
    }


# ---------------------------------------------------------------------------
# _dividir_secao
# ---------------------------------------------------------------------------

def _dividir_secao(texto: str, limite: int) -> list:
    """Divide texto em grupos de blocos separados por linha em branco.

    Regras:
    - Separa em blocos pelo padrao \n\n+.
    - Agrupa guloso ate limite caracteres.
    - Nunca corta um bloco; bloco unico > limite fica inteiro.
    - Bloco terminado em ':' fica colado ao seguinte.
    """
    blocos = re.split(r'\n\n+', texto)

    grupos = []
    acum = []
    acum_len = 0

    def flush():
        if acum:
            grupos.append('\n\n'.join(acum))
            acum.clear()

    i = 0
    while i < len(blocos):
        bloco = blocos[i]
        if bloco.rstrip().endswith(':') and i + 1 < len(blocos):
            janela = [bloco]
            j = i + 1
            while j < len(blocos):
                janela.append(blocos[j])
                if not blocos[j].rstrip().endswith(':'):
                    break
                j += 1
            i = j + 1
            unidade = '\n\n'.join(janela)
        else:
            unidade = bloco
            i += 1

        tamanho = len(unidade)
        sep = len('\n\n') if acum else 0

        if acum and acum_len + sep + tamanho > limite:
            flush()
            acum_len = 0

        acum.append(unidade)
        acum_len += sep + tamanho

    flush()
    return grupos


# ---------------------------------------------------------------------------
# montar_trechos_pagina (helpers)
# ---------------------------------------------------------------------------

def _meta_pagina(pagina: dict) -> dict:
    return {
        k: list(pagina[k])
        for k in ('curso', 'publico_alvo', 'assunto')
        if k in pagina
    }


def _data_ref_pagina(pagina: dict, doc: dict) -> Optional[str]:
    atualizado = pagina.get('atualizado_em')
    if atualizado and _validar_data_ref(atualizado):
        return atualizado
    return _validar_data_ref(doc.get('data_ref'))


def _texto_contato(contato: dict) -> str:
    linhas = []
    if contato.get('setor'):
        linhas.append(f'Contato: {contato["setor"]}')
    if contato.get('email'):
        linhas.append(f'E-mail: {contato["email"]}')
    if contato.get('telefone'):
        tel = contato['telefone']
        ramal = contato.get('ramal')
        if ramal:
            tel = f'{tel} (ramal {ramal})'
        linhas.append(f'Telefone: {tel}')
    if contato.get('endereco'):
        linhas.append(f'Endereço: {contato["endereco"]}')
    if contato.get('horario'):
        linhas.append(f'Horário de atendimento: {contato["horario"]}')
    return '\n'.join(linhas)


def montar_trechos_pagina(pagina: dict, doc: dict, limite: int = 1500) -> list:
    """Monta lista de registros de trechos para uma pagina HTML.

    pagina vem de extrair_pagina_fagen.
    doc e a entrada de fontes.json.
    """
    doc_id = doc['id']
    data_ref = _data_ref_pagina(pagina, doc)
    meta = _meta_pagina(pagina)
    secoes = pagina.get('secoes', [])
    contato = pagina.get('contato')

    resultado = []

    for idx, secao in enumerate(secoes, start=1):
        titulo = secao.get('titulo', '')
        texto = secao.get('texto', '')
        if not texto or not texto.strip():
            continue

        citacao = titulo if titulo else 'Texto principal'
        grupos = _dividir_secao(texto, limite)
        total = len(grupos)
        pai_local = f'secao-{idx}'

        for parte, grupo_texto in enumerate(grupos, start=1):
            local_id = f'{pai_local}#{parte}'
            resultado.append({
                'id': f'{doc_id}/{local_id}',
                'doc_id': doc_id,
                'local_id': local_id,
                'tipo_doc': 'pagina',
                'instituicao': doc['instituicao'],
                'titulo_doc': doc['titulo'],
                'url': doc['url'],
                'data_ref': data_ref,
                'prioridade': doc['prioridade'],
                'paginas': [],
                'localizacao': {'tipo': 'secao', 'secao': titulo},
                'citacao': citacao,
                'texto': grupo_texto,
                'pai_id': f'{doc_id}/{pai_local}',
                'parte': parte,
                'total_partes': total,
                'hash_texto': _sha256(grupo_texto),
                'metadados': copy.deepcopy(meta),
            })

    if contato:
        texto_ct = _texto_contato(contato)
        local_id_ct = 'contato#1'
        resultado.append({
            'id': f'{doc_id}/{local_id_ct}',
            'doc_id': doc_id,
            'local_id': local_id_ct,
            'tipo_doc': 'pagina',
            'instituicao': doc['instituicao'],
            'titulo_doc': doc['titulo'],
            'url': doc['url'],
            'data_ref': data_ref,
            'prioridade': doc['prioridade'],
            'paginas': [],
            'localizacao': {'tipo': 'contato'},
            'citacao': 'Contato',
            'texto': texto_ct,
            'pai_id': f'{doc_id}/contato',
            'parte': 1,
            'total_partes': 1,
            'hash_texto': _sha256(texto_ct),
            'metadados': copy.deepcopy(meta),
        })

    return resultado
