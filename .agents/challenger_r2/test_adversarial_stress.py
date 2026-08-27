"""
d:/hobby_project/cocopila/r2AI_2026/.agents/challenger_r2/test_adversarial_stress.py
================================================================================
Empirical Adversarial Stress Test Suite for Cocopila ViFinQA Pipeline:
- Node 1: query_parser.py (_normalize_company_name, _clean_financial_content, _fallback_parse_query)
- Node 3: schema_mapper.py (_is_code_or_index_column, _find_label_column, _find_value_column, _extract_useful_columns, _resolve_column_header)
- Node 5: executor.py (sanitize_code_str, validate_ast, clean_val, extract_value, sandbox execution)
"""

import sys
import os
import re
import json
import pytest
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline.src.config import Config, config as default_config
from pipeline.src.nodes.query_parser import (
    NEGATIVE_BLOCKLIST,
    ALIAS_TICKER_MAP,
    _normalize_company_name,
    _clean_financial_content,
    _fallback_parse_query,
    parse_query_node,
)
from pipeline.src.nodes.schema_mapper import (
    AUXILIARY_COL_REGEX,
    _AUXILIARY_CODE_COLUMNS,
    _is_cell_empty,
    _is_numeric_value,
    _resolve_column_header,
    _is_code_or_index_column,
    _extract_useful_columns,
    _find_label_column,
    _find_value_column,
    _extract_sub_sections,
    schema_mapper_node,
)
from pipeline.src.nodes.executor import (
    sanitize_code_str,
    validate_ast,
    clean_val,
    extract_value,
    executor_node,
    SecurityError,
)


# =====================================================================
# 1. ADVERSARIAL SUITE: NODE 1 QUERY PARSER & ENTITY RESOLUTION
# =====================================================================

