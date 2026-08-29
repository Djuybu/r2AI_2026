"""
======================================================================
QUESTION ID : 3
STATUS      : success (Attempts: 1)
QUESTION    : Chi phí dự phòng của Ngân hàng TMCP Sài Gòn Tài Lộc trong năm 2020 là bao nhiêu triệu đồng?
RESULT      : {"type": "scalar", "data": 172625.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Chi phí dự phòng  Ngân hàng TMCP Sài Gòn Tài Lộc trong    triệu đồng?'
mask = df['0'].astype(str).str.contains(search_key, case=False, na=False, regex=False)
if not mask.any():
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và']]
    for t in tokens:
        m = df['0'].astype(str).str.contains(t, case=False, na=False, regex=False)
        if m.any():
            mask = m
            break
if not mask.any():
    if '':
        mask = df['0'].astype(str).str.contains('', case=False, na=False, regex=False)
if not mask.any():
    for c in df.columns:
        if c != '1':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, '1', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, '1', _df=df, _row_idx=match_row.name)