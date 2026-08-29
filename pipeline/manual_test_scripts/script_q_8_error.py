"""
======================================================================
QUESTION ID : 8
STATUS      : error (Attempts: 1)
QUESTION    : Chi phí lương và các khoản khác theo lương của công ty mẹ CTCP Chứng khoán FPT trong năm 2021 là bao nhiêu tỷ đồng?
RESULT      : None
ERROR       : Traceback (most recent call last):
  File "/kaggle/working/r2AI_2026/pipeline/src/nodes/executor.py", line 392, in executor_node
    raise ValueError(f"Không tìm thấy chỉ tiêu trong toàn bộ Top {len(top_candidates)} bảng ứng viên.")
ValueError: Không tìm thấy chỉ tiêu trong toàn bộ Top 5 bảng ứng viên.

======================================================================
"""

import pandas as pd
import numpy as np
df = pd.read_csv(file_path)
# Lọc theo thực thể nhân sự: 'và các khoản khác'
mask = df['1'].astype(str).str.contains('và các khoản khác', case=False, na=False, regex=False)
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, '0', _df=df, _row_idx=match_row.name)
else:
    raise ValueError('Person not found in table')