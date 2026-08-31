"""Node 3: Schema Mapper Node.
Duyệt từng cột trong bảng dữ liệu thực tế để xác thực dữ liệu:
Workflow:
1. Truy vấn các cột từ bảng (Data Table)
2. Xác nhận: Số hàng có dữ liệu > Số hàng không có dữ liệu trong cột
3. Lựa chọn các cột thỏa mãn là Useful Columns
4. Tìm tên cột thực sự (Header Resolution khi tên cột là số/unnamed)
5. Đưa ra mô tả ngữ nghĩa cho cột dựa vào tên và nội dung
6. Xác định động cột nhãn (label_column) và cột giá trị (value_column)
7. Xuất và in ra Output JSON chuẩn phục vụ kiểm thử.
"""

import re
import time
import json
import yaml
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from thefuzz import process, fuzz
from langchain_core.messages import SystemMessage, HumanMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm
from pipeline.src.utils.json_repair import safe_parse_json


# Các cột metadata/thông tin chung ở đầu file CSV cần bỏ qua khi phân tích dữ liệu bảng
METADATA_HEADER_COLUMNS = [
    "Ma_Doanh_Nghiep", "Ten_Doanh_Nghiep", "Nam_Tai_Chinh",
    "Loai_Bao_Cao", "Ten_Bang", "Don_Vi_Tinh", "Tep_Nguon"
]


AUXILIARY_COL_REGEX = re.compile(
    r"^(stt|số\s*tt|số\s*thứ\s*tự|sothutu|mã\s*số|mãsố|mã|thuyết\s*minh|thuyếtminh|ghi\s*chú|note|code|ms|tm|[a-dA-D]|cột_\d+|unnamed.*)$",
    re.IGNORECASE,
)

_AUXILIARY_CODE_COLUMNS = {
    "mã số", "mãsố", "mã", "thuyết minh", "thuyếtminh", "stt", "số tt", "số thứ tự", "sothutu",
    "ghi chú", "note", "code", "ms", "tm", "a", "b", "c", "d", "cột_0", "cột 0", "cot_0", "cot 0", "unnamed: 0"
}


def _is_cell_empty(val: Any) -> bool:
    """Kiểm tra xem một ô có bị rỗng, null hoặc chứa ký tự không có dữ liệu hay không."""
    if val is None or pd.isna(val):
        return True
    s = str(val).strip()
    return s.lower() in {"", "nan", "none", "null", "n/a", "na", "-", "—", "--", "nil"}


def _is_numeric_value(val: Any) -> bool:
    """Kiểm tra xem một ô có chứa giá trị số (kể cả số âm trong ngoặc, dấu phân cách, %, $, VND) hay không."""
    if _is_cell_empty(val):
        return False
    s = str(val).strip()
    s = re.sub(r"(?i)\b(?:vnd|đồng|dong|usd)\b", "", s).strip()
    s = s.replace(",", "").replace(".", "").replace(" ", "").replace("%", "").replace("$", "").replace("VND", "").replace("vnd", "")
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1]
    if s.startswith("-") or s.startswith("+"):
        s = s[1:]
    return s.isdigit() and len(s) > 0


