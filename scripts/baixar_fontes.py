"""Baixa as fontes listadas em fontes.json para data/raw/ e gera um manifesto.

Uso:
    uv run python scripts/baixar_fontes.py            # baixa só o que falta
    uv run python scripts/baixar_fontes.py --forcar   # baixa tudo de novo
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_FONTES = RAIZ / "fontes.json"
DESTINO = RAIZ / "data" / "raw"
MANIFESTO = DESTINO / "manifest.json"
HEADERS = {
    "User-Agent": "guia-academico-ia/0.1 (projeto de portfolio; uso educacional)"
}


def caminho_destino(fonte: dict) -> Path:
    extensao = "pdf" if fonte["tipo"] == "pdf" else "html"
    pasta = DESTINO / fonte["instituicao"]
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / f"{fonte['id']}.{extensao}"


def conteudo_valido(fonte: dict, resposta: httpx.Response) -> str | None:
    """Retorna None se estiver ok, ou a descrição do problema."""
    if resposta.status_code != 200:
        return f"HTTP {resposta.status_code}"
    if fonte["tipo"] == "pdf" and not resposta.content.startswith(b"%PDF"):
        return "esperava um PDF, mas o conteúdo não começa com %PDF"
    tipo_resposta = resposta.headers.get("content-type", "")
    if fonte["tipo"] == "html" and "text/html" not in tipo_resposta:
        return f"esperava HTML, recebeu {tipo_resposta or 'tipo desconhecido'}"
    return None


def baixar(cliente: httpx.Client, fonte: dict, forcar: bool) -> dict:
    arquivo = caminho_destino(fonte)
    status = "ja_existia"

    if forcar or not arquivo.exists():
        try:
            resposta = cliente.get(fonte["url"])
        except httpx.HTTPError as erro:
            return {"id": fonte["id"], "status": "erro", "detalhe": str(erro)}

        problema = conteudo_valido(fonte, resposta)
        if problema:
            return {"id": fonte["id"], "status": "invalido", "detalhe": problema}

        arquivo.write_bytes(resposta.content)
        status = "baixado"

    dados = arquivo.read_bytes()
    return {
        "id": fonte["id"],
        "status": status,
        "arquivo": str(arquivo.relative_to(RAIZ)),
        "bytes": len(dados),
        "sha256": hashlib.sha256(dados).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Baixa as fontes do projeto.")
    parser.add_argument("--forcar", action="store_true", help="baixa de novo")
    args = parser.parse_args()

    fontes = json.loads(ARQUIVO_FONTES.read_text(encoding="utf-8"))
    transporte = httpx.HTTPTransport(retries=2)
    manifesto = []
    falhas = 0

    with httpx.Client(
        headers=HEADERS, timeout=30, follow_redirects=True, transport=transporte
    ) as cliente:
        for fonte in fontes:
            resultado = baixar(cliente, fonte, args.forcar)
            detalhe = resultado.get("detalhe", "")
            print(f"[{resultado['status']:>10}] {fonte['id']} {detalhe}")

            if resultado["status"] in ("erro", "invalido"):
                falhas += 1

            manifesto.append(
                {
                    **fonte,
                    **resultado,
                    "verificado_em": datetime.now(timezone.utc).isoformat(),
                }
            )

    DESTINO.mkdir(parents=True, exist_ok=True)
    MANIFESTO.write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n{len(fontes) - falhas}/{len(fontes)} fontes ok. Manifesto: {MANIFESTO}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())