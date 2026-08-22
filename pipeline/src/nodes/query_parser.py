"""Node 1: Query Parser Node.
Phân tích câu hỏi tài chính thành cấu trúc JSON chuẩn.
Output format: ten_cong_ty, so_nam, noi_dung, thao_tac (muc_tieu: trich_xuat | so_sanh), tieu_chi_phu.
Không thực hiện tìm bảng — việc này do Data Discovery xử lý.
"""

import re
import time
import yaml
from typing import Dict, Any, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm
from pipeline.src.utils.json_repair import safe_parse_json


def load_query_parser_prompt(cfg: Config) -> Dict[str, Any]:
    """Load prompt templates and few-shot examples from YAML."""
    prompt_path = cfg.get_prompt_path("query_parser.yaml")
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at: {prompt_path}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _normalize_company_name(company_input: str, user_query: str) -> str:
    """Normalize company name or raw ticker input against rag_module/code_stock.csv map.
    
    Quy tắc:
    1. Scan user_query directly for explicit 3-5 letter uppercase tickers in code_stock.csv.
    2. Scan user_query against company names in code_stock.csv (longest match first).
    3. If company_input provided by LLM is present in user_query, validate and return corresponding ticker.
    4. If company_input is NOT in user_query and no match found, do NOT map to arbitrary tickers (e.g. VNM).
    """
    company_input = company_input.strip() if company_input else ""
    user_query = user_query.strip() if user_query else ""
    q_lower = user_query.lower()

    try:
        from pathlib import Path
        import pandas as pd

        # Tìm đường dẫn tới file code_stock.csv
        possible_paths = [
            Path("rag_module/code_stock.csv"),
            Path("rag_module/ViFinQA/code_stock.csv"),
            Path("/kaggle/working/r2AI_2026/rag_module/code_stock.csv"),
            Path(__file__).resolve().parent.parent.parent / "rag_module" / "code_stock.csv",
            Path(__file__).resolve().parent.parent.parent / "rag_module" / "ViFinQA" / "code_stock.csv",
        ]

        csv_path = None
        for p in possible_paths:
            if p.exists():
                csv_path = p
                break

        name_to_code = []
        all_tickers = set()

        if csv_path:
            df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype=str)
            ticker_col = next((c for c in df.columns if "CK" in c.upper()), df.columns[0])
            name_col = next((c for c in df.columns if "TÊN" in c.upper() or "TEN" in c.upper()), df.columns[1])

            for _, row in df.iterrows():
                code = str(row[ticker_col]).strip().upper() if pd.notna(row[ticker_col]) else ""
                name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
                if code:
                    all_tickers.add(code)
                if code and name:
                    name_to_code.append((name, code))
                    # Thêm các biến thể tên thương hiệu sạch (loại bỏ CTCP, Tập đoàn, Ngân hàng, - CTCP...)
                    clean_name = re.sub(r"\b(CTCP|Tập đoàn|Công ty|Cổ phần|Ngân hàng|TMCP|\-\s*CTCP)\b", "", name, flags=re.IGNORECASE).strip(" -")
                    if clean_name and clean_name.lower() != name.lower() and len(clean_name) >= 3:
                        name_to_code.append((clean_name, code))
        else:
            # Fallback sang search_engine nếu không đọc được file CSV
            from rag_module.search_engine import _ensure_resources, _company_map
            _ensure_resources()
            if _company_map:
                name_to_code = list(_company_map)
                all_tickers = {code.upper() for _, code in _company_map}

        # 1. Tra cứu các mã chứng khoán 3-5 ký tự in hoa xuất hiện trực tiếp trong câu hỏi người dùng
        for w in re.findall(r"\b[A-Za-z]{3,5}\b", user_query):
            if w.upper() in all_tickers:
                return w.upper()

        # 2. Sắp xếp danh sách tên công ty theo độ dài giảm dần (longest-match first) và khớp vào user_query
        name_to_code.sort(key=lambda x: len(x[0]), reverse=True)
        for name, code in name_to_code:
            if len(name) >= 3 and name.lower() in q_lower:
                return code

        # 3. Nếu company_input xuất hiện trong user_query, kiểm tra tên/mã
        if company_input:
            c_upper = company_input.upper()
            if c_upper in all_tickers and c_upper.lower() in q_lower:
                return c_upper
            c_lower = company_input.lower()
            for name, code in name_to_code:
                if len(name) >= 3 and (name.lower() in c_lower or c_lower in name.lower()):
                    if name.lower() in q_lower or code.lower() in q_lower:
                        return code

    except Exception as e:
        print(f"⚠️ [Query Parser] Stock code normalization error: {e}")

    # Nếu company_input do LLM sinh ra KHÔNG hề có trong user_query -> Bỏ qua hallucination
    if company_input and company_input.lower() not in q_lower and company_input.upper() not in user_query:
        return ""

    return company_input