class TestAdversarialQueryParser:
    """Stress-test company normalization and content cleaning with adversarial inputs."""

    @pytest.mark.parametrize("blocklist_term", list(NEGATIVE_BLOCKLIST))
    def test_blocklist_terms_rejected_as_company(self, blocklist_term: str):
        """Every single blocklisted term must NEVER be returned as a valid company ticker."""
        query = f"Báo cáo tài chính của {blocklist_term} năm 2022"
        # 1. When passed as company_input
        res1 = _normalize_company_name(blocklist_term, query)
        assert res1 != blocklist_term or blocklist_term == "", f"Blocklist term '{blocklist_term}' was accepted!"
        assert res1 not in NEGATIVE_BLOCKLIST, f"Result '{res1}' is in NEGATIVE_BLOCKLIST!"

        # 2. When passed as empty company_input
        res2 = _normalize_company_name("", query)
        assert res2 not in NEGATIVE_BLOCKLIST, f"Result '{res2}' is in NEGATIVE_BLOCKLIST!"

    def test_parentheses_ticker_with_blocklist_term(self):
        """Parentheses containing blocklisted words like (VND), (USD), (CTCP), (BCTC) must NOT resolve to ticker."""
        assert _normalize_company_name("", "Doanh thu năm 2021 (VND) là bao nhiêu?") != "VND"
        assert _normalize_company_name("", "Báo cáo của công ty (CTCP) năm 2020") != "CTCP"
        assert _normalize_company_name("", "Chỉ tiêu theo (BCTC) hợp nhất") != "BCTC"
        assert _normalize_company_name("", "Tăng trưởng theo (USD) năm 2023") != "USD"

    def test_parentheses_ticker_priority_over_alias(self):
        """Parenthesized explicit ticker takes highest precedence even if another brand is mentioned."""
        # Query mentions 'Novaland' brand but explicitly specifies (VJC)
        q = "Số liệu của Novaland theo báo cáo tài chính của Vietjet (VJC) năm 2021"
        res = _normalize_company_name("", q)
        assert res == "VJC", f"Expected VJC from parens, got {res}"

    def test_brand_alias_nested_and_ambiguous_names(self):
        """Test brand aliases with overlapping/nested names to ensure longest match succeeds."""
        cases = [
            ("Tập đoàn Đầu tư Địa ốc No Va", "NVL"),
            ("Địa ốc No Va", "NVL"),
            ("Novaland", "NVL"),
            ("CTCP Chứng khoán FPT", "FTS"),
            ("Chứng khoán FPT", "FTS"),
            ("Viễn thông FPT", "FOX"),
            ("FPT Telecom", "FOX"),
            ("Tập đoàn FPT", "FPT"),
            ("FPT", "FPT"),
            ("Bất động sản Đất Xanh", "DXS"),
            ("Đất Xanh", "DXG"),
            ("Tập đoàn Masan", "MSN"),
            ("Hàng tiêu dùng Masan", "MCH"),
            ("Masan Consumer", "MCH"),
            ("Masan MeatLife", "MML"),
            ("Masan High-Tech Materials", "MSR"),
            ("Tập đoàn GELEX", "GEX"),
            ("Điện lực GELEX", "GEE"),
            ("Gelex Electric", "GEE"),
            ("HAGL Agrico", "HNG"),
            ("Nông nghiệp Quốc tế Hoàng Anh Gia Lai", "HNG"),
            ("Hoàng Anh Gia Lai", "HAG"),
            ("HAGL", "HAG"),
            ("Nhựa An Phát Xanh", "AAA"),
            ("An Phát Xanh", "AAA"),
            ("An Phát", "AAA"),
            ("Tập đoàn Sao Mai", "ASM"),
            ("Sao Mai", "ASM"),
            ("Tập đoàn Sunshine", "SSH"),
            ("Sunshine Homes", "SSH"),
            ("Bất động sản Văn Phú", "VPI"),
            ("Văn Phú Invest", "VPI"),
            ("Bất động sản Thế Kỷ", "CRE"),
            ("Cenland", "CRE"),
            ("Xi măng Vicem Hà Tiên", "HT1"),
            ("Vicem Hà Tiên", "HT1"),
            ("Hà Tiên 1", "HT1"),
            ("Hạ tầng Giao thông Đèo Cả", "HHV"),
            ("Đèo Cả", "HHV"),
            ("Tập đoàn Đức Long Gia Lai", "DLG"),
            ("Đức Long Gia Lai", "DLG"),
        ]
        for query_frag, expected_ticker in cases:
            q = f"Lợi nhuận năm 2022 của {query_frag} là bao nhiêu tỷ đồng?"
            res = _normalize_company_name("", q)
            assert res == expected_ticker, f"Failed for '{query_frag}': got '{res}', expected '{expected_ticker}'"

    def test_company_normalization_pathological_inputs(self):
        """Test with empty strings, None, punctuation, numbers, and SQL-like injections."""
        assert _normalize_company_name("", "") == ""
        assert _normalize_company_name("   ", "   ") == ""
        assert _normalize_company_name(None, None) == ""
        assert _normalize_company_name("'; DROP TABLE stock; --", "'; DROP TABLE stock; --") == "'; DROP TABLE stock; --"
        assert _normalize_company_name("12345", "12345 67890") == "12345"
        assert _normalize_company_name("", "Câu hỏi không có tên công ty nào cả vào năm 2021") == ""

    @pytest.mark.parametrize("input_text,expected_sub", [
        ("tốc độ tăng trưởng % doanh thu thuần là bao nhiêu?", "doanh thu thuần"),
        ("tốc độ tăng trưởng lợi nhuận sau thuế của công ty", "lợi nhuận sau thuế của công ty"),
        ("mức biến động chi phí quản lý doanh nghiệp thay đổi như thế nào?", "chi phí quản lý doanh nghiệp"),
        ("chênh lệch doanh thu tài chính năm nay so với năm trước", "doanh thu tài chính năm nay so với năm trước"),
        ("tính tổng chi phí lãi vay là bao nhiêu", "chi phí lãi vay"),
        ("trích xuất các khoản đầu tư nắm giữ đến ngày đáo hạn", "các khoản đầu tư nắm giữ đến ngày đáo hạn"),
        ("cho biết giá trị ghi sổ của tài sản cố định", "giá trị ghi sổ của tài sản cố định"),
        ("số dư các khoản phải thu ngắn hạn của khách hàng", "các khoản phải thu ngắn hạn của khách hàng"),
        ("tổng số tiền gửi ngân hàng", "tiền gửi ngân hàng"),
        ("tổng giá trị hàng tồn kho cuối kỳ", "hàng tồn kho cuối kỳ"),
        ("khoản phải trả người bán ngắn hạn", "phải trả người bán ngắn hạn"),
        ("giá trị còn lại của bất động sản đầu tư là bao nhiêu?", "bất động sản đầu tư"),
    ])
    def test_clean_financial_content_stacked_prefixes_and_suffixes(self, input_text: str, expected_sub: str):
        """Verify _clean_financial_content removes prefixes and suffixes cleanly."""
        cleaned = _clean_financial_content(input_text)
        assert expected_sub.lower() in cleaned.lower(), (
            f"Expected '{expected_sub}' in '{cleaned}' (from input '{input_text}')"
        )
        assert "bao nhiêu" not in cleaned.lower()
        assert "thế nào" not in cleaned.lower()
        assert not cleaned.lower().startswith("tốc độ tăng trưởng")
        assert not cleaned.lower().startswith("tính tổng")
        assert not cleaned.lower().startswith("trích xuất")
        assert not cleaned.lower().startswith("cho biết")

    def test_clean_financial_content_edge_cases(self):
        """Verify edge cases for content cleaner: empty, None, special regex chars."""
        assert _clean_financial_content("") == ""
        assert _clean_financial_content(None) == ""
        assert _clean_financial_content("   ") == ""
        # String with regex chars
        regex_str = "Khoản mục [A.1] (Phải thu ngắn hạn) + 10% * chi phí?"
        cleaned_regex = _clean_financial_content(regex_str)
        assert "phải thu ngắn hạn" in cleaned_regex.lower()

    def test_fallback_query_parser_adversarial_queries(self):
        """Stress-test _fallback_parse_query with multiple years, comparison indicators, and ranges."""
        # 1. Explicit year range
        q1 = "So sánh doanh thu từ năm 2019 đến năm 2023 của Novaland"
        res1 = _fallback_parse_query(q1)
        assert res1["ticker"] == "NVL"
        assert res1["thao_tac"] == "so_sanh"
        assert set(res1["so_nam"]) == {"2019", "2020", "2021", "2022", "2023"}

        # 2. Reverse range
        q2 = "Tăng trưởng lợi nhuận từ năm 2023 đến năm 2021 của Đèo Cả"
        res2 = _fallback_parse_query(q2)
        assert res2["ticker"] == "HHV"
        assert res2["thao_tac"] == "so_sanh"
        assert set(res2["so_nam"]) == {"2021", "2022", "2023"}

        # 3. Single year extraction
        q3 = "Cho biết tổng tài sản năm 2020 của Vinamilk"
        res3 = _fallback_parse_query(q3)
        assert res3["ticker"] == "VNM"
        assert res3["thao_tac"] == "trich_xuat"
        assert res3["so_nam"] == ["2020"]


