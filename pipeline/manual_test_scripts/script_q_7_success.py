"""
======================================================================
QUESTION ID : 7
STATUS      : success (Attempts: 1)
QUESTION    : Quỹ khen thưởng, phúc lợi của HT1 cuối năm 2019 là bao nhiêu tỷ đồng?
RESULT      : {"type": "scalar", "data": 583896009701.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Quỹ khen thưởng, phúc lợi  HT1 cuối    tỷ đồng?'
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