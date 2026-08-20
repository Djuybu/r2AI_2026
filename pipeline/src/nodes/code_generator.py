"""Node 4: Code Generation & Reflection Node.
Sinh code Python/Pandas dựa trên mục tiêu (trich_xuat/tinh_tong/so_sanh),
cột mapping, và bảng dữ liệu đã tìm được.
"""

import re
import time
import yaml
from typing import Dict, Any, Optional, List
from langchain_core.messages import SystemMessage, HumanMessage

from pipeline.src.state import AgentState
from pipeline.src.config import Config, config as default_config
from pipeline.src.llm_provider import get_llm


def load_yaml_prompt(cfg: Config, filename: str) -> Dict[str, Any]:
    """Load prompt template YAML."""
    prompt_path = cfg.get_prompt_path(filename)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at: {prompt_path}")

    with open(prompt_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean_python_code(raw_code: str) -> str:
    """Extract clean Python code from LLM markdown block."""
    if not raw_code:
        return ""

    # Match ```python ... ``` or ``` ... ```
    pattern = r"```(?:python)?\s*\n?(.*?)\n?```"
    matches = re.findall(pattern, raw_code, re.DOTALL)
    if matches:
        return matches[0].strip()

    # If no markdown block, clean trailing quotes
    cleaned = raw_code.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()
    return cleaned


def _build_files_context(
    discovered_tables: List[Dict[str, Any]],
    column_mapping: Dict[str, str],
) -> str:
    """Build context string describing available files for code generation."""
    if not discovered_tables:
        return "Không có bảng dữ liệu."

    lines = []
    for i, tbl in enumerate(discovered_tables):
        csv_path = tbl.get("csv_path", "")
        ten_bang = tbl.get("Ten_Bang", "N/A")
        nam = tbl.get("Nam_Tai_Chinh", "N/A")
        escaped_path = csv_path.replace('\\', '\\\\')
        lines.append(
            f"- File {i+1} (Năm {nam}):\n"
            f"  Đường dẫn: '{escaped_path}'\n"
            f"  Tên bảng: {ten_bang}\n"
        )

    lines.append(f"\nColumn Mapping: {column_mapping}")
    return "\n".join(lines)


def code_generator_node(state: AgentState, cfg: Optional[Config] = None) -> AgentState:
    """LangGraph Node 4: Sinh code Pandas hoặc sửa code lỗi (Reflection Loop).

    Đọc parsed_query format mới (muc_tieu, noi_dung, ten_cong_ty, so_nam, tieu_chi_phu)
    và discovered_tables để sinh code phù hợp.

    Args:
        state: Current AgentState
        cfg: Config instance

    Returns:
        Updated AgentState with 'generated_code'
    """
    cfg = cfg or default_config
    start_time = time.time()

    user_query = state.get("user_query", "")
    parsed_query = state.get("parsed_query", {})
    discovered_tables = state.get("discovered_tables", [])
    column_mapping = state.get("column_mapping", {})
    error_traceback = state.get("error_traceback")
    retry_count = state.get("retry_count", 0)

    # Extract parsed query fields
    muc_tieu = parsed_query.get("muc_tieu", "trich_xuat")
    noi_dung = parsed_query.get("noi_dung", "")
    ten_cong_ty = parsed_query.get("ten_cong_ty", "")
    so_nam = parsed_query.get("so_nam", [])
    tieu_chi_phu = parsed_query.get("tieu_chi_phu")

    # Get column names from mapping
    label_col = column_mapping.get("label_column", "CHỈ TIÊU")
    value_col = column_mapping.get("value_column", "Năm nay")

    # Build files context
    files_context = _build_files_context(discovered_tables, column_mapping)

    # Build file path variables for code
    paths_str = ""
    if discovered_tables:
        if len(discovered_tables) == 1:
            escaped = discovered_tables[0]["csv_path"].replace('\\', '\\\\')
            paths_str = f"file_path = '{escaped}'"
        else:
            for tbl in discovered_tables:
                nam = tbl.get("Nam_Tai_Chinh", "default")
                escaped = tbl["csv_path"].replace('\\', '\\\\')
                paths_str += f"file_path_{nam} = '{escaped}'\n"

    try:
        # Scenario A: Initial Code Generation
        if not error_traceback or retry_count == 0:
            prompt_data = load_yaml_prompt(cfg, "code_generator.yaml")
            system_prompt = prompt_data["system_prompt"]
            few_shots = prompt_data.get("few_shot_examples", [])

            messages = [SystemMessage(content=system_prompt)]
            for ex in few_shots:
                messages.append(
                    HumanMessage(
                        content=f"Yêu cầu: {ex['user_query']}\n"
                                f"File Path: {ex['file_path']}\n"
                                f"Column Mapping: {ex['column_mapping']}"
                    )
                )
                messages.append(SystemMessage(content=ex["generated_code"]))

            # Build human message with structured instructions
            muc_tieu_desc = {
                "trich_xuat": "TRÍCH XUẤT giá trị cụ thể",
                "tinh_tong": "TÍNH TỔNG (tìm dòng Tổng/Cộng trước, nếu không có thì cộng các dòng con)",
                "so_sanh": "SO SÁNH giá trị giữa nhiều năm/công ty",
            }

            human_content = (
                f"Yêu cầu người dùng: {user_query}\n\n"
                f"MỤC TIÊU: {muc_tieu_desc.get(muc_tieu, muc_tieu)}\n"
                f"NỘI DUNG cần tìm (ở cột label): '{noi_dung}'\n"
                f"Công ty: {ten_cong_ty}\n"
                f"Năm: {so_nam}\n"
                f"Tiêu chí phụ: {tieu_chi_phu or '(không có)'}\n\n"
                f"DỮ LIỆU CÓ SẴN:\n{files_context}\n\n"
                f"CỘT QUAN TRỌNG:\n"
                f"- Cột nhãn (chứa tên chỉ tiêu): '{label_col}'\n"
                f"- Cột giá trị: '{value_col}'\n\n"
                f"BIẾN ĐƯỜNG DẪN FILE:\n{paths_str}\n\n"
            )

            # Add specific instructions based on muc_tieu
            if muc_tieu == "trich_xuat":
                human_content += (
                    f"HƯỚNG DẪN CỤ THỂ:\n"
                    f"1. Đọc file CSV bằng pd.read_csv(file_path).\n"
                    f"2. Filter dòng chứa '{noi_dung}' ở cột '{label_col}'. Nếu rỗng, thử filter với từ khóa chính (VD: 'Tiền').\n"
                    f"3. Lấy giá trị ở cột '{value_col}', clean bằng clean_val().\n"
                    f"4. Gán vào biến result.\n"
                )
            elif muc_tieu == "tinh_tong":
                human_content += (
                    f"HƯỚNG DẪN CỤ THỂ:\n"
                    f"1. Đọc file CSV bằng pd.read_csv(file_path).\n"
                    f"2. Tìm dòng có chứa 'Tổng' hoặc 'Cộng' hoặc tên chỉ tiêu '{noi_dung}' ở cột '{label_col}'.\n"
                    f"3. Nếu tìm thấy → lấy giá trị ở cột '{value_col}', clean bằng clean_val(), gán vào result.\n"
                    f"4. Nếu KHÔNG tìm thấy → tìm các dòng con riêng lẻ liên quan đến '{noi_dung}', "
                    f"cộng tổng giá trị và gán vào result.\n"
                )
            elif muc_tieu == "so_sanh":
                human_content += (
                    f"HƯỚNG DẪN CỤ THỂ (TÍNH TỐC ĐỘ TĂNG TRƯỞNG / SO SÁNH NĂM):\n"
                    f"1. Đọc từng file CSV cho từng năm (ví dụ file_path_2019, file_path_2020, file_path_2021...).\n"
                    f"2. Từ mỗi file, filter dòng chứa '{noi_dung}' (hoặc từ khóa chính như 'Tiền') ở cột '{label_col}'.\n"
                    f"3. Lấy giá trị ở cột '{value_col}' của từng năm, clean bằng clean_val().\n"
                    f"4. Tính tốc độ tăng trưởng phần trăm (%) giữa năm đầu và năm cuối: `growth_rate = ((val_last - val_first) / val_first) * 100`.\n"
                    f"5. Gán kết quả vào `result` (ví dụ `result = growth_rate` hoặc dict chứa giá trị từng năm và tốc độ tăng trưởng).\n"
                )

            human_content += (
                f"\n🚨 BẮT BUỘC KHÔNG ĐƯỢC VI PHẠM:\n"
                f"1. Định nghĩa clean_val(val) để parse string số tài chính thành float.\n"
                f"2. Đọc file bằng pd.read_csv(file_path...).\n"
                f"3. Dùng `df['{label_col}'].astype(str).str.contains(..., case=False, na=False)` để lọc dòng. LUÔN DÙNG .astype(str) trước .str.\n"
                f"4. Kiểm tra `if not row.empty:` trước khi lấy `.values[0]`. Nếu rỗng, hãy lọc theo từ khóa ngắn hơn (ví dụ 'Tiền' thay vì cả câu dài) hoặc trả về 0.0.\n"
                f"5. KHÔNG ĐƯỢC filter theo `df['Ma_Doanh_Nghiep'] == ...` vì dữ liệu đã đúng công ty.\n"
                f"6. CHỈ ĐƯỢC SỬ DỤNG CÁC BIẾN ĐƯỜNG DẪN FILE ĐÃ ĐƯỢC ĐỊNH NGHĨA Ở TRÊN:\n{paths_str}\n"
                f"7. Kết quả cuối cùng BẮT BUỘC lưu vào biến `result`.\n"
            )

            messages.append(HumanMessage(content=human_content))

        # Scenario B: Reflection Debugging Loop (retry_count > 0)
        else:
            prompt_data = load_yaml_prompt(cfg, "reflection.yaml")
            system_prompt = prompt_data["system_prompt"]

            print(f"🔄 [Reflection Loop] Đang sửa lỗi mã nguồn (Lần {retry_count})...")
            print(f"   - Traceback Lỗi:\n{error_traceback.strip()}")

            # Extract sample labels from CSV files to guide LLM if IndexError occurred
            sample_labels = []
            if discovered_tables:
                from pathlib import Path
                for tbl in discovered_tables:
                    c_path = tbl.get("csv_path")
                    if c_path and Path(c_path).exists():
                        try:
                            sub_df = pd.read_csv(c_path)
                            if label_col in sub_df.columns:
                                labels = sub_df[label_col].dropna().astype(str).head(20).tolist()
                                sample_labels.append(f"Mẫu chỉ tiêu thực tế trong file '{Path(c_path).name}':\n{labels}")
                        except Exception:
                            pass
            sample_labels_str = "\n\n".join(sample_labels) if sample_labels else ""

            human_content = (
                f"Yêu cầu người dùng: {user_query}\n\n"
                f"MỤC TIÊU: {muc_tieu}\n"
                f"NỘI DUNG: '{noi_dung}'\n"
                f"DỮ LIỆU:\n{files_context}\n\n"
                f"CỘT: label='{label_col}', value='{value_col}'\n\n"
                f"BIẾN ĐƯỜNG DẪN:\n{paths_str}\n\n"
            )
            if sample_labels_str:
                human_content += f"{sample_labels_str}\n\n"

            human_content += (
                f"Mã Python bị lỗi trước đó:\n```python\n{state.get('generated_code', '')}\n```\n\n"
                f"Traceback Lỗi:\n{error_traceback}\n\n"
                f"HƯỚNG DẪN SỬA LỖI:\n"
                f"1. Dùng `df['{label_col}'].astype(str).str.contains(..., case=False, na=False)`.\n"
                f"2. Kiểm tra `if not row.empty:` trước khi truy cập `.values[0]`. Nếu rỗng, thử dùng từ khóa ngắn gọn có trong danh sách chỉ tiêu thực tế ở trên.\n"
                f"3. Đảm bảo kết quả cuối cùng BẮT BUỘC lưu vào biến `result`.\n"
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=human_content)
            ]

        # Call LLM
        llm = get_llm(cfg=cfg, temperature=0.0)
        response = llm.invoke(messages)
        raw_text = response.content if isinstance(response.content, str) else str(response.content)

        # Extract and print thoughts
        think_match = re.search(r"<think>(.*?)</think>", raw_text, re.DOTALL)
        if think_match:
            thought = think_match.group(1).strip()
            indented_thought = thought.replace('\n', '\n  ')
            print(f"💭 [Tư duy - Code Generator]:\n  {indented_thought}")
        else:
            code_start = raw_text.find("```")
            if code_start > 10:
                thought = raw_text[:code_start].strip()
                indented_thought = thought.replace('\n', '\n  ')
                print(f"💭 [Tư duy - Code Generator]:\n  {indented_thought}")

        code = clean_python_code(raw_text)

        print(f"📊 [Kết quả - Code Generator] Mã Python sinh ra:\n```python\n{code}\n```\n")

        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["code_generator"] = round(latency, 3)

        return {
            **state,
            "generated_code": code,
            "status": "pending",
            "node_latencies": node_latencies,
        }

    except Exception as e:
        latency = time.time() - start_time
        node_latencies = state.get("node_latencies", {})
        node_latencies["code_generator"] = round(latency, 3)

        return {
            **state,
            "status": "error",
            "error_message": f"Code generator node error: {str(e)}",
            "node_latencies": node_latencies,
        }