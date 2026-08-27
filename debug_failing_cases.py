import os, sys, unicodedata
import pandas as pd
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

import rag_module.search_engine as se
se._ensure_resources()

def strip_accents(text: str) -> str:
    if not text:
        return ""
    t = text.replace("đ", "d").replace("Đ", "D")
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn").lower()

print("Testing exact file matching for 6 remaining cases:")

# 1. ACB table 34_0
p_acb = Path("r2AI_2026/rag_module/ViFinQA/processed_data/ACB/2022/ACB_financial_statements_2022_separate/ACB_financial_statements_2022_separate_table_34_0.csv")
if p_acb.exists():
    df = pd.read_csv(p_acb)
    col, s = se.get_first_meaningful_column(df)
    print(f"\n1. ACB table 34_0: Col='{col}', Rows={s.dropna().tolist()[:3]}")
    doc_in_mapping = [d for d in se._doc_mapping if "table_34_0" in d.get("csv_path", "") and d.get("Ma_Doanh_Nghiep") == "ACB" and str(d.get("Nam_Tai_Chinh")) == "2022"]
    print(f"   In doc_mapping? {len(doc_in_mapping)} docs found. First doc: {doc_in_mapping[0] if doc_in_mapping else 'None'}")

# 2. FTS table 44_0
p_fts = Path("r2AI_2026/rag_module/ViFinQA/processed_data/FTS/2021/FTS_financial_statements_2021/FTS_financial_statements_2021_table_44_0.csv")
if p_fts.exists():
    df = pd.read_csv(p_fts)
    col, s = se.get_first_meaningful_column(df)
    print(f"\n2. FTS table 44_0: Col='{col}', Rows={s.dropna().tolist()[:3]}")
    doc_in_mapping = [d for d in se._doc_mapping if "table_44_0" in d.get("csv_path", "") and d.get("Ma_Doanh_Nghiep") == "FTS" and str(d.get("Nam_Tai_Chinh")) == "2021"]
    print(f"   In doc_mapping? {len(doc_in_mapping)} docs found.")

# 3. GVR table 16_0
p_gvr = Path("r2AI_2026/rag_module/ViFinQA/processed_data/GVR/2019/GVR_financial_statements_2019_separate/GVR_financial_statements_2019_separate_table_16_0.csv")
if p_gvr.exists():
    df = pd.read_csv(p_gvr)
    col, s = se.get_first_meaningful_column(df)
    print(f"\n3. GVR table 16_0: Col='{col}', Rows={s.dropna().tolist()[:3]}")
    doc_in_mapping = [d for d in se._doc_mapping if "table_16_0" in d.get("csv_path", "") and d.get("Ma_Doanh_Nghiep") == "GVR" and str(d.get("Nam_Tai_Chinh")) == "2019"]
    print(f"   In doc_mapping? {len(doc_in_mapping)} docs found.")

# 4. DLG table 8 / 8_0
p_dlg = Path("r2AI_2026/rag_module/ViFinQA/processed_data/DLG/2024/DLG_financial_statements_2024_separate/DLG_financial_statements_2024_separate_table_8.csv")
if p_dlg.exists():
    df = pd.read_csv(p_dlg)
    col, s = se.get_first_meaningful_column(df)
    print(f"\n4. DLG table 8: Col='{col}', Rows={s.dropna().tolist()[:5]}")
    doc_in_mapping = [d for d in se._doc_mapping if "table_8" in d.get("csv_path", "") and d.get("Ma_Doanh_Nghiep") == "DLG" and str(d.get("Nam_Tai_Chinh")) == "2024"]
    print(f"   In doc_mapping? {len(doc_in_mapping)} docs found.")

# 5. OGC table 4_0
p_ogc = Path("r2AI_2026/rag_module/ViFinQA/processed_data/OGC/2019/OGC_financial_statements_2019_separate/OGC_financial_statements_2019_separate_table_4_0.csv")
if p_ogc.exists():
    df = pd.read_csv(p_ogc)
    col, s = se.get_first_meaningful_column(df)
    print(f"\n5. OGC table 4_0: Col='{col}', Rows={s.dropna().tolist()[:5]}")
    doc_in_mapping = [d for d in se._doc_mapping if "table_4_0" in d.get("csv_path", "") and d.get("Ma_Doanh_Nghiep") == "OGC" and str(d.get("Nam_Tai_Chinh")) == "2019"]
    print(f"   In doc_mapping? {len(doc_in_mapping)} docs found.")

# 6. VRE table 30
p_vre = Path("r2AI_2026/rag_module/ViFinQA/processed_data/VRE/2016/VRE_financial_statements_2016_consolidated/VRE_financial_statements_2016_consolidated_table_30.csv")
if p_vre.exists():
    df = pd.read_csv(p_vre)
    col, s = se.get_first_meaningful_column(df)
    print(f"\n6. VRE table 30: Col='{col}', Rows={s.dropna().tolist()[:5]}")
    doc_in_mapping = [d for d in se._doc_mapping if "table_30" in d.get("csv_path", "") and d.get("Ma_Doanh_Nghiep") == "VRE" and str(d.get("Nam_Tai_Chinh")) == "2016"]
    print(f"   In doc_mapping? {len(doc_in_mapping)} docs found.")