def _clean_financial_content(text: str) -> str:
    """Clean action phrases, measurement prefixes, and query noise from financial content string."""
    if not text:
        return ""

    cleaned = text.strip()

    # Strip leading action/measurement phrases
    strip_patterns = [
        r"^tốc\s+độ\s+tăng\s+trưởng\s*%\s*",
        r"^tốc\s+độ\s+tăng\s+trưởng\s*",
        r"^tăng\s+trưởng\s*%\s*",
        r"^tăng\s+trưởng\s*",
        r"^tỷ\s+lệ\s+tăng\s+trưởng\s*",
        r"^mức\s+biến\s+động\s*",
        r"^chênh\s+lệch\s*",
        r"^so\s+sánh\s*",
        r"^tính\s+tổng\s*",
        r"^trích\s+xuất\s*",
        r"^cho\s+biết\s*",
    ]

    for pattern in strip_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Strip trailing question/noise phrases
    trailing_patterns = [
        r"\s*là\s+bao\s+nhiêu\??$",
        r"\s*bao\s+nhiêu\??$",
        r"\s*thay\s+đổi\s+như\s+thế\s+nào\??$",
        r"\s*như\s+thế\s+nào\??$",
    ]
    for pattern in trailing_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


def _fallback_parse_query(user_query: str) -> Dict[str, Any]:
    """Fallback rule-based parser when LLM is unreachable."""
    q = user_query.strip()
    
    # Check for range pattern e.g. "từ năm 2021 đến năm 2023" or "từ 2021 đến 2023"
    range_match = re.search(r"từ\s*(?:năm\s*)?(\d{4})\s*đến\s*(?:năm\s*)?(\d{4})", q, re.IGNORECASE)
    if range_match:
        y1, y2 = int(range_match.group(1)), int(range_match.group(2))
        start_y, end_y = min(y1, y2), max(y1, y2)
        years = [str(y) for y in range(start_y, end_y + 1)]
        tieu_chi_phu = range_match.group(0)
    else:
        years = re.findall(r"\b(20\d{2})\b", q)
        tieu_chi_phu = None

    q_lower = q.lower()
    if "so sánh" in q_lower or "thay đổi" in q_lower or "tăng trưởng" in q_lower or "từ năm" in q_lower or "đến năm" in q_lower:
        thao_tac = "so_sanh"
    else:
        thao_tac = "trich_xuat"

    m_ticker = re.search(r"\b([A-Z]{3,5})\b", q)
    company = m_ticker.group(1) if m_ticker else ""
    company = _normalize_company_name(company, user_query)

    clean_content = re.sub(r"\b(20\d{2})\b", "", q)
    if company:
        clean_content = re.sub(rf"\b{company}\b", "", clean_content, flags=re.IGNORECASE)
    
    # Remove growth/comparison stop words
    stop_phrases = [
        "tốc độ tăng trưởng %", "tốc độ tăng trưởng", "tăng trưởng %", "tăng trưởng",
        "so sánh", "từ năm", "đến năm", "của", "năm", "báo cáo", "tài chính",
        "cho", "là bao nhiêu", "bao nhiêu"
    ]
    for word in stop_phrases:
        clean_content = re.sub(rf"\b{re.escape(word)}\b", "", clean_content, flags=re.IGNORECASE)
    
    clean_content = _clean_financial_content(clean_content or q)

    return {
        "ticker": company,
        "ten_cong_ty": company,
        "year": ", ".join(years),
        "so_nam": years,
        "metric": clean_content or q,
        "noi_dung": clean_content or q,
        "thao_tac": thao_tac,
        "muc_tieu": thao_tac,
        "tieu_chi_phu": tieu_chi_phu,
    }


