"""
======================================================================
QUESTION ID : 10
STATUS      : success (Attempts: 1)
QUESTION    : Chi phí tài chính của công ty mẹ CTCP Phát triển Sunshine Homes năm 2021 là bao nhiêu triệu đồng?
RESULT      : {"type": "scalar", "data": 479813676934.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Chi phí   công ty mẹ CTCP Phát triển Sunshine Homes    triệu đồng?'
mask = df['Bên liên quan'].astype(str).str.contains(search_key, case=False, na=False, regex=False)
if not mask.any():
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và']]
    for t in tokens:
        m = df['Bên liên quan'].astype(str).str.contains(t, case=False, na=False, regex=False)
        if m.any():
            mask = m
            break
if not mask.any():
    if '':
        mask = df['Bên liên quan'].astype(str).str.contains('', case=False, na=False, regex=False)
if not mask.any():
    for c in df.columns:
        if c != 'Năm nay':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, 'Năm nay', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, 'Năm nay', _df=df, _row_idx=match_row.name)