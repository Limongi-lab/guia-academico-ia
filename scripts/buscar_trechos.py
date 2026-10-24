import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
doc_id, padrao = sys.argv[1], sys.argv[2]
arquivo = Path("data/processed/trechos") / f"{doc_id}.jsonl"
for linha in arquivo.read_text(encoding="utf-8").splitlines():
    r = json.loads(linha)
    if re.search(padrao, r["texto"], re.IGNORECASE):
        print(f"[{r['citacao']}]  ({r['id']})")
        print(r["texto"])
        print("-" * 60)