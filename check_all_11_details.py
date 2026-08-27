import os, sys
import pandas as pd
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from pipeline.src.nodes.data_discovery import clean_query_content
import rag_module.search_engine as se
se._ensure_resources()

questions = [
    {"id": 2, "ticker": "ACB", "year": "2022", "user_query": "Số dư cho vay khách hàng ngành Thương mại của công ty mẹ Ngân hàng TMCP Á Châu (ACB) cuối năm 2022 là bao nhiêu triệu đồng?", "noi_dung": "Số dư cho vay khách hàng ngành Thương mại"},
    {"id": 8, "ticker": "FTS", "year": "2021", "user_query": "Chi phí lương và các khoản khác theo lương của công ty mẹ CTCP Chứng khoán FPT trong năm 2021 là bao nhiêu tỷ đồng?", "noi_dung": "Chi phí lương và các khoản khác theo lương"},
    {"id": 11, "ticker": "BID", "year": "2016", "user_query": "Số dư tiền gửi tại các TCTD khác cuối năm 2016 của Ngân hàng TMCP Đầu tư và Phát triển Việt Nam (BID) là bao nhiêu triệu đồng?", "noi_dung": "Số dư tiền gửi tại các TCTD khác"},
    {"id": 16, "ticker": "CEO", "year": "2025", "user_query": "Số dư vay ngắn hạn của công ty mẹ CEO cuối năm 2025 là bao nhiêu tỷ đồng?", "noi_dung": "Số dư vay ngắn hạn"},
    {"id": 19, "ticker": "HHV", "year": "2023", "user_query": "Tổng tỷ lệ quyền biểu quyết của công ty mẹ CTCP Đầu tư Hạ tầng Giao thông Đèo Cả năm 2023 là bao nhiêu phần trăm?", "noi_dung": "Tổng tỷ lệ quyền biểu quyết"},
    {"id": 20, "ticker": "GVR", "year": "2019", "user_query": "Tỷ lệ biểu quyết của Xí nghiệp Liên doanh Visorutex của công ty mẹ GVR đến ngày 31/12/2019 là bao nhiêu %?", "noi_dung": "Tỷ lệ biểu quyết của Xí nghiệp Liên doanh Visorutex"},
    {"id": 27, "ticker": "DLG", "year": "2024", "user_query": "Lưu chuyển tiền thuần từ hoạt động kinh doanh của công ty mẹ CTCP Tập đoàn Đức Long Gia Lai (DLG) năm 2024 là bao nhiêu triệu đồng?", "noi_dung": "Lưu chuyển tiền thuần từ hoạt động kinh doanh"},
    {"id": 29, "ticker": "OGC", "year": "2019", "user_query": "Tổng số trả trước cho người bán dài hạn của OGC đến ngày 31 tháng 12 năm 2019 là bao nhiêu triệu đồng?", "noi_dung": "Tổng số trả trước cho người bán dài hạn"},
    {"id": 35, "ticker": "BVH", "year": "2015", "user_query": "Khoản phải thu từ Bảo Việt Nhân thọ của công ty mẹ Tập đoàn Bảo Việt (BVH) cuối năm 2015 là bao nhiêu triệu đồng?", "noi_dung": "Khoản phải thu từ Bảo Việt Nhân thọ"},
    {"id": 36, "ticker": "VRE", "year": "2016", "user_query": "Giá trị còn lại của lợi thế thương mại (tổng cộng) của CTCP Vincom Retail (VRE) là bao nhiêu triệu đồng đến ngày 31/12/2016?", "noi_dung": "Giá trị còn lại của lợi thế thương mại (tổng cộng)"},
    {"id": 37, "ticker": "GEX", "year": "2018", "user_query": "Tổng cam kết cho thuê hoạt động của công ty mẹ CTCP Tập đoàn GELEX (GEX) đến ngày 31/12/2018 là bao nhiêu tỷ đồng?", "noi_dung": "Tổng cam kết cho thuê hoạt động"},
]

for q in questions:
    print("\n" + "="*80)
    print(f"TEST Q{q['id']}: {q['ticker']} ({q['year']})")
    print(f"User Query: {q['user_query']}")
    cleaned = clean_query_content(q["noi_dung"], q["ticker"], [q["year"]])
    print(f"Cleaned content: '{cleaned}' (gốc: '{q['noi_dung']}')")
    
    # Check what search_by_company_and_content returns
    results = se.search_by_company_and_content(
        company_name=q["ticker"],
        content=cleaned,
        year=q["year"],
        report_type=None,
        top_k=5
    )
    print(f"Search results ({len(results)} found):")
    for i, r in enumerate(results[:5], 1):
        p = Path(r.get("csv_path", "")).name
        tb = r.get("Ten_Bang", "")
        rrf = r.get("rrf_score", 0.0)
        sample = r.get("matched_sample", "")
        print(f"  #{i} RRF={rrf:.4f} | File: {p} | Table: {tb} | Sample: '{sample}'")