def _resolve_column_header(df: pd.DataFrame, col: str) -> str:
    """Xác định tên thực sự của cột.

    - Nếu tên cột là năm 4 chữ số (ví dụ: '2018', '2017') -> giữ nguyên.
    - Nếu tên cột là chữ có nghĩa -> giữ nguyên.
    - Nếu tên cột là số thứ tự positional ('0', '1', '2',...) hoặc 'Unnamed:' -> quét các hàng đầu tiên để tìm tiêu đề chữ.
    """
    raw_name = str(col).strip()

    # 1. Nếu là năm 4 chữ số (19xx, 20xx) -> là header hợp lệ, giữ nguyên!
    if re.match(r"^(19|20)\d{2}$", raw_name):
        return raw_name

    # 2. Nếu là tên rõ ràng (chứa chữ và không phải 'Unnamed:' hoặc positional số) -> giữ nguyên!
    if not raw_name.isdigit() and not raw_name.startswith("Unnamed:"):
        return raw_name

    # 3. Quét các hàng header đầu tiên để tìm chuỗi văn bản tiêu đề
    for row_idx in range(min(5, len(df))):
        cell_val = df.iloc[row_idx][col]
        if not _is_cell_empty(cell_val):
            cell_str = str(cell_val).strip()
            if not _is_numeric_value(cell_str):
                has_letters = bool(re.search(r"[a-zA-ZÀ-ỹ]", cell_str))
                has_date_format = bool(re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", cell_str))
                if has_letters or has_date_format:
                    return cell_str

    if raw_name == "0":
        return "Chỉ tiêu"

    return raw_name


def _clean_table_name(table_name: str) -> str:
    """Làm sạch tên bảng báo cáo tài chính để phục vụ việc mô tả cột."""
    if not table_name:
        return "Báo cáo tài chính"
    text = str(table_name).strip()
    text = re.sub(r"^(\d+\s*[\.\)]|\w+\s*[\.\)]|\*\))\s*", "", text)
    patterns_to_remove = [
        r"Mẫu\s+B\s*\d+\s*-\s*DN.*",
        r"Ban\s+hành\s+theo\s+Thông\s+tư.*",
        r"Cho\s+năm\s+tài\s+chính\s+kết\s+thúc.*",
        r"cho\s+năm\s+kết\s+thúc\s+ngày.*",
        r"kết\s+thúc\s+ngày\s+\d+.*",
        r"vào\s+ngày\s+\d+.*",
        r"Tại\s+ngày\s+\d+.*",
        r"\(?\s*tiếp\s+theo.*",
        r"_\s*Phải\s+trả.*",
    ]
    for p in patterns_to_remove:
        text = re.sub(p, "", text, flags=re.IGNORECASE).strip()
    text = text.strip(" :,-_.\t\n()[]{}")
    return text if len(text) >= 3 else table_name.strip()


def _extract_unit_from_name(name: str, default_unit: Optional[str] = None) -> Optional[str]:
    """Phát hiện đơn vị tính/đo lường từ tên cột hoặc metadata để làm rõ trong mô tả."""
    lower = name.lower()
    if "triệu" in lower or "trieu" in lower or "million" in lower:
        return "triệu đồng"
    if "tỷ" in lower or "ty" in lower or "billion" in lower:
        return "tỷ đồng"
    if "nghìn" in lower or "ngàn" in lower or "thousand" in lower:
        return "nghìn đồng"
    if "usd" in lower or "$" in lower:
        return "USD"
    if "vnd" in lower or "đồng" in lower:
        return "VND"
    if default_unit:
        d_lower = str(default_unit).lower().strip()
        if d_lower and d_lower not in {"vnd", "đồng", "dong", "none", "nan", "-"}:
            return str(default_unit).strip()
    return None


def _build_default_column_description(
    table_name: str, 
    col_name: str, 
    raw_column: str,
    don_vi_tinh: Optional[str] = None,
) -> str:
    """Tạo mô tả chi tiết mặc định kết hợp ngữ cảnh tên bảng, thời kỳ và đơn vị tính của cột."""
    clean_tbl = _clean_table_name(table_name)
    name_check = f"{col_name} {raw_column}".strip()
    unit = _extract_unit_from_name(name_check, don_vi_tinh)
    unit_suffix = f" (đơn vị đo: {unit})" if unit else ""

    # 1. Định dạng ngày cụ thể (ví dụ: 31/12/2024, 01/01/2023)
    date_match = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", name_check)
    if date_match:
        date_str = date_match.group(0)
        return f"{clean_tbl} của các nội dung tại ngày {date_str}{unit_suffix}"

    # 2. Tìm năm 4 chữ số trong tên cột (ví dụ: '2018', '2017', 'Năm 2020Triệu', '2021Triệu', '2020 VND')
    year_match = re.search(r"(19\d{2}|20\d{2})", name_check)
    if year_match:
        year = year_match.group(1)
        return f"{clean_tbl} của các nội dung trong năm {year}{unit_suffix}"

    # 3. Các từ khóa chỉ kỳ / thời điểm tương đối
    lower_check = name_check.lower()
    if "năm nay" in lower_check or "kỳ này" in lower_check:
        return f"{clean_tbl} của các nội dung trong năm nay / kỳ hiện tại{unit_suffix}"
    if "năm trước" in lower_check or "kỳ trước" in lower_check:
        return f"{clean_tbl} của các nội dung trong năm trước / kỳ trước{unit_suffix}"
    if "cuối năm" in lower_check or "cuối kỳ" in lower_check:
        return f"{clean_tbl} của các nội dung vào thời điểm cuối năm / cuối kỳ{unit_suffix}"
    if "đầu năm" in lower_check or "đầu kỳ" in lower_check:
        return f"{clean_tbl} của các nội dung vào thời điểm đầu năm / đầu kỳ{unit_suffix}"

    # 4. Fallback chung
    display_col = col_name if col_name and not col_name.isdigit() else raw_column
    return f"{clean_tbl} - chỉ tiêu {display_col}{unit_suffix}"


def _get_columns_from_table(table: Dict[str, Any]) -> List[str]:
    """Extract column names from a discovered table by reading its CSV file."""
    csv_path = table.get("csv_path", "")
    if not csv_path:
        return []

    try:
        df = pd.read_csv(csv_path, nrows=2)
        return list(df.columns)
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────

def _is_code_or_index_column(series: pd.Series, col_name: str = "") -> bool:
    """Kiểm tra xem một cột có phải STT, mã số, thuyết minh, float index hoặc chỉ số phân mục hay không."""
    raw_col_lower = str(col_name).strip().lower()
    if AUXILIARY_COL_REGEX.match(raw_col_lower) or raw_col_lower in _AUXILIARY_CODE_COLUMNS:
        return True

    non_empty = [str(x).strip() for x in series if not _is_cell_empty(x)]
    if not non_empty:
        return False

    total_chars = sum(len(x) for x in non_empty)
    letter_count = sum(sum(1 for ch in x if ch.isalpha()) for x in non_empty)
    avg_len = total_chars / len(non_empty)
    letter_ratio = (letter_count / total_chars) if total_chars > 0 else 0.0

    # Quy tắc 1: Text density check - Chuỗi cực ngắn (<= 4.0 ký tự) và ít chữ cái (< 0.35) -> Cột chỉ số / STT
    if avg_len <= 4.0 and letter_ratio < 0.35:
        return True

    # Quy tắc 2: Khớp các mẫu mã số, số thứ tự, float index (\d+\.0+), số La Mã, phân mục
    index_token_pattern = re.compile(
        r"^(?:[0-9]{1,4}[a-z]?|[IVXLCDM]+|[A-Z]|\(\w+\)|\d+\.\d{1,2}|\d+[\.\)]|\d+\.\d+\.\d+)$",
        re.IGNORECASE,
    )
    index_matches = sum(
        1 for s in non_empty
        if (len(s) <= 4 and not _is_numeric_value(s)) or
           (len(s) <= 5 and bool(re.match(r"^\d+\.0+$", s))) or
           (len(s) <= 6 and bool(index_token_pattern.match(s)))
    )
    return (index_matches / len(non_empty)) >= 0.5


def _extract_useful_columns(
    df: pd.DataFrame,
    label_col: Optional[str] = None,
    metadata_cols: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Duyệt từng cột một trong bảng và xác nhận:
    Số hàng có dữ liệu > Số hàng không có dữ liệu.

    Returns:
        List[Dict] thông tin các useful columns.
    """
    metadata_set = metadata_cols or set(METADATA_HEADER_COLUMNS)
    useful = []
    total_rows = len(df)
    candidate_cols = [c for c in df.columns if c not in metadata_set]


    for col in candidate_cols:
        series = df[col]
        data_rows = 0
        empty_rows = 0
        numeric_count = 0
        sample_values = []
        non_empty_values = []

        for val in series:
            if _is_cell_empty(val):
                empty_rows += 1
            else:
                data_rows += 1
                s_val = str(val).strip()
                non_empty_values.append(s_val)
                if _is_numeric_value(val):
                    numeric_count += 1
                if len(sample_values) < 3:
                    sample_values.append(s_val)

        # Điều kiện bắt buộc: Số hàng có dữ liệu > Số hàng không có dữ liệu
        is_useful = data_rows > empty_rows

        if is_useful:

            # Step 4: Tìm tên cột thực tế
            resolved_name = _resolve_column_header(df, col)

            total_chars = sum(len(x) for x in non_empty_values)
            letter_count = sum(sum(1 for ch in x if ch.isalpha()) for x in non_empty_values)
            avg_str_len = (total_chars / len(non_empty_values)) if non_empty_values else 0.0
            letter_ratio = (letter_count / total_chars) if total_chars > 0 else 0.0

            # Phân loại auxiliary code column (Mã số, Thuyết minh, STT, Roman numerals, short index codes, float index)
            is_aux_code = (
                bool(AUXILIARY_COL_REGEX.match(resolved_name.strip()))
                or bool(AUXILIARY_COL_REGEX.match(str(col).strip()))
                or resolved_name.strip().lower() in _AUXILIARY_CODE_COLUMNS 
                or str(col).strip().lower() in _AUXILIARY_CODE_COLUMNS
                or _is_code_or_index_column(series, col_name=str(col))
                or _is_code_or_index_column(series, col_name=resolved_name)
            )

            if is_aux_code:
                data_type = "text"
            else:
                data_type = "numeric" if (data_rows > 0 and numeric_count / data_rows >= 0.5) else "text"

            useful.append({
                "raw_column": str(col),
                "column_name": resolved_name,
                "column_index": list(df.columns).index(col),
                "data_type": data_type,
                "is_aux_code": is_aux_code,
                "avg_str_len": avg_str_len,
                "letter_ratio": letter_ratio,
                "data_rows_count": data_rows,
                "empty_rows_count": empty_rows,
                "sample_values": sample_values,
                "column_description": "",
            })
        else:
            pass

    return useful


def _find_label_column(
    useful_columns: List[Dict[str, Any]],
    columns: Optional[List[str]] = None
) -> Optional[str]:
    """Xác định cột nhãn (chứa tên chỉ tiêu tài chính) một cách động:
    Chọn cột dạng 'text' có độ dài chuỗi trung bình lớn nhất và mật độ chữ cao nhất.
    """
    if not useful_columns:
        if columns:
            non_meta = [c for c in columns if c not in METADATA_HEADER_COLUMNS]
            return non_meta[0] if non_meta else columns[0]
        return None

    # 1. Ứng viên ưu tiên: Cột text không phải auxiliary code
    primary_text = [
        c for c in useful_columns 
        if c.get("data_type") == "text" 
        and not c.get("is_aux_code", False)
        and not AUXILIARY_COL_REGEX.match(str(c.get("column_name", "")).strip())
        and not AUXILIARY_COL_REGEX.match(str(c.get("raw_column", "")).strip())
        and str(c.get("column_name", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
        and str(c.get("raw_column", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
    ]

    if primary_text:
        # Chọn cột có letter_ratio >= 0.40 và avg_str_len lớn nhất
        high_letter_candidates = [c for c in primary_text if c.get("letter_ratio", 0.0) >= 0.40]
        if high_letter_candidates:
            return max(high_letter_candidates, key=lambda c: c.get("avg_str_len", 0.0))["raw_column"]
        return max(primary_text, key=lambda c: c.get("avg_str_len", 0.0))["raw_column"]

    # 2. Fallback sang bất kỳ cột text nào có avg_str_len lớn nhất
    text_cols = [c for c in useful_columns if c.get("data_type") == "text"]
    if text_cols:
        return max(text_cols, key=lambda c: c.get("avg_str_len", 0.0))["raw_column"]

    # 3. Fallback sang cột đầu tiên trong useful_columns
    return useful_columns[0]["raw_column"]


def _find_value_column(
    useful_columns: List[Dict[str, Any]],
    label_col: Optional[str] = None,
    tieu_chi_phu: Optional[str] = None,
    columns: Optional[List[str]] = None,
) -> Optional[str]:
    """Xác định cột giá trị một cách động dựa trên tiêu chí phụ, cột số và cột phần trăm (%)."""
    if not useful_columns:
        if columns:
            candidates = [
                c for c in columns
                if c not in METADATA_HEADER_COLUMNS
                and c != label_col
                and not AUXILIARY_COL_REGEX.match(str(c).strip())
                and str(c).strip().lower() not in _AUXILIARY_CODE_COLUMNS
            ]
            return candidates[0] if candidates else (columns[0] if columns else None)
        return None

    # Lọc bỏ cột nhãn và tất cả các cột mã số / auxiliary code / single letter
    value_candidates = [
        c for c in useful_columns
        if c.get("raw_column") != label_col
        and not c.get("is_aux_code", False)
        and not AUXILIARY_COL_REGEX.match(str(c.get("column_name", "")).strip())
        and not AUXILIARY_COL_REGEX.match(str(c.get("raw_column", "")).strip())
        and str(c.get("column_name", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
        and str(c.get("raw_column", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
    ]
    if not value_candidates:
        value_candidates = [c for c in useful_columns if c.get("raw_column") != label_col]
    if not value_candidates:
        value_candidates = useful_columns

    if tieu_chi_phu and value_candidates:
        clean_tcp = str(tieu_chi_phu).strip().lower()

        # 1. Exact or substring match TRÊN TÊN CỘT THỰC TẾ (TUYỆT ĐỐI KHÔNG match trên c_desc)
        for uc in value_candidates:
            c_name = str(uc.get("column_name", "")).lower()
            r_name = str(uc.get("raw_column", "")).lower()
            if clean_tcp == c_name or clean_tcp == r_name:
                return uc["raw_column"]
            if len(clean_tcp) >= 3 and (clean_tcp in c_name or clean_tcp in r_name):
                return uc["raw_column"]

        # 2. Khớp chuyên biệt cho truy vấn tỷ lệ / phần trăm (%)
        if any(pct_kw in clean_tcp for pct_kw in ["%", "phần trăm", "tỷ lệ", "ty le", "biểu quyết", "sở hữu", "lãi suất"]):
            for uc in value_candidates:
                c_name = str(uc.get("column_name", "")).lower()
                r_name = str(uc.get("raw_column", "")).lower()
                if any(k in c_name or k in r_name for k in ["%", "tỷ lệ", "ty le", "biểu quyết", "sở hữu", "lãi suất"]):
                    return uc["raw_column"]

        # 3. Fuzzy match tiêu chí phụ với các tên cột ứng viên
        candidate_names = [str(uc.get("column_name", "")) for uc in value_candidates]
        if candidate_names:
            match, score = process.extractOne(
                clean_tcp, candidate_names, scorer=fuzz.token_set_ratio
            )
            if score >= 65:
                for uc in value_candidates:
                    if str(uc.get("column_name", "")) == match:
                        return uc["raw_column"]

    # Ưu tiên các cột numeric KHÔNG phải là cột mã số / thuyết minh / số lượng cổ phiếu
    primary_numeric = [
        c for c in value_candidates 
        if c.get("data_type") == "numeric" 
        and not c.get("is_aux_code", False)
        and not AUXILIARY_COL_REGEX.match(str(c.get("column_name", "")).strip())
        and not AUXILIARY_COL_REGEX.match(str(c.get("raw_column", "")).strip())
        and str(c.get("column_name", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
        and str(c.get("raw_column", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
    ]
    if primary_numeric:
        def _col_priority(col_dict):
            raw_c = str(col_dict.get("raw_column", "")).lower()
            name_c = str(col_dict.get("column_name", "")).lower()
            check = f"{raw_c} {name_c}"
            # Cột số tiền hiện tại / năm nay / cuối năm: Ưu tiên cao nhất (0)
            if any(kw in check for kw in ["năm nay", "kỳ này", "cuối năm", "cuối kỳ", "31/12", "số tiền", "giá trị", "thực hiện", "thành tiền"]):
                return 0
            # Cột số lượng / số cổ phiếu: ưu tiên thấp hơn số tiền (3)
            if any(kw in check for kw in ["số cổ phiếu", "số lượng", "cổ phần", "cp"]):
                return 3
            # Cột năm trước / kỳ trước / đầu năm: ưu tiên sau năm nay (2)
            if any(kw in check for kw in ["năm trước", "kỳ trước", "đầu năm", "đầu kỳ", "01/01"]):
                return 2
            # Các cột số liệu thông thường khác: (1)
            return 1

        sorted_numeric = sorted(primary_numeric, key=_col_priority)
        return sorted_numeric[0]["raw_column"]

    # Default: Chọn cột dạng 'numeric' đầu tiên trong các cột ứng viên
    numeric_candidates = [c for c in value_candidates if c.get("data_type") == "numeric"]
    if numeric_candidates:
        return numeric_candidates[0]["raw_column"]

    return value_candidates[0]["raw_column"]


def _extract_sub_sections(
    df: pd.DataFrame,
    label_col: Optional[str],
    metadata_cols: Set[str],
) -> List[Dict[str, Any]]:
    """Phát hiện các danh mục con (sub-sections) trong bảng tài chính."""
    if not label_col or label_col not in df.columns:
        return []

    value_cols = [c for c in df.columns if c not in metadata_cols and c != label_col]
    if not value_cols:
        return []

    sections = []
    section_header_rows = []

    prev_was_empty = False
    for idx in range(len(df)):
        label_val = df.iloc[idx][label_col]
        is_label_empty = pd.isna(label_val) or str(label_val).strip() == ""

        if not is_label_empty and prev_was_empty:
            label_text = str(label_val).strip()

            total_value = None
            for vc in value_cols:
                cell = df.iloc[idx][vc]
                if pd.notna(cell):
                    try:
                        cell_str = str(cell).strip().replace(",", "")
                        if cell_str.startswith("(") and cell_str.endswith(")"):
                            cell_str = "-" + cell_str[1:-1].strip()
                        total_value = float(cell_str)
                        break
                    except (ValueError, TypeError):
                        continue

            section_header_rows.append({
                "row_idx": idx,
                "section_name": label_text,
                "total_value": total_value,
            })

        prev_was_empty = is_label_empty

    for i, header in enumerate(section_header_rows):
        start = header["row_idx"] + 1
        if i + 1 < len(section_header_rows):
            end = section_header_rows[i + 1]["row_idx"] - 1
        else:
            end = len(df) - 1

        while end >= start:
            val = df.iloc[end][label_col]
            if pd.isna(val) or str(val).strip() == "":
                end -= 1
            else:
                break

        if start <= end:
            sections.append({
                "section_name": header["section_name"],
                "range": [start, end],
                "total_value": header["total_value"],
            })

    return sections


def _enrich_column_descriptions(
    cfg: Config,
    useful_columns: List[Dict[str, Any]],
    table_name: str,
    don_vi_tinh: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Gán mô tả cấu trúc mặc định cho các cột hữu ích KHÔNG gọi LLM (xử lý tức thì)."""
    if not useful_columns:
        return useful_columns

    for col in useful_columns:
        c_name = col.get("column_name", "")
        r_name = col.get("raw_column", "")
        if not col.get("column_description"):
            col["column_description"] = _build_default_column_description(table_name, c_name, r_name, don_vi_tinh)

    return useful_columns


def analyze_single_table_schema(
    table_dict: Dict[str, Any],
    tieu_chi_phu: Optional[str] = None,
    cfg: Optional[Config] = None,
) -> Dict[str, Any]:
    """Phân tích schema, label_column, value_column cho một bảng bất kỳ."""
    cfg = cfg or default_config
    csv_path = table_dict.get("csv_path", "")
    if not csv_path or not Path(csv_path).exists():
        return {"column_mapping": {}, "schema": {}}

    metadata_set = set(METADATA_HEADER_COLUMNS)
    table_name = table_dict.get("Ten_Bang", Path(csv_path).stem)
    try:
        df_full = pd.read_csv(csv_path)
        raw_columns = list(df_full.columns)
        all_useful = _extract_useful_columns(df_full, metadata_cols=metadata_set)
        label_col = _find_label_column(all_useful, raw_columns)
        useful_cols = [
            c for c in all_useful
            if c.get("data_type") == "numeric"
            and not c.get("is_aux_code", False)
            and not AUXILIARY_COL_REGEX.match(str(c.get("column_name", "")).strip())
            and not AUXILIARY_COL_REGEX.match(str(c.get("raw_column", "")).strip())
            and str(c.get("column_name", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
            and str(c.get("raw_column", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
        ]
        if not useful_cols:
            useful_cols = [c for c in all_useful if c.get("raw_column") != label_col]
        value_col = _find_value_column(useful_cols, label_col, tieu_chi_phu, raw_columns)
        label_col_idx = raw_columns.index(label_col) if (label_col and label_col in raw_columns) else 0
        value_col_idx = raw_columns.index(value_col) if (value_col and value_col in raw_columns) else 1
        return {
            "column_mapping": {
                "label_column": label_col,
                "value_column": value_col,
                "label_column_idx": label_col_idx,
                "value_column_idx": value_col_idx,
                "all_columns": str(raw_columns),
                "all_useful_columns": [c["raw_column"] for c in useful_cols],
            },
            "schema": {
                "useful_columns": useful_cols,
                "sub_sections": _extract_sub_sections(df_full, label_col, metadata_set),
            }
        }
    except Exception as e:
        return {"column_mapping": {}, "schema": {}}


def map_multi_tables(
    tables: List[Dict[str, Any]],
    parsed_query: Dict[str, Any],
    cfg: Optional[Config] = None,
) -> List[Dict[str, Any]]:
    """Enrich candidate tables with schema mappings, label/value columns, and table summaries.

    Args:
        tables: List of candidate table dicts (each having 'csv_path', 'Ten_Bang', etc.)
        parsed_query: Parsed query dictionary (containing 'tieu_chi_phu', 'noi_dung', etc.)
        cfg: Configuration instance

    Returns:
        Enriched list of table dicts, each updated with:
        - 'column_mapping': {'label_column': ..., 'value_column': ..., 'all_columns': ..., 'all_useful_columns': ...}
        - 'schema': {'useful_columns': [...], 'sub_sections': [...]}
        - 'useful_columns': List of useful column names or dicts
        - 'label_column': str
        - 'value_column': str
        - 'table_summary': str
    """
    cfg = cfg or default_config
    tieu_chi_phu = parsed_query.get("tieu_chi_phu") if isinstance(parsed_query, dict) else None
    enriched_tables = []

    for tbl in tables:
        tbl_copy = dict(tbl)
        tbl_res = analyze_single_table_schema(tbl_copy, tieu_chi_phu=tieu_chi_phu, cfg=cfg)
        col_mapping = tbl_res.get("column_mapping", {})
        tbl_schema = tbl_res.get("schema", {})

        label_col = col_mapping.get("label_column", "")
        value_col = col_mapping.get("value_column", "")
        useful_cols = tbl_schema.get("useful_columns", [])
        csv_p = tbl_copy.get("csv_path", "")
        table_name = tbl_copy.get("Ten_Bang", Path(csv_p).stem if csv_p else "")

        tbl_copy["column_mapping"] = col_mapping
        tbl_copy["schema"] = tbl_schema
        tbl_copy["label_column"] = label_col
        tbl_copy["value_column"] = value_col
        tbl_copy["useful_columns"] = useful_cols
        tbl_copy["table_summary"] = f"Bảng: {table_name} | Cột nhãn: {label_col} | Cột giá trị: {value_col}"

        enriched_tables.append(tbl_copy)

    return enriched_tables


def schema_mapper_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 3: Schema Mapper Node.

    Thực hiện quy trình:
    1. Truy vấn các cột từ bảng
    2. Xác nhận số hàng có dữ liệu > số hàng không có dữ liệu
    3. Lựa chọn các cột useful (chỉ giữ lại cột numeric)
    4. Tìm tên cột thực sự
    5. Đưa ra mô tả cho từng cột kết hợp tên bảng, thời kỳ và đơn vị tính
    6. Xác định động label_column và value_column
    7. In Output JSON ra console phục vụ kiểm thử.
    """
    cfg = cfg or default_config
    start_time = time.time()

    parsed_query = state.get("parsed_query", {})
    discovered_tables = state.get("discovered_tables", [])
    top_candidates = state.get("top_k_candidates", discovered_tables[:5])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    # pass
    # pass
    # pass

    column_mapping: Dict[str, Any] = {}
    schema: Dict[str, Any] = {"useful_columns": [], "sub_sections": []}

    if not discovered_tables:
        print(f"   ⚠️ [Schema Mapper] Không có bảng dữ liệu đầu vào để ánh xạ.")
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["schema_mapper"] = round(latency, 3)
        return {
            **state,
            "column_mapping": {},
            "schema": schema,
            "top_k_candidates": [],
            "status": "pending",
            "node_latencies": node_latencies,
        }

    first_table = discovered_tables[0]
    csv_path = first_table.get("csv_path", "")
    table_name = first_table.get("Ten_Bang", Path(csv_path).stem if csv_path else "unknown")
    metadata_set = set(METADATA_HEADER_COLUMNS)

    try:
        df_full = pd.read_csv(csv_path)
        raw_columns = list(df_full.columns)

        # Trích xuất đơn vị tính từ metadata nếu có
        don_vi_tinh = None
        if "Don_Vi_Tinh" in df_full.columns and len(df_full) > 0:
            first_dvt = df_full.iloc[0]["Don_Vi_Tinh"]
            if not _is_cell_empty(first_dvt):
                don_vi_tinh = str(first_dvt).strip()

        # ── 1, 2, 3, 4. Trích xuất useful_columns qua kiểm tra dữ liệu từng cột ──
        all_useful_detected = _extract_useful_columns(df_full, metadata_cols=metadata_set)

        # ── 5. Xác định động label_column và value_column (Không dùng danh sách ưu tiên) ──
        label_col = _find_label_column(all_useful_detected, raw_columns)

        # Chỉ giữ lại các cột numeric trong useful_columns (loại bỏ các cột auxiliary code và text)
        useful_columns = [
            c for c in all_useful_detected 
            if c.get("data_type") == "numeric" 
            and not c.get("is_aux_code", False)
            and not AUXILIARY_COL_REGEX.match(str(c.get("column_name", "")).strip())
            and not AUXILIARY_COL_REGEX.match(str(c.get("raw_column", "")).strip())
            and str(c.get("column_name", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
            and str(c.get("raw_column", "")).strip().lower() not in _AUXILIARY_CODE_COLUMNS
        ]
        if not useful_columns:
            useful_columns = [c for c in all_useful_detected if c.get("raw_column") != label_col]

        value_col = _find_value_column(useful_columns, label_col, tieu_chi_phu, raw_columns)

        label_col_idx = raw_columns.index(label_col) if (label_col and label_col in raw_columns) else 0
        value_col_idx = raw_columns.index(value_col) if (value_col and value_col in raw_columns) else 1

        column_mapping = {
            "label_column": label_col,
            "value_column": value_col,
            "label_column_idx": label_col_idx,
            "value_column_idx": value_col_idx,
            "all_columns": str(raw_columns),
            "all_useful_columns": [c["raw_column"] for c in useful_columns],
        }


        # ── 6. Phân tích Sub-sections ──
        sub_sections = _extract_sub_sections(df_full, label_col, metadata_set)
        if sub_sections:
            print(f"   📂 Phát hiện {len(sub_sections)} danh mục con (Sub-sections).")

        # ── 7. Sinh mô tả ngữ nghĩa cho các cột bằng LLM ──
        useful_columns = _enrich_column_descriptions(cfg, useful_columns, table_name, don_vi_tinh=don_vi_tinh)

        schema = {
            "useful_columns": useful_columns,
            "sub_sections": sub_sections,
        }

        # Ánh xạ schema cho toàn bộ danh sách candidate tables qua map_multi_tables
        top_candidates = map_multi_tables(top_candidates, parsed_query, cfg=cfg)

        # ── 8. In Output JSON phục vụ kiểm thử ──
        output_json = {
            "column_mapping": column_mapping,
            "schema": schema,
        }

        print(f"\n" + "-" * 65)
        # pass
        print("-" * 65)

    except Exception as e:
        print(f"   ⚠️ [Schema Mapper] Lỗi trong quá trình phân tích schema: {e}")
        import traceback
        traceback.print_exc()

    latency = time.time() - start_time
    node_latencies = state.get("node_latencies", {})
    node_latencies["schema_mapper"] = round(latency, 3)

    print(f"✅ [Node 3: Schema Mapper] Hoàn thành trong {node_latencies['schema_mapper']}s")
    print(f"=" * 65 + "\n")

    return {
        **state,
        "column_mapping": column_mapping,
        "schema": schema,
        "top_k_candidates": top_candidates,
        "status": "pending",
        "node_latencies": node_latencies,
    }
