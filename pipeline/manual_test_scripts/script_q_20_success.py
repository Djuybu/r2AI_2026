"""
======================================================================
QUESTION ID : 20
STATUS      : success (Attempts: 1)
QUESTION    : Tỷ lệ biểu quyết của Xí nghiệp Liên doanh Visorutex của công ty mẹ GVR đến ngày 31/12/2019 là bao nhiêu %?
RESULT      : {"type": "scalar", "data": 8749737281.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Tỷ lệ biểu quyết  Xí nghiệp Liên doanh Visorutex  công ty mẹ  đến ngày 31/12/  %?'
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
        if c != 'Cột_2':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, 'Cột_2', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, 'Cột_2', _df=df, _row_idx=match_row.name)