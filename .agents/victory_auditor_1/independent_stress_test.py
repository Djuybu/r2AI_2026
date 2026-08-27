import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import numpy as np
import pandas as pd

from pipeline.src.nodes.query_parser import (
    NEGATIVE_BLOCKLIST,
    ALIAS_TICKER_MAP,
    _normalize_company_name,
    _clean_financial_content,
    _fallback_parse_query,
)
from pipeline.src.nodes.schema_mapper import (
    AUXILIARY_COL_REGEX,
    _AUXILIARY_CODE_COLUMNS,
    _is_numeric_value,
    _is_code_or_index_column,
    _find_label_column,
    _find_value_column,
    _extract_useful_columns,
)
from pipeline.src.nodes.executor import (
    sanitize_code_str,
    validate_ast,
    clean_val,
    extract_value,
    SecurityError,
)

def run_stress_tests():
    print("=== STARTING INDEPENDENT AUDITOR ADVERSARIAL STRESS TESTS ===")
    passed = 0
    total = 0

    # 1. Query Parser & Entity Resolver Stress Tests
    cases_entity = [
        # (company_input, query, expected_ticker)
        ("", "Báo cáo thường niên của CTCP Tập đoàn Hòa Phát năm 2022", "HPG"),
        ("CTCP", "Doanh thu của CTCP Đầu tư Địa ốc No Va (NVL) 2021", "NVL"),
        ("Tập đoàn", "Chi phí quản lý của Novaland năm 2020", "NVL"),
        ("", "Lãi vay của CTCP Chứng khoán FPT (FTS) năm 2022", "FTS"),
        ("", "Doanh thu phần mềm của FPT năm 2023", "FPT"),
        ("CTCP", "Tỷ lệ sở hữu của CTCP Đầu tư Hạ tầng Giao thông Đèo Cả (HHV)", "HHV"),
        ("TMCP", "Dư nợ tín dụng của Ngân hàng TMCP Xuất nhập khẩu Việt Nam (Eximbank)", "EIB"),
        ("", "Tài sản ngắn hạn của Ngân hàng Quân đội (MBBank)", "MBB"),
        ("CTCP", "Vốn chủ sở hữu của Đức Long Gia Lai năm 2016", "DLG"),
        ("TỔNG CÔNG TY", "Doanh thu thuần không rõ", ""),  # Blocklist only -> empty
        ("BCTC", "Không có công ty nào được nhắc đến ở đây 2021", ""),
    ]

    for c_in, q, exp in cases_entity:
        total += 1
        res = _normalize_company_name(c_in, q)
        assert res == exp, f"[FAIL Entity] Query: '{q}' -> got '{res}', expected '{exp}'"
        passed += 1

    print(f"✅ Entity Resolution Stress Tests: {passed}/{total} Passed")

    # 2. Content Cleaner Stress Tests
    cases_cleaner = [
        ("tốc độ tăng trưởng % doanh thu thuần là bao nhiêu?", "doanh thu thuần"),
        ("tăng trưởng % lợi nhuận sau thuế của công ty mẹ", "lợi nhuận sau thuế của công ty mẹ"),
        ("mức biến động tổng tài sản thay đổi như thế nào?", "tổng tài sản"),
        ("tính tổng chi phí bán hàng", "chi phí bán hàng"),
        ("khoản phải thu khách hàng", "phải thu khách hàng"),
        ("giá trị còn lại của tài sản cố định vô hình", "tài sản cố định vô hình"),
        ("số dư các khoản phải trả", "các khoản phải trả"),
        ("", ""),
    ]

    for inp, exp in cases_cleaner:
        total += 1
        res = _clean_financial_content(inp)
        assert res.lower() == exp.lower(), f"[FAIL Cleaner] Input: '{inp}' -> got '{res}', expected '{exp}'"
        passed += 1

    print(f"✅ Content Cleaner Stress Tests Passed")

    # 3. Schema Mapper Index Rejection & Text Density Stress Tests
    # Float index series
    total += 1
    s_float = pd.Series(["1.0", "2.0", "3.0", "4.0", "5.0"])
    assert _is_code_or_index_column(s_float, "Cột_0") is True
    passed += 1

    # Short numerical strings
    total += 1
    s_codes = pd.Series(["100", "110", "111", "120", "200"])
    assert _is_code_or_index_column(s_codes, "Mã số") is True
    passed += 1

    # Real accounting line items with numbers in parentheses
    total += 1
    s_items = pd.Series([
        "I. Doanh thu bán hàng và cung cấp dịch vụ",
        "1. Doanh thu bán hàng hóa",
        "2. Doanh thu cung cấp dịch vụ",
        "II. Các khoản giảm trừ doanh thu",
        "III. Doanh thu thuần về bán hàng và cung cấp dịch vụ (10 = 01 - 02)",
    ])
    assert _is_code_or_index_column(s_items, "CHỈ TIÊU") is False
    passed += 1

    # 4. Longest text label column selection
    total += 1
    useful_mock = [
        {"raw_column": "col_0", "column_name": "STT", "data_type": "text", "is_aux_code": True, "avg_str_len": 2.0, "letter_ratio": 0.0},
        {"raw_column": "col_1", "column_name": "Mã số", "data_type": "text", "is_aux_code": True, "avg_str_len": 3.0, "letter_ratio": 0.0},
        {"raw_column": "col_2", "column_name": "NỘI DUNG CHỈ TIÊU", "data_type": "text", "is_aux_code": False, "avg_str_len": 32.5, "letter_ratio": 0.85},
        {"raw_column": "col_3", "column_name": "2023", "data_type": "numeric", "is_aux_code": False, "avg_str_len": 10.0, "letter_ratio": 0.0},
    ]
    lbl = _find_label_column(useful_mock)
    assert lbl == "col_2", f"Expected col_2, got {lbl}"
    passed += 1

    # 5. Value column matching with %
    total += 1
    val_mock = [
        {"raw_column": "col_2", "column_name": "Tên công ty con", "data_type": "text", "is_aux_code": False},
        {"raw_column": "col_3", "column_name": "Tỷ lệ quyền biểu quyết (%)", "data_type": "numeric", "is_aux_code": False},
        {"raw_column": "col_4", "column_name": "Số lượng CP", "data_type": "numeric", "is_aux_code": False},
    ]
    val_c = _find_value_column(val_mock, label_col="col_2", tieu_chi_phu="quyền biểu quyết")
    assert val_c == "col_3", f"Expected col_3, got {val_c}"
    passed += 1

    # 6. AST Sanitization and Execution
    total += 1
    code_raw = """
df_filt = df[df['CHỈ TIÊU'].str.contains('Doanh thu thuần', case=False, na=False)]
if 'Doanh thu thuần' in df['CHỈ TIÊU'].str.contains('Doanh thu'):
    result = 123
"""
    code_sanitized = sanitize_code_str(code_raw)
    assert "df['CHỈ TIÊU'].astype(str).str.contains" in code_sanitized
    assert "if (df['CHỈ TIÊU'].astype(str).str.contains('Doanh thu')).any():" in code_sanitized
    validate_ast(code_sanitized)
    passed += 1

    print(f"=== ALL {passed}/{total} INDEPENDENT ADVERSARIAL STRESS TESTS PASSED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_stress_tests()
