"""Adversarial stress test harness for Node 1 (Query Parser & Entity Extraction).
Executes empirical verification against pipeline/src/nodes/query_parser.py
"""

import sys
import os
from pathlib import Path

# Add project root to sys.path
repo_root = Path("d:/hobby_project/cocopila/r2AI_2026")
sys.path.insert(0, str(repo_root))

from pipeline.src.nodes.query_parser import (
    _normalize_company_name,
    _clean_financial_content,
    _fallback_parse_query,
    NEGATIVE_BLOCKLIST,
    ALIAS_TICKER_MAP,
    _get_stock_mappings,
)


def run_tests():
    passed = 0
    failed = 0
    total = 0
    results = []

    def check(test_group: str, case_name: str, actual: any, expected: any, condition=None):
        nonlocal passed, failed, total
        total += 1
        if condition is not None:
            ok = bool(condition(actual, expected))
        else:
            ok = (actual == expected)
        
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        
        results.append({
            "group": test_group,
            "case": case_name,
            "actual": actual,
            "expected": expected,
            "status": status
        })
        print(f"[{status}] {test_group} :: {case_name} -> Actual: {actual!r}, Expected: {expected!r}")

    print("=" * 80)
    print("STARTING ADVERSARIAL SUITE 1: NEGATIVE_BLOCKLIST STRESS & FALSE POSITIVE PREVENTION")
    print("=" * 80)
    
    # 1. Blocklisted terms should NEVER be resolved as ticker when given as company_input
    for term in sorted(NEGATIVE_BLOCKLIST):
        query = f"Doanh thu thuần của {term} trong năm 2022 là bao nhiêu?"
        res = _normalize_company_name(term, query)
        check("Negative Blocklist", f"company_input='{term}'", res, "", condition=lambda a, e: a != term or a == "")

    # 2. Blocklisted terms in query with no real company
    false_positives = [
        ("CTCP", "Lãi gộp của CTCP năm 2021 là bao nhiêu?"),
        ("TMCP", "Tổng tài sản của ngân hàng TMCP năm 2020?"),
        ("TẬP ĐOÀN", "Lợi nhuận sau thuế của Tập đoàn năm 2023?"),
        ("TCTD", "Chi phí trích lập dự phòng rủi ro của TCTD năm 2022?"),
        ("TNDN", "Thuế TNDN hoãn lại năm 2021 là bao nhiêu?"),
        ("GTGT", "Thuế GTGT được khấu trừ cuối năm 2020?"),
        ("VAMC", "Mệnh giá trái phiếu đặc biệt VAMC năm 2019?"),
        ("BCTC", "Theo BCTC năm 2022 chi phí lãi vay là bao nhiêu?"),
        ("VND", "Doanh thu 500 tỷ VND năm 2021?"),
        ("USD", "Tiền gửi ngoại tệ USD năm 2020?"),
        ("HOSE", "Cổ phiếu niêm yết trên HOSE năm 2021?"),
        ("HNX", "Chỉ số HNX năm 2022?"),
        ("TSCĐ", "Nguyên giá TSCĐ hữu hình năm 2023?"),
        ("SXKD", "Chi phí SXKD dở dang năm 2021?"),
    ]
    for term, q in false_positives:
        res = _normalize_company_name("", q)
        check("False Positive Query", f"query containing '{term}' without ticker", res, "")

    print("\n" + "=" * 80)
    print("STARTING ADVERSARIAL SUITE 2: PARENTHESIZED TICKER PRECEDENCE")
    print("=" * 80)

    paren_cases = [
        ("Vietjet (VJC)", "Lãi tiền gửi năm 2021 của Vietjet (VJC) là bao nhiêu triệu đồng?", "VJC"),
        ("Đức Long Gia Lai (DLG)", "Lãi vay phải trả của CTCP Tập đoàn Đức Long Gia Lai (DLG) cuối năm 2023 là bao nhiêu?", "DLG"),
        ("Đèo Cả (HHV)", "Tổng tài sản của Công ty Cổ phần Hạ tầng Giao thông Đèo Cả (HHV) năm 2022?", "HHV"),
        ("Địa ốc No Va (NVL)", "Nợ ngắn hạn của Địa ốc No Va (NVL) năm 2021?", "NVL"),
        ("Chứng khoán FPT (FTS)", "Doanh thu môi giới của CTCP Chứng khoán FPT (FTS) năm 2020?", "FTS"),
        ("Sacombank (STB)", "Lợi nhuận trước thuế của Sacombank (STB) năm 2023?", "STB"),
        ("LowerCase paren (vjc)", "Doanh thu thuần của Vietjet (vjc) năm 2021?", "VJC"),
        ("LowerCase paren (nvl)", "Hàng tồn kho của No Va (nvl) năm 2020?", "NVL"),
    ]
    for name, q, expected in paren_cases:
        res = _normalize_company_name("", q)
        check("Parentheses Precedence", name, res, expected)

    print("\n" + "=" * 80)
    print("STARTING ADVERSARIAL SUITE 3: AMBIGUOUS CORPORATE NAMES & TICKERS")
    print("=" * 80)

    ambiguous_cases = [
        # FPT ecosystem
        ("CTCP Chứng khoán FPT", "Doanh thu hoạt động của CTCP Chứng khoán FPT năm 2021", "FTS"),
        ("Chứng khoán FPT", "Chi phí của Chứng khoán FPT năm 2020 là bao nhiêu?", "FTS"),
        ("FPT Telecom", "Doanh thu thuần của Viễn thông FPT (FPT Telecom) năm 2022", "FOX"),
        ("Viễn thông FPT", "Lợi nhuận của Viễn thông FPT năm 2021", "FOX"),
        ("Tập đoàn FPT", "Doanh thu hợp nhất của Tập đoàn FPT năm 2023", "FPT"),
        ("CTCP FPT", "Lợi nhuận trước thuế của CTCP FPT năm 2022", "FPT"),
        ("FPT standalone", "Doanh thu FPT năm 2021 là bao nhiêu?", "FPT"),
        
        # Masan ecosystem
        ("Masan Group", "Doanh thu của Tập đoàn Masan năm 2022", "MSN"),
        ("Masan Consumer", "Lợi nhuận của Masan Consumer năm 2021", "MCH"),
        ("Hàng tiêu dùng Masan", "Doanh thu thuần Hàng tiêu dùng Masan năm 2023", "MCH"),
        ("Masan MEATLife", "Doanh thu Masan MEATLife năm 2022", "MML"),
        ("Masan High-Tech", "Tài sản của Masan High-Tech Materials năm 2020", "MSR"),

        # Gelex ecosystem
        ("Tập đoàn Gelex", "Doanh thu thuần của Tập đoàn Gelex năm 2022", "GEX"),
        ("Gelex Electric", "Lợi nhuận của Gelex Electric năm 2021", "GEE"),
        ("Điện lực Gelex", "Chi phí của Điện lực Gelex năm 2023", "GEE"),

        # Đất Xanh ecosystem
        ("Bất động sản Đất Xanh", "Doanh thu của Bất động sản Đất Xanh năm 2022", "DXS"),
        ("Tập đoàn Đất Xanh", "Lợi nhuận của Đất Xanh năm 2021", "DXG"),

        # HAGL ecosystem
        ("Hoàng Anh Gia Lai", "Nợ vay của Hoàng Anh Gia Lai năm 2021", "HAG"),
        ("HAGL", "Lợi nhuận của HAGL năm 2022", "HAG"),
        ("HAGL Agrico", "Doanh thu thuần của HAGL Agrico năm 2021", "HNG"),
        ("Nông nghiệp Quốc tế HAGL", "Tài sản của Nông nghiệp Quốc tế Hoàng Anh Gia Lai năm 2020", "HNG"),

        # Novaland / No Va
        ("Địa ốc No Va", "Phải thu ngắn hạn của Địa ốc No Va năm 2021", "NVL"),
        ("CTCP Tập đoàn Đầu tư Địa ốc No Va", "Tổng phải thu ngắn hạn của CTCP Tập đoàn Đầu tư Địa ốc No Va đến 31/12/2016", "NVL"),
        ("Novaland", "Lãi vay của Novaland năm 2022", "NVL"),
        ("Nova", "Doanh thu của Nova năm 2020", "NVL"),

        # Đèo Cả
        ("Đèo Cả", "Doanh thu BOT của Đèo Cả năm 2022", "HHV"),
        ("Giao thông Đèo Cả", "Vốn chủ sở hữu của Giao thông Đèo Cả năm 2021", "HHV"),
        ("Hạ tầng giao thông Đèo Cả", "Tổng tỷ lệ quyền biểu quyết của CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023", "HHV"),

        # Đức Long Gia Lai
        ("Đức Long Gia Lai", "Nợ ngắn hạn của Đức Long Gia Lai năm 2022", "DLG"),
        ("CTCP Tập đoàn Đức Long Gia Lai", "Lãi vay phải trả của CTCP Tập đoàn Đức Long Gia Lai năm 2023", "DLG"),

        # Vinamilk
        ("Vinamilk", "Doanh thu sữa của Vinamilk năm 2022", "VNM"),
        ("Sữa Việt Nam", "Lợi nhuận sau thuế của CTCP Sữa Việt Nam năm 2021", "VNM"),

        # Petrolimex / BSR / PV Gas / PV Power
        ("Petrolimex", "Doanh thu của Petrolimex năm 2022", "PLX"),
        ("Xăng dầu Việt Nam", "Tổng tài sản của Tập đoàn Xăng dầu Việt Nam năm 2021", "PLX"),
        ("Lọc dầu Bình Sơn", "Lợi nhuận của Lọc dầu Bình Sơn năm 2022", "BSR"),
        ("Bình Sơn", "Doanh thu của Bình Sơn năm 2021", "BSR"),
        ("PV Gas", "Doanh thu PV Gas năm 2022", "GAS"),
        ("Khí Việt Nam", "Lợi nhuận Tổng Công ty Khí Việt Nam năm 2021", "GAS"),
        ("PV Power", "Sản lượng điện của PV Power năm 2022", "POW"),
        ("Điện lực Dầu khí", "Doanh thu Điện lực Dầu khí năm 2021", "POW"),

        # Banking
        ("Vietcombank", "Lãi thuần Vietcombank năm 2022", "VCB"),
        ("Ngoại thương Việt Nam", "Ngân hàng TMCP Ngoại thương Việt Nam năm 2021", "VCB"),
        ("Vietinbank", "Thu nhập lãi của Vietinbank năm 2022", "CTG"),
        ("Công thương Việt Nam", "Ngân hàng TMCP Công thương Việt Nam năm 2021", "CTG"),
        ("BIDV", "Tổng tài sản BIDV năm 2022", "BID"),
        ("Đầu tư và Phát triển Việt Nam", "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam năm 2021", "BID"),
        ("MBBank", "Lợi nhuận MBBank năm 2022", "MBB"),
        ("Ngân hàng Quân đội", "Dư nợ tín dụng Ngân hàng Quân đội năm 2021", "MBB"),
        ("Eximbank", "Tổng quỹ lương năm 2022 của công ty mẹ EIB", "EIB"),
        ("Xuất nhập khẩu Việt Nam", "Ngân hàng TMCP Xuất nhập khẩu Việt Nam năm 2021", "EIB"),
        ("Sacombank", "Doanh thu Ngân hàng TMCP Sài Gòn Thương Tín năm 2020", "STB"),
    ]
    for name, q, expected in ambiguous_cases:
        res = _normalize_company_name("", q)
        check("Ambiguity Resolution", name, res, expected)

    print("\n" + "=" * 80)
    print("STARTING ADVERSARIAL SUITE 4: LOWERCASE & CASING ROBUSTNESS")
    print("=" * 80)

    casing_cases = [
        ("novaland lowercase", "doanh thu thuần của novaland năm 2021", "NVL"),
        ("NOVALAND uppercase", "DOANH THU THUẦN CỦA NOVALAND NĂM 2021", "NVL"),
        ("vinamilk mixed", "Lợi Nhuận Của VinaMilk Năm 2022", "VNM"),
        ("đèo cả lowercase", "vốn chủ sở hữu của đèo cả năm 2023", "HHV"),
        ("ĐÈO CẢ uppercase", "VỐN CHỦ SỞ HỮU CỦA ĐÈO CẢ NĂM 2023", "HHV"),
        ("đức long gia lai lowercase", "nợ vay của đức long gia lai năm 2022", "DLG"),
        ("vietjet lowercase", "chi phí nhiên liệu của vietjet năm 2021", "VJC"),
        ("masan lowercase", "doanh thu của masan năm 2022", "MSN"),
        ("chứng khoán fpt lowercase", "chi phí hoa hồng của chứng khoán fpt năm 2021", "FTS"),
        ("eximbank lowercase", "quỹ lương của eximbank năm 2022", "EIB"),
    ]
    for name, q, expected in casing_cases:
        res = _normalize_company_name("", q)
        check("Casing Robustness", name, res, expected)

    print("\n" + "=" * 80)
    print("STARTING ADVERSARIAL SUITE 5: FINANCIAL CONTENT CLEANING (_clean_financial_content)")
    print("=" * 80)

    clean_cases = [
        # Prefix tests
        ("Prefix 'tốc độ tăng trưởng %'", "tốc độ tăng trưởng % doanh thu thuần", "doanh thu thuần"),
        ("Prefix 'tốc độ tăng trưởng'", "tốc độ tăng trưởng lợi nhuận sau thuế", "lợi nhuận sau thuế"),
        ("Prefix 'tăng trưởng %'", "tăng trưởng % tổng tài sản", "tổng tài sản"),
        ("Prefix 'tăng trưởng'", "tăng trưởng vốn chủ sở hữu", "vốn chủ sở hữu"),
        ("Prefix 'tỷ lệ tăng trưởng'", "tỷ lệ tăng trưởng nợ phải trả", "nợ phải trả"),
        ("Prefix 'mức biến động'", "mức biến động chi phí tài chính", "chi phí tài chính"),
        ("Prefix 'chênh lệch'", "chênh lệch lợi nhuận gộp", "lợi nhuận gộp"),
        ("Prefix 'so sánh'", "so sánh doanh thu thuần", "doanh thu thuần"),
        ("Prefix 'tính tổng'", "tính tổng các khoản nợ ngắn hạn", "các khoản nợ ngắn hạn"),
        ("Prefix 'trích xuất'", "trích xuất lãi tiền gửi", "lãi tiền gửi"),
        ("Prefix 'cho biết'", "cho biết chi phí quản lý doanh nghiệp", "chi phí quản lý doanh nghiệp"),
        ("Prefix 'số dư'", "số dư tiền và tương đương tiền", "tiền và tương đương tiền"),
        ("Prefix 'tổng số'", "tổng số nhân viên", "nhân viên"),
        ("Prefix 'tổng giá trị'", "tổng giá trị hàng tồn kho", "hàng tồn kho"),
        ("Prefix 'khoản'", "khoản phải thu khách hàng", "phải thu khách hàng"),
        ("Prefix 'giá trị còn lại của'", "giá trị còn lại của tài sản cố định", "tài sản cố định"),
        
        # Suffix tests
        ("Suffix 'là bao nhiêu?'", "doanh thu thuần là bao nhiêu?", "doanh thu thuần"),
        ("Suffix 'là bao nhiêu'", "lợi nhuận sau thuế là bao nhiêu", "lợi nhuận sau thuế"),
        ("Suffix 'bao nhiêu?'", "chi phí bán hàng bao nhiêu?", "chi phí bán hàng"),
        ("Suffix 'bao nhiêu'", "chi phí quản lý bao nhiêu", "chi phí quản lý"),
        ("Suffix 'thay đổi như thế nào?'", "vốn chủ sở hữu thay đổi như thế nào?", "vốn chủ sở hữu"),
        ("Suffix 'như thế nào?'", "doanh thu tài chính như thế nào?", "doanh thu tài chính"),
        ("Suffix 'như thế nào'", "nợ dài hạn như thế nào", "nợ dài hạn"),

        # Combined Prefix + Suffix + Whitespace
        ("Combined 1", "  Cho biết tổng giá trị còn lại của chi phí trả trước dài hạn là bao nhiêu?  ", "chi phí trả trước dài hạn"),
        ("Combined 2", "\ttốc độ tăng trưởng % doanh thu thuần thay đổi như thế nào?\n", "doanh thu thuần"),
        ("Combined 3", "Trích xuất khoản phải thu ngắn hạn khác bao nhiêu?", "phải thu ngắn hạn khác"),
        ("Combined 4", "Tính tổng số dư tiền gửi ngân hàng là bao nhiêu?", "tiền gửi ngân hàng"),

        # Non-stripped legitimate financial phrases (should be preserved intact)
        ("Preserve legitimate 'Tổng lợi nhuận'", "Tổng lợi nhuận trước thuế", "Tổng lợi nhuận trước thuế"),
        ("Preserve legitimate 'Tổng tài sản'", "Tổng tài sản", "Tổng tài sản"),
        ("Preserve legitimate 'Tổng nợ phải trả'", "Tổng nợ phải trả", "Tổng nợ phải trả"),
        ("Preserve legitimate 'Phải thu khác'", "Phải thu khác", "Phải thu khác"),
        ("Preserve legitimate 'Lãi tiền gửi'", "Lãi tiền gửi", "Lãi tiền gửi"),
    ]
    for name, input_str, expected in clean_cases:
        res = _clean_financial_content(input_str)
        check("Financial Cleaner", name, res, expected)

    print("\n" + "=" * 80)
    print("STARTING ADVERSARIAL SUITE 6: FALLBACK QUERY PARSER (_fallback_parse_query)")
    print("=" * 80)

    fallback_cases = [
        (
            "Range year query",
            "Tốc độ tăng trưởng doanh thu thuần của CTCP Sữa Việt Nam từ năm 2021 đến năm 2023",
            {"ticker": "VNM", "thao_tac": "so_sanh", "so_nam": ["2021", "2022", "2023"]}
        ),
        (
            "Single year extraction",
            "Lãi tiền gửi năm 2021 của Vietjet (VJC) là bao nhiêu?",
            {"ticker": "VJC", "thao_tac": "trich_xuat", "so_nam": ["2021"]}
        ),
        (
            "Novaland complex query",
            "Tổng phải thu ngắn hạn khác của CTCP Tập đoàn Đầu tư Địa ốc No Va năm 2016",
            {"ticker": "NVL", "thao_tac": "trich_xuat", "so_nam": ["2016"]}
        ),
        (
            "Đèo Cả voting ratio",
            "Tổng tỷ lệ quyền biểu quyết của CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023",
            {"ticker": "HHV", "thao_tac": "trich_xuat", "so_nam": ["2023"]}
        ),
        (
            "Đức Long Gia Lai interest payable",
            "Lãi vay phải trả của CTCP Tập đoàn Đức Long Gia Lai cuối năm 2023",
            {"ticker": "DLG", "thao_tac": "trich_xuat", "so_nam": ["2023"]}
        ),
        (
            "FPT Securities salary expense",
            "Chi phí lương và các khoản khác theo lương của CTCP Chứng khoán FPT năm 2021",
            {"ticker": "FTS", "thao_tac": "trich_xuat", "so_nam": ["2021"]}
        ),
    ]
    for name, q, expected_dict in fallback_cases:
        res = _fallback_parse_query(q)
        is_ok = True
        for k, v in expected_dict.items():
            if res.get(k) != v:
                is_ok = False
                break
        check("Fallback Parser", name, {k: res.get(k) for k in expected_dict}, expected_dict)

    print("\n" + "=" * 80)
    print("STARTING ADVERSARIAL SUITE 7: EXTREME EDGE CASES")
    print("=" * 80)

    edge_cases = [
        ("Empty string query", "", "", ""),
        ("Whitespace query", "   \t\n  ", "", ""),
        ("Numeric only query", "12345 67890 2021", "", ""),
        ("Special characters only", "!@#$%^&*()_+{}[]:;<>?,./", "", ""),
        ("Only blocklisted words", "CTCP TMCP TẬP ĐOÀN CÔNG TY BCTC VND USD", "", ""),
        ("Ticker as substring in regular word", "Tăng trưởng doanh thu", "", ""),
    ]
    for name, q, comp_in, expected in edge_cases:
        res = _normalize_company_name(comp_in, q)
        check("Extreme Edge Cases", name, res, expected)

    print("\n" + "=" * 80)
    print(f"SUMMARY: Total: {total}, Passed: {passed}, Failed: {failed}, Pass Rate: {passed/total*100:.2f}%")
    print("=" * 80)
    return passed, failed, total, results


if __name__ == "__main__":
    passed, failed, total, results = run_tests()
    if failed > 0:
        sys.exit(1)
    sys.exit(0)
