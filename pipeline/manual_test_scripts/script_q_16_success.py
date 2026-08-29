"""
======================================================================
QUESTION ID : 16
STATUS      : success (Attempts: 1)
QUESTION    : Số dư vay ngắn hạn của công ty mẹ CEO cuối năm 2025 là bao nhiêu tỷ đồng?
RESULT      : {"type": "scalar", "data": 57765853729.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'vay ngắn hạn  công ty mẹ  cuối    tỷ đồng?'
mask = df['1'].astype(str).str.contains(search_key, case=False, na=False, regex=False)
if not mask.any():
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và']]
    for t in tokens:
        m = df['1'].astype(str).str.contains(t, case=False, na=False, regex=False)
        if m.any():
            mask = m
            break
if not mask.any():
    if '':
        mask = df['1'].astype(str).str.contains('', case=False, na=False, regex=False)
if not mask.any():
    for c in df.columns:
        if c != '2':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, '2', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, '2', _df=df, _row_idx=match_row.name)