"""
======================================================================
QUESTION ID : 6
STATUS      : success (Attempts: 1)
QUESTION    : Lưu chuyển tiền thuần từ hoạt động kinh doanh của công ty mẹ VSC trong năm 2017 là bao nhiêu tỷ đồng?
RESULT      : {"type": "scalar", "data": 529114885291.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Lưu chuyển tiền thuần từ hoạt động kinh doanh  công ty mẹ  trong    tỷ đồng?'
mask = df['Cột_0'].astype(str).str.contains(search_key, case=False, na=False, regex=False)
if not mask.any():
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và']]
    for t in tokens:
        m = df['Cột_0'].astype(str).str.contains(t, case=False, na=False, regex=False)
        if m.any():
            mask = m
            break
if not mask.any():
    if '':
        mask = df['Cột_0'].astype(str).str.contains('', case=False, na=False, regex=False)
if not mask.any():
    for c in df.columns:
        if c != '2017':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, '2017', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, '2017', _df=df, _row_idx=match_row.name)