"""Verification script for Milestone 1: Node 1 Query Parser & Entity Extraction Hotfix.
"""

import sys
from pathlib import Path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import re
import yaml
from pipeline.src.nodes.query_parser import (
    NEGATIVE_BLOCKLIST,
    ALIAS_TICKER_MAP,
    _normalize_company_name,
    _clean_financial_content,
    _fallback_parse_query,
    parse_query_node,
    load_query_parser_prompt,
    _get_stock_mappings,
)
from pipeline.src.config import Config


def test_blocklist():
    print("\n--- Testing NEGATIVE_BLOCKLIST ---")
    required_terms = [
        "CTCP", "TMCP", "TẬP ĐOÀN", "CÔNG TY", "NGÂN HÀNG", "TỔNG CÔNG TY",
        "TNHH", "CP", "DN", "JSC", "CORP", "CORPORATION", "GROUP", "BANK",
        "HOLDINGS", "SECURITIES", "CHỨNG KHOÁN", "BẢO HIỂM", "BẤT ĐỘNG SẢN",
        "BÁO CÁO", "TÀI CHÍNH", "BCTC", "TCTD", "TNDN", "TNCN", "GTGT", "VAMC",
        "CHKQT", "CHK", "HĐQT", "HDQT", "TSCĐ", "TSCD", "SXKD", "XDCB",
        "VIỆT NAM", "QUỐC TẾ", "ĐẦU TƯ", "THƯƠNG MẠI", "XÂY DỰNG", "NĂNG LƯỢNG",
        "VND", "USD", "EUR", "HOSE", "HNX", "UPCOM", "VN30", "VNINDEX"
    ]
    for term in required_terms:
        assert term in NEGATIVE_BLOCKLIST, f"Missing {term} in NEGATIVE_BLOCKLIST"
        # Test normalization with blocklisted input
        res = _normalize_company_name(term, f"Báo cáo của {term} năm 2022")
        assert res != term, f"Blocklisted term {term} was returned as ticker: {res}"
    print(f"✅ NEGATIVE_BLOCKLIST passed all {len(required_terms)} terms!")


def test_alias_map_and_normalization():
    print("\n--- Testing ALIAS_TICKER_MAP & Entity Resolution Precedence ---")
    test_cases = [
        # (company_input, query, expected_ticker, description)
        ("CTCP", "Tổng phải thu ngắn hạn khác của công ty mẹ CTCP Tập đoàn Đầu tư Địa ốc No Va đến ngày 31 tháng 12 năm 2016 là bao nhiêu triệu đồng?", "NVL", "Q28 (Novaland)"),
        ("", "Tổng quỹ lương năm 2022 của công ty mẹ EIB là bao nhiêu triệu đồng?", "EIB", "Q42 (Eximbank)"),
        ("", "Số dư phải thu theo tiến độ kế hoạch hợp đồng của FPT đến ngày 31/12/2025 là bao nhiêu tỷ đồng?", "FPT", "Q32 (FPT Corp)"),
        ("CTCP", "Giá gốc chứng khoán kinh doanh của CTCP Tập đoàn Đức Long Gia Lai cuối năm 2016 là bao nhiêu tỷ đồng?", "DLG", "Q41 (Đức Long GL)"),
        ("CTCP", "Tổng tỷ lệ quyền biểu quyết của công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023 là bao nhiêu phần trăm?", "HHV", "Q19 (Đèo Cả)"),
        ("", "Chi phí lương và các khoản khác theo lương của công ty mẹ CTCP Chứng khoán FPT trong năm 2021 là bao nhiêu tỷ đồng?", "FTS", "Q4 (FPT Securities vs FPT Corp)"),
        ("", "Lãi tiền gửi năm 2021 của Vietjet (VJC) là bao nhiêu triệu đồng?", "VJC", "Explicit parentheses (VJC)"),
        ("", "Doanh thu bán lẻ của Thế giới di động năm 2023", "MWG", "Thế giới di động -> MWG"),
        ("", "Sản lượng thép của Hòa Phát năm 2022", "HPG", "Hòa Phát -> HPG"),
        ("", "Doanh thu sữa của Vinamilk năm 2021", "VNM", "Vinamilk -> VNM"),
        ("", "Lợi nhuận của Vietcombank năm 2023", "VCB", "Vietcombank -> VCB"),
        ("", "Tổng tài sản của Sacombank năm 2020", "STB", "Sacombank -> STB"),
        ("", "Doanh thu thuần của Xăng dầu Việt Nam (Petrolimex) năm 2021", "PLX", "Petrolimex -> PLX"),
        ("", "Chi phí quản lý của Tập đoàn Bảo Việt năm 2015", "BVH", "Bảo Việt -> BVH"),
        ("", "Doanh thu dịch vụ của Hàng hải Việt Nam năm 2022", "MSB", "MSB brand"),
        ("", "Lãi vay của SAM Holdings năm 2023", "SAM", "SAM Holdings"),
        ("", "Doanh thu của Gỗ Trường Thành năm 2022", "TTF", "Gỗ Trường Thành"),
        ("", "Doanh thu Vinatex năm 2021", "VGT", "Vinatex -> VGT"),
    ]

    for comp_in, query, expected, desc in test_cases:
        res = _normalize_company_name(comp_in, query)
        assert res == expected, f"Failed {desc}: expected '{expected}', got '{res}'"
        print(f"  ✓ {desc}: resolved -> '{res}'")

    print(f"✅ All {len(test_cases)} entity resolution cases passed!")


