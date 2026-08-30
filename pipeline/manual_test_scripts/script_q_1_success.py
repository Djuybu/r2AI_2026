"""
======================================================================
QUESTION ID : 1
STATUS      : success (Attempts: 1)
QUESTION    : Lãi tiền gửi năm 2018 của công ty mẹ CTCP Hàng không Vietjet (VJC) là bao nhiêu triệu đồng?
RESULT      : {"type": "scalar", "data": 208253201298.0}
ERROR       : None
======================================================================
"""

import pandas as pd
import numpy as np

df = pd.read_csv(file_path)
# Truy vấn trực tiếp theo vị trí chỉ số cột từ Schema Mapper (label_col_idx = 7, value_col_idx = 9)
label_idx = 7
value_idx = 9
search_key = 'Lãi tiền gửi'

filtered_df = df[df.iloc[:, label_idx].astype(str).str.contains(search_key, case=False, na=False, regex=False)]
if filtered_df.empty:
    tokens = [t for t in search_key.split() if len(t) > 2 and t.lower() not in ['tổng', 'chi_phí', 'doanh_thu', 'năm', 'của', 'và', 'các', 'khoản', 'theo', 'công', 'mẹ', 'đã', 'phát', 'hành']]
    for t in tokens:
        filtered_df = df[df.iloc[:, label_idx].astype(str).str.contains(t, case=False, na=False, regex=False)]
        if not filtered_df.empty:
            break

if not filtered_df.empty:
    match_row = filtered_df.iloc[0]
    result = extract_value(match_row, value_idx, _df=df, _row_idx=match_row.name, abs_val=True)
else:
    raise ValueError(f"Metric '{search_key}' not found at column index {label_idx}")