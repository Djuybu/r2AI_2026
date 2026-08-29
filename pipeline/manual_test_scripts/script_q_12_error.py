"""
======================================================================
QUESTION ID : 12
STATUS      : error (Attempts: 1)
QUESTION    : Vốn cổ phần đã phát hành của công ty mẹ VGT là bao nhiêu nghìn tỷ đồng vào cuối năm 2024?
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
# Lọc theo thực thể nhân sự: 'đã phát hành của'
mask = df['Cột_0'].astype(str).str.contains('đã phát hành của', case=False, na=False, regex=False)
if mask.any():
    match_row = df[mask].iloc[0]
    result = extract_value(match_row, '31/12/2024', _df=df, _row_idx=match_row.name)
else:
    raise ValueError('Person not found in table')