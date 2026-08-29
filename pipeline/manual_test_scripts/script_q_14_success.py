"""
======================================================================
QUESTION ID : 14
STATUS      : success (Attempts: 1)
QUESTION    : Chi phí quản lý doanh nghiệp năm 2025 của công ty mẹ ASM là bao nhiêu triệu đồng?
RESULT      : {"type": "scalar", "data": 125224829308.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Chi phí quản lý doanh nghiệp    công ty mẹ   triệu đồng?'
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
        if c != 'Năm 2025':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, 'Năm 2025', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, 'Năm 2025', _df=df, _row_idx=match_row.name)