def test_clean_financial_content():
    print("\n--- Testing _clean_financial_content ---")
    test_cases = [
        ("tốc độ tăng trưởng % doanh thu thuần", "doanh thu thuần"),
        ("tốc độ tăng trưởng lợi nhuận sau thuế", "lợi nhuận sau thuế"),
        ("tăng trưởng % vốn chủ sở hữu", "vốn chủ sở hữu"),
        ("tăng trưởng tổng tài sản", "tổng tài sản"),
        ("mức biến động chi phí tài chính", "chi phí tài chính"),
        ("chênh lệch doanh thu hoạt động tài chính", "doanh thu hoạt động tài chính"),
        ("so sánh lãi thuần từ hoạt động dịch vụ", "lãi thuần từ hoạt động dịch vụ"),
        ("tính tổng chi phí quản lý doanh nghiệp", "chi phí quản lý doanh nghiệp"),
        ("trích xuất chi phí bán hàng", "chi phí bán hàng"),
        ("cho biết lợi nhuận gộp", "lợi nhuận gộp"),
        ("số dư phải thu theo tiến độ kế hoạch hợp đồng", "phải thu theo tiến độ kế hoạch hợp đồng"),
        ("tổng số lao động", "lao động"),
        ("tổng giá trị hàng tồn kho", "hàng tồn kho"),
        ("khoản phải thu ngắn hạn khác", "phải thu ngắn hạn khác"),
        ("giá trị còn lại của tài sản cố định hữu hình", "tài sản cố định hữu hình"),
        ("Lãi tiền gửi năm 2021 là bao nhiêu?", "Lãi tiền gửi năm 2021"),
        ("Chi phí lãi vay thay đổi như thế nào?", "Chi phí lãi vay"),
        ("doanh thu thuần như thế nào", "doanh thu thuần"),
        ("chi phí bán hàng bao nhiêu", "chi phí bán hàng"),
    ]

    for inp, expected in test_cases:
        res = _clean_financial_content(inp)
        assert res.lower() == expected.lower(), f"Failed for '{inp}': expected '{expected}', got '{res}'"
        print(f"  ✓ '{inp}' -> '{res}'")

    print(f"✅ All {len(test_cases)} content cleaning cases passed!")


