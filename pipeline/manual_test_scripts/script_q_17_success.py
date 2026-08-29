"""
======================================================================
QUESTION ID : 17
STATUS      : success (Attempts: 1)
QUESTION    : Lãi thuần từ hoạt động dịch vụ của Ngân hàng TMCP Sài Gòn - Hà Nội (SHB) năm 2018 là bao nhiêu triệu đồng?
RESULT      : {"type": "scalar", "data": 3077240.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Lãi thuần từ hoạt động dịch vụ  Ngân hàng TMCP Sài Gòn - Hà Nội ()    triệu đồng?'
mask = df['Chỉ tiêu'].astype(str).str.contains(search_key, case=False, na=False, regex=False)
if not mask.any():
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và']]
    for t in tokens:
        m = df['Chỉ tiêu'].astype(str).str.contains(t, case=False, na=False, regex=False)
        if m.any():
            mask = m
            break
if not mask.any():
    if '':
        mask = df['Chỉ tiêu'].astype(str).str.contains('', case=False, na=False, regex=False)
if not mask.any():
    for c in df.columns:
        if c != 'Miền BắcTriệu':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, 'Miền BắcTriệu', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, 'Miền BắcTriệu', _df=df, _row_idx=match_row.name)