"""
======================================================================
QUESTION ID : 19
STATUS      : success (Attempts: 1)
QUESTION    : Tổng tỷ lệ quyền biểu quyết của công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023 là bao nhiêu phần trăm?
RESULT      : {"type": "scalar", "data": 70.36}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Tổng tỷ lệ quyền biểu quyết  công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả    phần trăm?'
mask = df['Tên Công ty'].astype(str).str.contains(search_key, case=False, na=False, regex=False)
if not mask.any():
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và']]
    for t in tokens:
        m = df['Tên Công ty'].astype(str).str.contains(t, case=False, na=False, regex=False)
        if m.any():
            mask = m
            break
if not mask.any():
    if '':
        mask = df['Tên Công ty'].astype(str).str.contains('', case=False, na=False, regex=False)
if not mask.any():
    for c in df.columns:
        if c != 'Tỷ lệ quyền biểu quyết':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, 'Tỷ lệ quyền biểu quyết', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, 'Tỷ lệ quyền biểu quyết', _df=df, _row_idx=match_row.name)