def test_fallback_query_parser():
    print("\n--- Testing _fallback_parse_query ---")
    res_q28 = _fallback_parse_query("Tổng phải thu ngắn hạn khác của công ty mẹ CTCP Tập đoàn Đầu tư Địa ốc No Va đến ngày 31 tháng 12 năm 2016 là bao nhiêu triệu đồng?")
    assert res_q28["ticker"] == "NVL", f"Expected NVL, got {res_q28['ticker']}"
    assert res_q28["ten_cong_ty"] == "NVL"
    assert "2016" in res_q28["so_nam"]
    assert res_q28["thao_tac"] == "trich_xuat"

    res_q19 = _fallback_parse_query("Tổng tỷ lệ quyền biểu quyết của công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023 là bao nhiêu phần trăm?")
    assert res_q19["ticker"] == "HHV"
    assert res_q19["ten_cong_ty"] == "HHV"
    assert "2023" in res_q19["so_nam"]

    res_range = _fallback_parse_query("So sánh doanh thu thuần của FPT từ năm 2021 đến năm 2023 là bao nhiêu?")
    assert res_range["ticker"] == "FPT"
    assert res_range["thao_tac"] == "so_sanh"
    assert res_range["so_nam"] == ["2021", "2022", "2023"]

    print("✅ Fallback query parser passed all tests!")


def test_yaml_prompt_loading():
    print("\n--- Testing YAML Prompt Loading ---")
    cfg = Config()
    prompt_data = load_query_parser_prompt(cfg)
    assert "system_prompt" in prompt_data
    assert "json_schema" in prompt_data
    assert "few_shot_examples" in prompt_data
    assert len(prompt_data["few_shot_examples"]) >= 7

    # Verify FTS mapping in few-shots
    fts_example = next((ex for ex in prompt_data["few_shot_examples"] if "Chứng khoán FPT" in ex["user_query"]), None)
    assert fts_example is not None, "Chứng khoán FPT example missing from few_shots"
    assert '"ticker": "FTS"' in fts_example["parsed_output"], f"Expected FTS in few shot, got: {fts_example['parsed_output']}"
    print("✅ YAML Prompt loaded successfully with valid FTS few-shot mapping!")


def test_parse_query_node_integration():
    print("\n--- Testing parse_query_node State Synchronization ---")
    # Test empty query handling
    state_empty = {"user_query": ""}
    out_empty = parse_query_node(state_empty)
    assert out_empty["status"] == "error"
    assert out_empty["error_message"] == "User query is empty."

    # Test parse_query_node fallback path execution (or live)
    state_q28 = {
        "user_query": "Tổng phải thu ngắn hạn khác của công ty mẹ CTCP Tập đoàn Đầu tư Địa ốc No Va đến ngày 31 tháng 12 năm 2016 là bao nhiêu triệu đồng?"
    }
    out_q28 = parse_query_node(state_q28)
    pq_28 = out_q28["parsed_query"]
    assert pq_28["ticker"] == "NVL", f"Expected ticker NVL, got {pq_28.get('ticker')}"
    assert pq_28["ten_cong_ty"] == "NVL", f"Expected ten_cong_ty NVL, got {pq_28.get('ten_cong_ty')}"
    assert "2016" in pq_28["so_nam"]
    print(f"  ✓ Q28 state synchronization verified: ticker={pq_28['ticker']}, ten_cong_ty={pq_28['ten_cong_ty']}")

    state_q19 = {
        "user_query": "Tổng tỷ lệ quyền biểu quyết của công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023 là bao nhiêu phần trăm?"
    }
    out_q19 = parse_query_node(state_q19)
    pq_19 = out_q19["parsed_query"]
    assert pq_19["ticker"] == "HHV", f"Expected ticker HHV, got {pq_19.get('ticker')}"
    assert pq_19["ten_cong_ty"] == "HHV", f"Expected ten_cong_ty HHV, got {pq_19.get('ten_cong_ty')}"
    assert "2023" in pq_19["so_nam"]
    print(f"  ✓ Q19 state synchronization verified: ticker={pq_19['ticker']}, ten_cong_ty={pq_19['ten_cong_ty']}")

    print("✅ parse_query_node state synchronization passed all tests!")


if __name__ == "__main__":
    print("==================================================")
    print("RUNNING NODE 1 COMPREHENSIVE VERIFICATION SUITE")
    print("==================================================")
    test_blocklist()
    test_alias_map_and_normalization()
    test_clean_financial_content()
    test_fallback_query_parser()
    test_yaml_prompt_loading()
    test_parse_query_node_integration()
    print("\n==================================================")
    print("🎉 ALL NODE 1 VERIFICATION TESTS PASSED 100%!")
    print("==================================================")
