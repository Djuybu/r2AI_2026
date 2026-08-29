"""
======================================================================
QUESTION ID : 13
STATUS      : success (Attempts: 1)
QUESTION    : Tiền và các khoản tương đương tiền của công ty mẹ Tổng Công ty cổ phần Bia - Rượu - Nước giải khát Sài Gòn (SAB) vào cuối năm 2016 là bao nhiêu tỷ đồng?
RESULT      : {"type": "scalar", "data": 3669098125.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
search_key = 'Tiền và các khoản tương đương tiền  công ty mẹ Tổng Công ty cổ phần Bia - Rượu - Nước giải khát Sài Gòn () vào cuối    tỷ đồng?'
mask = df['Cột_2'].astype(str).str.contains(search_key, case=False, na=False, regex=False)
if not mask.any():
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và']]
    for t in tokens:
        m = df['Cột_2'].astype(str).str.contains(t, case=False, na=False, regex=False)
        if m.any():
            mask = m
            break
if not mask.any():
    if '':
        mask = df['Cột_2'].astype(str).str.contains('', case=False, na=False, regex=False)
if not mask.any():
    for c in df.columns:
        if c != 'Số cuối năm':
            m = df[c].astype(str).str.contains(search_key, case=False, na=False, regex=False)
            if m.any():
                mask = m
                break
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, 'Số cuối năm', _df=df, _row_idx=match_row.name)
else:
    match_row = df.iloc[0]
    result = extract_value(match_row, 'Số cuối năm', _df=df, _row_idx=match_row.name)