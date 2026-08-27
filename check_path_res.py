import os, sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

print(f"Total docs in _doc_mapping: {len(se._doc_mapping)}")

acb_docs = [d for d in se._doc_mapping if d.get("Ma_Doanh_Nghiep") == "ACB" and str(d.get("Nam_Tai_Chinh")) == "2022"]
print(f"Total ACB 2022 docs in mapping: {len(acb_docs)}")

resolved_count = 0
unresolved = []
for d in acb_docs:
    p = se._resolve_local_csv_path(d.get("csv_path", ""))
    if p and p.exists():
        resolved_count += 1
    else:
        unresolved.append(d.get("csv_path"))

print(f"Resolved paths: {resolved_count}/{len(acb_docs)}")
if unresolved:
    print(f"First 5 unresolved: {unresolved[:5]}")

t34_docs = [d for d in acb_docs if "table_34" in d.get("csv_path", "")]
print(f"Table 34 docs for ACB 2022: {len(t34_docs)}")
for d in t34_docs:
    p = se._resolve_local_csv_path(d.get("csv_path", ""))
    print(f"  raw={d.get('csv_path')} -> resolved={p} (exists={p.exists() if p else False})")
