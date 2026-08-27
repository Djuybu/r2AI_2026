import sys, os
sys.path.insert(0, os.path.abspath('.'))
import pandas as pd
from pipeline.src.nodes.query_parser import _normalize_company_name, _clean_financial_content, _fallback_parse_query
from pipeline.src.nodes.schema_mapper import _is_code_or_index_column, _find_label_column, _find_value_column, _extract_useful_columns
from pipeline.src.nodes.executor import sanitize_code_str, validate_ast, clean_val, extract_value, SecurityError

print("=== ADVERSARIAL STRESS TEST ===")

# Test 1: Ticker resolution adversarial cases
assert _normalize_company_name("CTCP", "Doanh thu thuần của CTCP Nam Long (NLG) năm 2021") == "NLG"
assert _normalize_company_name("CÔNG TY", "Lợi nhuận của Công ty Cổ phần Sữa Việt Nam năm 2022") == "VNM"
assert _normalize_company_name("TẬP ĐOÀN", "Doanh thu của Tập đoàn Vingroup năm 2023") == "VIC"
assert _normalize_company_name("TỔNG CÔNG TY", "Tổng tài sản của Tổng Công ty Khí Việt Nam (PV GAS)") == "GAS"
assert _normalize_company_name("CTCP", "Không có tên công ty nào ở đây cả") == ""
print("1. Adversarial Ticker Resolution: PASS")

# Test 2: Content cleaning adversarial cases
assert _clean_financial_content("tốc độ tăng trưởng % lợi nhuận gộp là bao nhiêu?") == "lợi nhuận gộp"
assert _clean_financial_content("tính tổng giá trị còn lại của tài sản cố định vô hình thay đổi như thế nào?") == "tài sản cố định vô hình"
assert _clean_financial_content("khoản phải thu ngắn hạn khác bao nhiêu") == "phải thu ngắn hạn khác"
print("2. Adversarial Content Cleaning: PASS")

# Test 3: Schema mapper adversarial tables
df_adversarial = pd.DataFrame({
    "cột_0": ["1.0", "2.0", "3.0", "4.0"], # Float index
    "Thuyết minh": ["I", "II", "III", "IV"], # Roman index
    "Mã số": ["Mã 01", "Mã 02", "Mã 03", "Mã 04"], # Short codes
    "Chỉ tiêu": ["Doanh thu bán hàng và cung cấp dịch vụ", "Các khoản giảm trừ doanh thu", "Doanh thu thuần về bán hàng", "Giá vốn hàng bán"], # Long label
    "Năm 2021": ["100.000", "20.000", "80.000", "50.000"], # Value column
    "Tỷ lệ %": ["10%", "2%", "8%", "5%"], # Percentage column
})

useful = _extract_useful_columns(df_adversarial)
label = _find_label_column(useful)
assert label == "Chỉ tiêu", f"Expected label Chỉ tiêu, got {label}"

val_num = _find_value_column(useful, label_col=label, tieu_chi_phu="VND")
assert val_num == "Năm 2021", f"Expected value Năm 2021, got {val_num}"

val_pct = _find_value_column(useful, label_col=label, tieu_chi_phu="%")
assert val_pct == "Tỷ lệ %", f"Expected value Tỷ lệ %, got {val_pct}"
print("3. Adversarial Schema Mapper Column Selection: PASS")

# Test 4: AST Sanitizer & Sandbox Security
code_attack1 = 'import os; os.system("dir")'
try:
    validate_ast(code_attack1)
    assert False, "Failed to block os import"
except SecurityError:
    pass

code_attack2 = 'eval("1 + 1")'
try:
    validate_ast(code_attack2)
    assert False, "Failed to block eval"
except SecurityError:
    pass

sanitized = sanitize_code_str("df[df['0'].str.contains('abc')]")
assert "df['0'].astype(str).str.contains" in sanitized
print("4. Adversarial AST Security & Sanitizer: PASS")

print("\n>>> ALL ADVERSARIAL STRESS TESTS PASSED EMPIRICALLY! <<<")