def parse_query_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 1: Phân tích câu hỏi thành cấu trúc truy vấn.

    Trích xuất: ten_cong_ty, so_nam, noi_dung, thao_tac (muc_tieu: trich_xuat | so_sanh), tieu_chi_phu.
    KHÔNG tìm bảng — Data Discovery sẽ xử lý.

    Args:
        state: Current AgentState containing 'user_query'
        cfg: Config instance (defaults to global config)

    Returns:
        Updated AgentState with 'parsed_query', 'status', and latency tracking.
    """
    cfg = cfg or default_config
    start_time = time.time()
    user_query = state.get("user_query", "").strip()

    if not user_query:
        return {
            **state,
            "status": "error",
            "error_message": "User query is empty.",
            "parsed_query": {},
        }

    try:
        # Load prompts
        prompt_data = load_query_parser_prompt(cfg)
        system_prompt = prompt_data["system_prompt"]
        json_schema = prompt_data["json_schema"]
        few_shots = prompt_data.get("few_shot_examples", [])

        # Build prompt messages
        prompt_messages = [
            SystemMessage(content=f"{system_prompt}\n\nSchema Yêu cầu:\n{json_schema}")
        ]

        for example in few_shots:
            prompt_messages.append(HumanMessage(content=example["user_query"]))
            prompt_messages.append(SystemMessage(content=example["parsed_output"]))

        prompt_messages.append(HumanMessage(content=f"Câu hỏi: {user_query}"))

        # Call LLM with slight temperature=0.1 to avoid overfitting/copy-pasting examples
        llm = get_llm(cfg=cfg, temperature=0.1)
        response = llm.invoke(prompt_messages)

        raw_content = response.content if isinstance(response.content, str) else str(response.content)

        # Extract and print agent thoughts
        print(f"\n🔍 [Query Parser] Đang phân tích câu hỏi: '{user_query}'")
        think_match = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
        if think_match:
            thought = think_match.group(1).strip()
            indented_thought = thought.replace('\n', '\n  ')
            print(f"💭 [Tư duy - Query Parser]:\n  {indented_thought}")
        else:
            json_start = raw_content.find("{")
            if json_start > 10:
                thought = raw_content[:json_start].strip()
                indented_thought = thought.replace('\n', '\n  ')
                print(f"💭 [Tư duy - Query Parser]:\n  {indented_thought}")

        # Parse output JSON
        parsed_json = safe_parse_json(raw_content)

        # Map strict schema keys {"ticker", "year", "metric"} to state schema keys
        ticker_val = parsed_json.get("ticker") or parsed_json.get("ten_cong_ty") or ""
        metric_val = parsed_json.get("metric") or parsed_json.get("noi_dung") or ""
        year_val = parsed_json.get("year") if "year" in parsed_json else parsed_json.get("so_nam")

        # Fallback year extraction from query if year is None or empty
        if not year_val or year_val is None or str(year_val).strip() in ["None", "null", ""]:
            year_val = re.findall(r"\b(20\d{2})\b", user_query)

        # Ensure so_nam is a list of strings
        if isinstance(year_val, str):
            so_nam_list = [y.strip() for y in year_val.replace(",", " ").split() if y.strip().isdigit()]
            if not so_nam_list:
                so_nam_list = re.findall(r"\b(20\d{2})\b", user_query)
        elif isinstance(year_val, (int, float)):
            so_nam_list = [str(int(year_val))]
        elif isinstance(year_val, list):
            so_nam_list = [str(y).strip() for y in year_val if str(y).strip().isdigit()]
        else:
            so_nam_list = re.findall(r"\b(20\d{2})\b", user_query)

        # Sync keys
        parsed_json["ticker"] = ticker_val
        parsed_json["ten_cong_ty"] = _normalize_company_name(ticker_val, user_query)
        parsed_json["year"] = ", ".join(so_nam_list) if so_nam_list else ""
        parsed_json["so_nam"] = so_nam_list
        parsed_json["metric"] = metric_val
        parsed_json["noi_dung"] = metric_val

        # Ensure minimal structure and sync thao_tac / muc_tieu (only trich_xuat or so_sanh)
        thao_tac = parsed_json.get("thao_tac") or parsed_json.get("muc_tieu") or ("so_sanh" if len(so_nam_list) > 1 or "so sánh" in user_query.lower() or "tăng trưởng" in user_query.lower() else "trich_xuat")
        if thao_tac not in ["trich_xuat", "so_sanh"]:
            thao_tac = "trich_xuat"
        
        parsed_json["thao_tac"] = thao_tac
        parsed_json["muc_tieu"] = thao_tac

        # Clean content only for so_sanh (strip measurement prefixes)
        raw_noi_dung = parsed_json.get("noi_dung", "")
        if thao_tac == "so_sanh":
            parsed_json["noi_dung"] = _clean_financial_content(raw_noi_dung) or raw_noi_dung
            parsed_json["metric"] = parsed_json["noi_dung"]

        if "tieu_chi_phu" not in parsed_json:
            parsed_json["tieu_chi_phu"] = None

        print(
            f"📊 [Kết quả - Query Parser]:\n"
            f"   Công ty: {parsed_json.get('ten_cong_ty')}\n"
            f"   Năm: {parsed_json.get('so_nam')}\n"
            f"   Nội dung: {parsed_json.get('noi_dung')}\n"
            f"   Thao tác: {parsed_json.get('thao_tac')}\n"
            f"   Tiêu chí phụ: {parsed_json.get('tieu_chi_phu')}\n"
        )

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["query_parser"] = round(latency, 3)

        return {
            **state,
            "parsed_query": parsed_json,
            "status": "pending",
            "node_latencies": node_latencies,
        }

    except Exception as e:
        print(f"⚠️ [Query Parser] LLM không phản hồi ({e}). Đang sử dụng Rule-based Fallback Parser...")
        parsed_json = _fallback_parse_query(user_query)

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["query_parser"] = round(latency, 3)

        print(
            f"📊 [Kết quả Fallback - Query Parser]:\n"
            f"   Công ty: {parsed_json.get('ten_cong_ty')}\n"
            f"   Năm: {parsed_json.get('so_nam')}\n"
            f"   Nội dung: {parsed_json.get('noi_dung')}\n"
            f"   Thao tác: {parsed_json.get('thao_tac')}\n"
            f"   Tiêu chí phụ: {parsed_json.get('tieu_chi_phu')}\n"
        )

        return {
            **state,
            "parsed_query": parsed_json,
            "status": "pending",
            "node_latencies": node_latencies,
        }