# =====================================================================
# 2. ADVERSARIAL SUITE: NODE 3 SCHEMA MAPPER RESOLUTION
# =====================================================================

class TestAdversarialSchemaMapper:
    """Stress-test Schema Mapper column classification, header resolution, and label/value detection."""

    def test_auxiliary_column_detection_stress(self):
        """Exhaustive check on all variations of auxiliary column names and representations."""
        aux_names = [
            "STT", "stt", "Stt", "SỐ TT", "Số TT", "số tt", "Số thứ tự", "SỐ THỨ TỰ", "sothutu",
            "MÃ SỐ", "Mã số", "mã số", "MÃSỐ", "MãSố", "mãsố", "code", "CODE", "Code", "ms", "MS", "Ms",
            "THUYẾT MINH", "Thuyết minh", "thuyết minh", "TM", "tm", "Tm", "ghi chú", "GHI CHÚ",
            "note", "NOTE", "Note", "Cột_0", "cột_0", "CỘT_0", "Cột_1", "cột_99",
            "unnamed: 0", "Unnamed: 0", "UNNAMED: 0", "unnamed: 1_level_0"
        ]
        for name in aux_names:
            assert AUXILIARY_COL_REGEX.match(name) or name.lower() in _AUXILIARY_CODE_COLUMNS, (
                f"Auxiliary header '{name}' was not detected as auxiliary!"
            )

    def test_is_code_or_index_column_synthetic_adversarial_series(self):
        """Construct synthetic adversarial Series to challenge _is_code_or_index_column heuristics."""
        # 1. Float index sequence: '1.0', '2.0', '3.0', ...
        s_float = pd.Series([f"{i}.0" for i in range(1, 25)])
        assert _is_code_or_index_column(s_float, col_name="Cột_0") is True

        # 2. Mixed float/integer index: '1.0', '1.1', '1.2', '2.0'
        s_sub_idx = pd.Series(["1.0", "1.1", "1.2", "2.0", "2.1", "3.0"])
        assert _is_code_or_index_column(s_sub_idx, col_name="0") is True

        # 3. Short line codes: '100', '110', '111', '120', '200', '300'
        s_line_codes = pd.Series(["100", "110", "111", "112", "120", "130", "140", "200"])
        assert _is_code_or_index_column(s_line_codes, col_name="col_a") is True

        # 4. Roman numerals with sub-letters: 'I', 'II', 'III', 'IV', 'V', 'a', 'b', 'c'
        s_roman_letters = pd.Series(["I", "II", "III", "IV", "V", "a", "b", "c"])
        assert _is_code_or_index_column(s_roman_letters, col_name="0") is True

        # 5. Footnote numbers with high NaNs: '29.0', None, None, '30.0', None
        s_footnotes = pd.Series(["29.0", None, None, "30.0", None, None, "31.0"])
        assert _is_code_or_index_column(s_footnotes, col_name="1") is True

        # 6. Ultra-short strings with symbols: '(*)', '(1)', '(2)', '(a)'
        s_parens = pd.Series(["(1)", "(2)", "(3)", "(4)", "(5)"])
        assert _is_code_or_index_column(s_parens, col_name="col") is True

        # 7. Real financial labels with numbers: "1. Doanh thu bán hàng", "2. Các khoản giảm trừ"
        # MUST BE RECOGNIZED AS FALSE (NOT auxiliary code!) because of high letter ratio and length
        s_real_labels = pd.Series([
            "1. Doanh thu bán hàng và cung cấp dịch vụ",
            "2. Các khoản giảm trừ doanh thu",
            "3. Doanh thu thuần về bán hàng và cung cấp dịch vụ",
            "4. Giá vốn hàng bán",
            "5. Lợi nhuận gộp về bán hàng và cung cấp dịch vụ",
        ])
        assert _is_code_or_index_column(s_real_labels, col_name="Chỉ tiêu") is False

        # 8. Real financial labels without numbers
        s_pure_labels = pd.Series([
            "TÀI SẢN NGẮN HẠN",
            "Tiền và các khoản tương đương tiền",
            "Đầu tư tài chính ngắn hạn",
            "Các khoản phải thu ngắn hạn",
            "Hàng tồn kho",
            "Tài sản ngắn hạn khác",
        ])
        assert _is_code_or_index_column(s_pure_labels, col_name="TÀI SẢN") is False

    def test_find_label_column_synthetic_race_conditions(self):
        """Test _find_label_column when multiple candidate text columns exist."""
        # Synthetic Useful Columns where Col 0 is STT, Col 1 is footnote, Col 2 is real label, Col 3 is short note
        useful_cols = [
            {"raw_column": "0", "column_name": "Cột_0", "data_type": "text", "is_aux_code": True, "avg_str_len": 3.0, "letter_ratio": 0.0},
            {"raw_column": "1", "column_name": "Mã số", "data_type": "text", "is_aux_code": True, "avg_str_len": 3.2, "letter_ratio": 0.1},
            {"raw_column": "2", "column_name": "Chỉ tiêu", "data_type": "text", "is_aux_code": False, "avg_str_len": 28.5, "letter_ratio": 0.85},
            {"raw_column": "3", "column_name": "Thuyết minh", "data_type": "text", "is_aux_code": True, "avg_str_len": 4.0, "letter_ratio": 0.2},
            {"raw_column": "4", "column_name": "2023", "data_type": "numeric", "is_aux_code": False, "avg_str_len": 12.0, "letter_ratio": 0.0},
        ]
        label_col = _find_label_column(useful_cols)
        assert label_col == "2", f"Expected '2' (Chỉ tiêu), got {label_col}"

    def test_find_label_column_fallback_when_all_flagged_aux(self):
        """When every column is text or aux, _find_label_column should pick the one with max avg_str_len gracefully."""
        useful_cols = [
            {"raw_column": "0", "column_name": "0", "data_type": "text", "is_aux_code": True, "avg_str_len": 3.0, "letter_ratio": 0.0},
            {"raw_column": "1", "column_name": "1", "data_type": "text", "is_aux_code": True, "avg_str_len": 15.0, "letter_ratio": 0.5},
        ]
        label_col = _find_label_column(useful_cols)
        assert label_col == "1", f"Fallback failed: expected '1', got {label_col}"

    def test_find_value_column_percentage_keyword_prioritization(self):
        """Test _find_value_column selects percentage column when tieu_chi_phu asks for percentage/voting rights."""
        useful_cols = [
            {"raw_column": "0", "column_name": "Tên công ty con", "data_type": "text", "is_aux_code": False},
            {"raw_column": "1", "column_name": "Địa chỉ", "data_type": "text", "is_aux_code": False},
            {"raw_column": "2", "column_name": "Tỷ lệ quyền biểu quyết (%)", "data_type": "numeric", "is_aux_code": False},
            {"raw_column": "3", "column_name": "Giá trị góp vốn (VND)", "data_type": "numeric", "is_aux_code": False},
        ]
        # Query asking for %
        assert _find_value_column(useful_cols, label_col="0", tieu_chi_phu="%") == "2"
        assert _find_value_column(useful_cols, label_col="0", tieu_chi_phu="quyền biểu quyết") == "2"
        assert _find_value_column(useful_cols, label_col="0", tieu_chi_phu="tỷ lệ sở hữu") == "2"
        # Query asking for capital amount
        assert _find_value_column(useful_cols, label_col="0", tieu_chi_phu="giá trị góp vốn") == "3"
        # Default query without tieu_chi_phu selects first primary numeric
        assert _find_value_column(useful_cols, label_col="0", tieu_chi_phu=None) == "2"

    def test_schema_mapper_with_synthetic_extreme_dataframes(self):
        """Run full _extract_useful_columns on synthetic edge-case DataFrames."""
        # 1. DataFrame with integer columns and mixed types
        df_int_cols = pd.DataFrame({
            0: ["TÀI SẢN NGẮN HẠN", "Tiền", "Phải thu"],
            1: ["100", "110", "120"],  # mã số
            2: ["100.000.000", "50.000.000", "50.000.000"],  # numeric values
            3: [None, None, None],  # empty column
        })
        useful = _extract_useful_columns(df_int_cols)
        cols = [c["raw_column"] for c in useful]
        assert "0" in cols
        assert "1" in cols
        assert "2" in cols
        assert "3" not in cols  # empty column filtered out

        label_col = _find_label_column(useful)
        assert label_col == "0"

        value_col = _find_value_column(useful, label_col=label_col)
        assert value_col == "2"


