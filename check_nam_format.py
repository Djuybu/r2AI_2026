import os, sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

for d in se._doc_mapping[:10]:
    print(f"Doc: Ma={d.get('Ma_Doanh_Nghiep')}, Nam={repr(d.get('Nam_Tai_Chinh'))}, Type={type(d.get('Nam_Tai_Chinh'))}")
