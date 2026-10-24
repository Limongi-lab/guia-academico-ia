import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
caminho = Path("avaliacao/perguntas.jsonl")
ids, tipos = set(), Counter()
for n, linha in enumerate(caminho.read_text(encoding="utf-8").splitlines(), 1):
    if not linha.strip():
        print(f"linha {n}: linha em branco (remova)")
        continue
    try:
        item = json.loads(linha)
    except json.JSONDecodeError as erro:
        print(f"linha {n}: JSON inválido ({erro})")
        continue
    faltando = {"id", "pergunta", "tipo"} - set(item)
    if faltando:
        print(f"linha {n}: faltam as chaves {sorted(faltando)}")
    if item.get("id") in ids:
        print(f"linha {n}: id repetido {item.get('id')}")
    ids.add(item.get("id"))
    tipos[item.get("tipo")] += 1
    if item.get("tipo") != "recusa" and not (item.get("resposta_esperada") and item.get("fonte_esperada")):
        print(f"linha {n}: falta resposta_esperada ou fonte_esperada")
print(f"{len(ids)} perguntas | por tipo: {dict(tipos)}")