"""Detailed test script checking single-pass loop vs multi-pass prefix stripping in _clean_financial_content."""
import sys
from pathlib import Path
repo_root = Path("d:/hobby_project/cocopila/r2AI_2026")
sys.path.insert(0, str(repo_root))

from pipeline.src.nodes.query_parser import _clean_financial_content

tests = [
    "Cho biết tính tổng số dư tiền gửi ngân hàng",
    "Cho biết trích xuất khoản phải thu khách hàng",
    "Trích xuất tổng giá trị hàng tồn kho",
    "Cho biết giá trị còn lại của tài sản cố định",
    "Cho biết số dư tiền và tương đương tiền là bao nhiêu?",
    "Cho biết tổng giá trị còn lại của chi phí trả trước dài hạn là bao nhiêu?",
]

for t in tests:
    res = _clean_financial_content(t)
    print(f"Input:    {t!r}")
    print(f"Cleaned:  {res!r}\n")
