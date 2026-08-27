import time, sys
from pathlib import Path

t0 = time.time()
print("1. Testing company map...", flush=True)
import rag_module.search_engine as se
cmap = se.load_company_map()
print(f"Company map loaded: {len(cmap)} entries ({time.time()-t0:.2f}s)", flush=True)

t1 = time.time()
print("2. Testing BM25 index...", flush=True)
bm25, doc_mapping = se.load_bm25_index()
print(f"BM25 loaded: doc_mapping len={len(doc_mapping) if doc_mapping else 0} ({time.time()-t1:.2f}s)", flush=True)

t2 = time.time()
print("3. Testing Qdrant client...", flush=True)
try:
    qc = se.load_qdrant_client()
    print(f"Qdrant loaded ({time.time()-t2:.2f}s)", flush=True)
except Exception as e:
    print(f"Qdrant error: {e}", flush=True)

t3 = time.time()
print("4. Testing SentenceTransformer model...", flush=True)
try:
    model = se.load_embedding_model()
    print(f"Model loaded ({time.time()-t3:.2f}s)", flush=True)
except Exception as e:
    print(f"Model error: {e}", flush=True)
