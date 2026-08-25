"""State definition for LangGraph workflow in Cocopila."""

from typing import Any, Dict, List, Literal, Optional, TypedDict


class AgentState(TypedDict, total=False):
    """Shared state dictionary passed across LangGraph nodes."""

    # User Input
    user_query: str

    # Node 1: Query Parser Output (structured)
    parsed_query: Dict[str, Any]
    # Expected format:
    # {
    #   "muc_tieu": "trich_xuat" | "tinh_tong" | "so_sanh",
    #   "noi_dung": str,          # Nội dung ở cột đầu tiên của bảng
    #   "ten_cong_ty": str,       # Tên công ty
    #   "so_nam": list[str],      # Danh sách năm
    #   "tieu_chi_phu": str | None  # Tiêu chí phụ (tên cột giá trị)
    # }

    # Node 2: Data Discovery Output
    discovered_tables: List[Dict[str, Any]]  # List bảng từ Search Engine
    # Each table dict contains: csv_path, Ten_Bang, rrf_score, Ma_Doanh_Nghiep, Nam_Tai_Chinh, etc.
    table_schema: List[str]                  # Danh sách tên cột của bảng tốt nhất
    first_row_values: Dict[str, str]         # Giá trị hàng đầu tiên (khi cột có tên là số)

    # Node 3: Schema Mapper Output
    column_mapping: Dict[str, str]  # Map tiêu_chí_phụ → tên cột thực tế
    schema: Dict[str, Any]          # Schema phân tích bảng: useful_columns + sub_sections

    # Node 4: Code Generator Output
    generated_code: str

    # Node 5: Executor Output
    execution_result: Any
    error_traceback: Optional[str]
    retry_count: int

    # General Workflow Metadata
    status: Literal["pending", "success", "error"]
    error_message: Optional[str]
    node_latencies: Dict[str, float]