# =====================================================================
# 3. ADVERSARIAL SUITE: NODE 5 EXECUTOR & AST SANITIZER
# =====================================================================

class TestAdversarialExecutorSanitizer:
    """Stress-test AST sandbox safety, regex sanitization, clean_val, and extract_value."""

    def test_sanitize_code_str_basic_cases(self):
        """Test sanitize_code_str against standard Pandas single-expression fixes."""
        cases = [
            # 1. Basic missing astype(str)
            (
                "df[df['0'].str.contains('keyword')]",
                "df[df['0'].astype(str).str.contains('keyword')]"
            ),
            # 2. Already has astype(str) -> must NOT duplicate
            (
                "df[df['0'].astype(str).str.contains('keyword')]",
                "df[df['0'].astype(str).str.contains('keyword')]"
            ),
            # 3. Double quotes
            (
                'df[df["TÀI SẢN"].str.contains("Tiền")]',
                'df[df["TÀI SẢN"].astype(str).str.contains("Tiền")]'
            ),
            # 4. Chained string methods
            (
                "df[df['0'].str.strip().str.contains('X')]",
                "df[df['0'].astype(str).str.strip().str.contains('X')]"
            ),
            # 5. Equality check conversion
            (
                "df[df['Chỉ tiêu'] == 'Lợi nhuận']",
                "df[df['Chỉ tiêu'].astype(str).str.contains('Lợi nhuận', case=False, na=False, regex=False)]"
            ),
            # 6. Column with spaces and special characters
            (
                "df[df['Tên khoản mục (BCTC)'].str.contains('Hàng tồn kho')]",
                "df[df['Tên khoản mục (BCTC)'].astype(str).str.contains('Hàng tồn kho')]"
            ),
        ]
        for input_code, expected_pattern in cases:
            sanitized = sanitize_code_str(input_code)
            assert expected_pattern in sanitized or sanitized == expected_pattern, (
                f"Sanitizer failed for:\n{input_code}\nGot:\n{sanitized}\nExpected:\n{expected_pattern}"
            )

    def test_clean_val_extreme_inputs(self):
        """Test clean_val with extreme values, formatting edge cases, and invalid inputs."""
        # 1. Valid numbers in various formats
        assert clean_val(0) == 0.0
        assert clean_val(1234567890123.0) == 1234567890123.0
        assert clean_val("0") == 0.0
        assert clean_val("1.234.567.890") == 1234567890.0
        assert clean_val("1,234,567,890") == 1234567890.0
        assert clean_val("(1.234.567)") == -1234567.0
        assert clean_val("(500,000)") == -500000.0
        assert clean_val("-") == 0.0
        assert clean_val("—") == 0.0
        assert clean_val(" - ") == 0.0

        # 2. Invalid inputs must raise ValueError
        invalid_inputs = ["", "   ", "nan", "NaN", "None", "null", "n/a", None, "abc", "Chưa có số liệu"]
        for inv in invalid_inputs:
            with pytest.raises(ValueError):
                clean_val(inv)

    def test_extract_value_hierarchical_row_traversal(self):
        """Verify extract_value falls back to child row when parent row has all NaNs."""
        df = pd.DataFrame({
            "0": ["1. Tiền và tương đương tiền", "Tiền mặt tại quỹ", "Tiền gửi ngân hàng"],
            "1": [None, "50.000.000", "150.000.000"],
            "2": [None, "40.000.000", "120.000.000"],
        })
        # Row 0 has all NaNs in numeric columns
        row_0 = df.iloc[0]
        val = extract_value(row_0, preferred_col="1", _df=df, _row_idx=0)
        # Should extract from row 1 (child row)
        assert val == 50000000.0, f"Expected 50000000.0 from child row, got {val}"

    def test_ast_sandbox_security_attacks(self):
        """Verify AST sandbox strictly blocks all dangerous modules, functions, and attack vectors."""
        attack_payloads = [
            "import os; os.system('whoami')",
            "import sys; sys.exit(0)",
            "import subprocess; subprocess.run(['ls'])",
            "import socket; s = socket.socket()",
            "import shutil; shutil.rmtree('.')",
            "from os import path",
            "from pathlib import Path",
            "eval('1 + 1')",
            "exec('x = 2')",
            "open('test.txt', 'w')",
            "globals()['__builtins__']",
            "locals()",
            "__import__('os')",
            "breakpoint()",
        ]
        for payload in attack_payloads:
            with pytest.raises(SecurityError, match=r"forbidden"):
                validate_ast(payload)

    def test_executor_node_end_to_end_safe_execution(self):
        """Verify executor_node executes valid Pandas code and captures structured output."""
        df_sample = pd.DataFrame({
            "0": ["Doanh thu bán hàng", "Lợi nhuận gộp", "Lợi nhuận sau thuế"],
            "2022": ["1.000.000", "400.000", "200.000"],
            "2021": ["800.000", "300.000", "150.000"],
        })
        # Save temporary CSV to test execution
        temp_csv = REPO_ROOT / ".agents" / "challenger_r2" / "temp_test_table.csv"
        df_sample.to_csv(temp_csv, index=False)

        try:
            code = (
                f"df = pd.read_csv(r'{temp_csv.as_posix()}')\n"
                f"row = df[df['0'].str.contains('Lợi nhuận sau thuế')].iloc[0]\n"
                f"result = extract_value(row, preferred_col='2022')\n"
            )
            state = {
                "generated_code": code,
                "discovered_tables": [{"csv_path": temp_csv.as_posix()}],
                "node_latencies": {},
            }
            res = executor_node(state)
            assert res["status"] == "success", f"Executor failed: {res.get('error_traceback')}"
            assert res["execution_result"]["data"] == 200000.0
        finally:
            if temp_csv.exists():
                temp_csv.unlink()
