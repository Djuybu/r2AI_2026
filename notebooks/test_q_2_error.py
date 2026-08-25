"""
======================================================================
QUESTION ID : 2
STATUS      : error (Attempts: 3)
QUESTION    : Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?
RESULT      : {"type": "error", "data": null}
ERROR       : Failed after reflection attempts
======================================================================
"""

import pandas as pd

file_path_2022 = '/kaggle/input/datasets/duymcminh/r2-ai-output/r2AI_data/ViFinQA/processed_data/ACB/2022/ACB_financial_statements_2022_consolidated/ACB_financial_statements_2022_consolidated_table_106.csv'
df = pd.read_csv(file_path_2022)

filtered_df = df[df['0'].astype(str).str.contains('Số dư cho vay khách hàng ngành Thương mại', case=False, na=False, regex=False)]
if not filtered_df.empty:
    result = extract_value(filtered_df.iloc[0], '1')
else:
    raise ValueError("Metric not found in table")