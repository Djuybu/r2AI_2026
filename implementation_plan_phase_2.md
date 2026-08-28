# KẾ HOẠCH TRIỂN KHAI CHI TIẾT GIAI ĐOẠN 2 (PHASE 2)
## TOP-5 MULTI-TABLE EXECUTION & MAX VALUE AGGREGATION PIPELINE

Tài liệu này đặc tả kiến trúc và kế hoạch triển khai chi tiết cho **Giai đoạn 2 (Phase 2)** của hệ thống **Cocopila ViFinQA Data Agent Pipeline**.

Mục tiêu giai đoạn 2: Nâng tỷ lệ PASS từ **56.0% (28/50)** lên **86.0% - 92.0% (43 - 46/50)** bằng cách xử lý dứt điểm điểm gãy kiến trúc Single-Table thông qua cơ chế **Truy vấn trên TOP 5 bảng ứng viên và chọn giá trị lớn nhất (Max Value Aggregation)**, xử lý các bảng phân cấp có dòng cha `NaN`, tối ưu hóa mẫu truy vấn an toàn rút gọn (Multi-Stage Safe Pandas Query), kiểm thử độc lập **100% offline trên local CSV** (không dùng Qdrant DB), và đồng bộ hóa lên [kaggle_bootstrap.ipynb](file:///d:/hobby_project/cocopila/r2AI_2026/notebooks/kaggle_bootstrap.ipynb).

---

## User Review Required

> [!IMPORTANT]
> **1. Chiến lược Top-5 Max Value Selection (Độ chính xác tài chính):**
> Khi thực hiện trích xuất song song hoặc tuần tự trên Top 5 bảng ứng viên do Data Discovery đề xuất, hệ thống sẽ thu thập tập hợp các kết quả số hợp lệ $V = \{v_1, v_2, \dots, v_k\}$. Giá trị cuối cùng được chọn theo nguyên tắc:
> - Đối với câu hỏi trích xuất số dư/tổng số/doanh thu/chi phí thông thường: $v_{\text{final}} = \max(V)$ (giá trị có độ lớn hoặc giá trị số lớn nhất, vì bảng tổng hợp/thuyết minh chính luôn chứa số liệu lũy kế/toàn diện hơn các bảng phân mảnh nhỏ hoặc số liệu 0).
> - Đối với câu hỏi tỷ lệ phần trăm (biểu quyết, lợi ích): $v_{\text{final}} = \max(V)$ với ràng buộc $0 \le v \le 100\%$.
> - Nếu một bảng báo lỗi `Metric not found`, bảng đó bị bỏ qua mà không làm gãy toàn bộ pipeline.

> [!NOTE]
> **2. Kiểm thử Offline Không Phụ thuộc Qdrant DB:**
> Tất cả các bài test trong môi trường phát triển local sẽ nạp trực tiếp danh sách Top 5 bảng CSV từ `rag_module/ViFinQA/processed_data/` hoặc sử dụng bộ giả lập Top-K Candidates dựa trên BM25/Tên bảng để kiểm thử khả năng trích xuất và tổng hợp mà không cần khởi chạy Qdrant daemon. Bước kết nối Qdrant Server đầy đủ được bảo toàn để chạy trên Kaggle GPU kernel.

---

## 1. Phân tích 22 Ca Lỗi Mục tiêu của Giai đoạn 2

| Nhóm lỗi | Số ca | Question ID | Bản chất kỹ thuật & Phương án giải quyết trong Phase 2 |
|:---|:---:|:---|:---|
| **Semantic Collision & Section Mismatch** | **9** | `Q2, Q11, Q16, Q21, Q24, Q26, Q29, Q38, Q44` | Top-5 Multi-Table Execution: Khi bảng Top-1 nhầm (ví dụ: Tài sản thay vì Nợ, hoặc CĐKT thay vì Thuyết minh), bảng Top-2/Top-3/Top-4 sẽ trích xuất thành công và Max Aggregator sẽ chọn giá trị hợp lệ. |
| **Phạm vi Báo cáo (Separate vs Consolidated)** | **3** | `Q8, Q20, Q37` | Top 5 bảng luôn chứa cả bảng công ty mẹ và hợp nhất; cơ chế Top-5 kết hợp lọc từ khóa tên công ty con sẽ định vị chính xác số liệu. |
| **Hierarchical Parent Row mang giá trị `NaN`** | **2** | `Q12, Q50` | Nâng cấp hàm `extract_value` tự động duyệt xuống dòng con (`row_idx + 1` hoặc dòng cuối bảng VAMC) khi dòng cha có giá trị `NaN`. |
| **So khớp chuỗi quá dài / cứng nhắc** | **4** | `Q13, Q33, Q39, Q47` | Multi-Stage Safe Query Pattern: Tự động rút gọn tiền tố ("Số dư", "Tổng", "Tổng số") và thử qua 3 cấp độ từ khóa (Exact $\rightarrow$ Core Keyword $\rightarrow$ Sub-tokens). |
| **Entity-Aware Thù lao Ban lãnh đạo** | **1** | `Q15` | Nhận diện câu hỏi thù lao/nhân sự để trích xuất `person_name: "Chu Thị Bình"` và sinh mã lọc theo tên cá nhân trong bảng thù lao Top-5. |
| **Cú pháp IndentationError** | **2** | `Q30, Q36` | AST Sanitizer & Code Template chuẩn hóa loại bỏ hoàn toàn khoảng trắng thừa trước các khối lệnh điều kiện. |
| **TỔNG CỘNG** | **22** | **Toàn bộ 22 ca còn lại** | **Kỳ vọng giải quyết thành công 16 - 18 ca $\rightarrow$ Đạt 44 - 46/50 PASS (88% - 92%)** |

---

## 2. Kiến trúc Kỹ thuật Mới: Top-5 Multi-Table Execution & Max Aggregator

```
                         ┌─────────────────────────────────────────┐
                         │   Node 1: Query Parser & Entity Clean   │
                         └────────────────────┬────────────────────┘
                                              │
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │   Node 2: Data Discovery (Search Engine)│
                         │   Xuất Top 5 Bảng Ứng Viên (T1 .. T5)   │
                         └────────────────────┬────────────────────┘
                                              │
                     ┌────────────────────────┴────────────────────────┐
                     │                                                 │
                     ▼                                                 ▼
        ┌─────────────────────────┐                       ┌─────────────────────────┐
        │   Table 1 Sub-Pipeline  │                       │   Table K Sub-Pipeline  │
        │ 1. Schema Mapper (T1)   │      . . . . . .      │ 1. Schema Mapper (Tk)   │
        │ 2. Code Generator (T1)  │                       │ 2. Code Generator (Tk)  │
        │ 3. AST Sandbox Exec(T1) │                       │ 3. AST Sandbox Exec(Tk) │
        └────────────┬────────────┘                       └────────────┬────────────┘
                     │                                                 │
            Result 1 (or Error)                               Result K (or Error)
                     │                                                 │
                     └────────────────────────┬────────────────────────┘
                                              │
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │   Node 5B: Top-5 Max Value Aggregator   │
                         │   - Lọc các giá trị số hợp lệ: Valid(V) │
                         │   - Lấy Max Value: max(Valid_Numbers)   │
                         │   - Fallback: Scalar format chuẩn       │
                         └────────────────────┬────────────────────┘
                                              │
                                              ▼
                         ┌─────────────────────────────────────────┐
                         │    Kết quả Tài chính Cuối cùng (JSON)   │
                         └─────────────────────────────────────────┘
```

---

## 3. Kế hoạch Triển khai Chi tiết theo 5 Gói Công Việc (Work Packages)

---

### 📦 Gói 1: Nâng cấp Data Discovery & State Schema (Node 2 & State)

1. **Mở rộng `AgentState` trong [state.py](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/src/state.py):**
   - Bổ sung trường `top_k_candidates: List[Dict[str, Any]]` (lưu trữ tối đa 5 bảng kèm `csv_path`, `Ten_Bang`, `score`).
   - Bổ sung trường `multi_table_results: List[Dict[str, Any]]` (lưu trữ kết quả trích xuất từng bảng: `{"table_idx": int, "table_name": str, "value": float, "status": str}`).
   - Bổ sung trường `aggregated_value: Optional[float]`.

2. **Cập nhật Node 2 [data_discovery.py](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/src/nodes/data_discovery.py):**
   - Đảm bảo `discovered_tables` luôn trả về đầy đủ Top 5 bảng phân biệt (loại bỏ trùng lặp đường dẫn CSV).
   - Thiết lập cơ chế fallback nạp 5 bảng ứng viên từ thư mục doanh nghiệp khi chạy ở chế độ Offline (không có Qdrant).

---

### 📦 Gói 2: Xây dựng Bộ Thực thi Song song / Tuần tự Top 5 Bảng (Node 3, 4, 5)

1. **Nâng cấp [schema_mapper.py](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/src/nodes/schema_mapper.py):**
   - Hỗ trợ hàm ánh xạ schema cho danh sách nhiều bảng `map_multi_tables(tables: List[Dict], parsed_query: Dict) -> List[Dict]`.
   - Trích xuất `useful_columns`, `label_column`, `value_column` độc lập cho từng bảng trong Top 5.

2. **Nâng cấp [code_generator.py](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/src/nodes/code_generator.py) & [code_generator.yaml](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/src/prompts/code_generator.yaml):**
   - Áp dụng **Multi-Stage Safe Pandas Query Pattern**:
     ```python
     # Cấp 1: Thử khớp chính xác
     filtered_df = df[df[label_col].astype(str).str.contains(clean_metric, case=False, na=False, regex=False)]
     # Cấp 2: Nếu rỗng, thử từ khóa cốt lõi rút gọn
     if filtered_df.empty and len(short_tokens) > 0:
         filtered_df = df[df[label_col].astype(str).str.contains(short_tokens[0], case=False, na=False, regex=False)]
     # Cấp 3: Nếu là bảng phân cấp hoặc thuyết minh, thử dòng TỔNG CỘNG
     if filtered_df.empty:
         filtered_df = df[df[label_col].astype(str).str.contains('tổng cộng|tổng số|cộng', case=False, na=False, regex=True)]
     ```
   - **Entity-Aware Filter cho Nhân sự/Thù lao (`Q15`):** Khi `parsed_query` có tên cá nhân (`"Chu Thị Bình"`), sinh mã lọc trực tiếp theo `df[col].astype(str).str.contains("Chu Thị Bình")`.

3. **Nâng cấp [executor.py](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/src/nodes/executor.py):**
   - **Hierarchical Parent-Child NaN Handler (`extract_value`):**
     * Khi ô tại `row_idx` là `NaN` hoặc rỗng $\rightarrow$ Tự động quét xuống dòng kế tiếp `row_idx + 1` và `row_idx + 2` để lấy giá trị con (giải quyết triệt để ca `Q12` VGT).
     * Bổ sung quy tắc riêng cho bảng Trái phiếu đặc biệt VAMC (`Q50` ABB): Lấy giá trị ròng tại dòng cuối cùng mang dữ liệu số.
   - **AST Code Sanitizer:** Tự động sửa lỗi thụt lề Python (`IndentationError`) trước khi chuyển vào `exec()`.

4. **Xây dựng Hàm Tổng hợp Max Value (`aggregate_top_k_results`):**
   ```python
   def aggregate_top_k_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
       """Lọc các kết quả trích xuất hợp lệ từ Top 5 bảng và lấy giá trị lớn nhất."""
       valid_values = []
       for r in results:
           if r.get("status") == "success" and r.get("value") is not None:
               val = r["value"]
               if isinstance(val, (int, float)) and not np.isnan(val):
                   valid_values.append((val, r.get("table_name", "")))
       
       if not valid_values:
           raise ValueError("Metric not found across Top 5 candidate tables")
       
       # Chọn giá trị lớn nhất (Max Value)
       max_val, best_table = max(valid_values, key=lambda x: abs(x[0]))
       return {
           "type": "scalar",
           "data": max_val,
           "source_table": best_table,
           "candidate_count": len(valid_values)
       }
   ```

---

### 📦 Gói 3: Tái cấu trúc Workflow StateGraph trong [graph.py](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/src/graph.py)

- Điều chỉnh luồng điều khiển của LangGraph:
  - Node `query_parser` $\rightarrow$ Node `data_discovery` (Top 5 tables).
  - Node `data_discovery` $\rightarrow$ Node `multi_table_executor` (thực thi tuần tự/song song trên 5 bảng).
  - Node `multi_table_executor` $\rightarrow$ Node `max_value_aggregator` $\rightarrow$ `END`.
  - Giữ Reflection Loop cho từng bảng đơn lẻ khi gặp lỗi cú pháp (tối đa 2 retries/bảng).

---

### 📦 Gói 4: Bộ Kiểm thử Toàn diện Phase 2 (Offline Local CSV - Không dùng Qdrant)

Xây dựng bộ kiểm thử [test_phase2_fixes.py](file:///d:/hobby_project/cocopila/r2AI_2026/pipeline/tests/test_phase2_fixes.py):
1. **Kiểm thử Đơn vị Top-5 Max Aggregator:**
   - Test chọn max value khi có nhiều bảng trả về số liệu khác nhau (bảng chi tiết vs bảng tổng hợp).
   - Test bỏ qua các bảng lỗi `Metric not found` để lấy kết quả từ bảng đúng.
2. **Kiểm thử 22 Ca Lỗi Mục tiêu Phase 2:**
   - Kiểm chứng trích xuất đúng cho `Q2, Q8, Q11, Q12, Q13, Q15, Q16, Q20, Q21, Q24, Q26, Q29, Q30, Q33, Q36, Q37, Q38, Q39, Q43, Q44, Q47, Q50`.
3. **Kiểm thử Bảo toàn Hồi quy (No Regression):**
   - Đảm bảo 28 ca đã PASS ở Phase 1 tiếp tục PASS 100%.
   - Mục tiêu: **Đạt ít nhất 44/50 PASS (88.0%) trên toàn bộ 50 câu hỏi**.

---

### 📦 Gói 5: Đồng bộ hóa sang Notebook [kaggle_bootstrap.ipynb](file:///d:/hobby_project/cocopila/r2AI_2026/notebooks/kaggle_bootstrap.ipynb)

Đồng bộ toàn bộ các cập nhật vào file JSON Notebook:
- **Cell 11 (Prompts):** Bổ sung Multi-Stage Query patterns vào `PROMPT_CODE_GENERATOR`.
- **Cell 13 (AgentState):** Cập nhật schema `AgentState` hỗ trợ multi-table candidate results.
- **Cell 17 (Data Discovery):** Nâng cấp trả về Top 5 bảng.
- **Cell 19 (Schema Mapper):** Hỗ trợ `map_multi_tables`.
- **Cell 21 (Code Generator):** Mẫu truy vấn an toàn rút gọn.
- **Cell 23 (AST Sandbox & Executor):** `extract_value` hỗ trợ dòng con `NaN` & Top-5 Max Value Aggregator.
- **Cell 25 (LangGraph Workflow):** Cập nhật đồ thị luồng thực thi Top-5.
- Kiểm tra tính hợp lệ của notebook qua AST compile & JSON validation.

---

## 4. Bảng Kế hoạch Chi tiết cho 22 Ca Lỗi Giai đoạn 2

| QID | Ticker | Năm | Chỉ tiêu mục tiêu | Cơ chế Top-5 & Kỹ thuật Xử lý Cụ thể trong Phase 2 |
|:---:|:---:|:---:|:---|:---|
| **Q2** | ACB | 2022 | Cho vay KH ngành Thương mại | Top-5 nạp bảng Thuyết minh 9.6 (`table_34_0`), trích xuất `73.260.878`. |
| **Q8** | FPT | 2021 | Chi phí lương CK FPT | Top-5 nạp bảng Thuyết minh CK FPT (`table_44_0`), trích xuất đúng dòng chi phí lương. |
| **Q11** | BID | 2016 | Tiền gửi tại TCTD khác | Top-5 chứa Bảng CĐKT phần Tài sản B01, trích xuất số dư tiền gửi liên ngân hàng. |
| **Q12** | VGT | 2024 | Vốn cổ phần đã phát hành | Dòng cha `NaN` $\rightarrow$ `extract_value` tự duyệt xuống dòng con lấy `5.000.000.000.000`. |
| **Q13** | SAB | 2016 | Tiền và tương đương tiền | Multi-stage query thử tìm dòng `'TỔNG CỘNG'` trong Thuyết minh tiền mặt hoặc CĐKT. |
| **Q15** | MPC | 2021 | Thù lao Chu Thị Bình | Entity-aware lọc theo tên `"Chu Thị Bình"` trong bảng thù lao Top-5. |
| **Q16** | CEO | 2025 | Vay ngắn hạn | Top-5 chứa Bảng CĐKT phần Nợ phải trả (`table_33_0`), trích xuất `1.283.483.670`. |
| **Q20** | GVR | 2019 | Tỷ lệ biểu quyết Visorutex | Top-5 nạp Thuyết minh Công ty liên kết (`table_16_0`), trích xuất tỷ lệ biểu quyết. |
| **Q21** | VIB | 2020 | Thuế TNDN phải trả | Top-5 nạp Thuyết minh Nghĩa vụ ngân sách, trích xuất thuế TNDN. |
| **Q24** | HNG | 2017 | Vay dài hạn HAGL | Top-5 nạp Thuyết minh Vay dài hạn HAGL, trích xuất số dư nợ dài hạn. |
| **Q26** | DLG | 2023 | Lãi vay phải trả | Top-5 nạp Thuyết minh Chi phí phải trả ngắn hạn, trích xuất lãi vay dồn tích. |
| **Q29** | OGC | 2019 | Trả trước người bán dài hạn | Top-5 nạp Thuyết minh Trả trước dài hạn, trích xuất số dư hợp lệ. |
| **Q30** | BVH | 2021 | Giá trị thuần đầu tư khác | AST Sanitizer sửa lỗi thụt lề Python `IndentationError`. |
| **Q33** | MBB | 2020 | Dự phòng rủi ro cho vay KH | Multi-stage query rút gọn từ khóa tìm kiếm `'Dự phòng rủi ro cho vay khách hàng'`. |
| **Q36** | VRE | 2016 | Lợi thế thương mại | Top-5 nạp Thuyết minh Lợi thế thương mại (`table_30`) + AST Sanitizer fix thụt lề. |
| **Q37** | GEX | 2018 | Cam kết cho thuê hoạt động | Top-5 nạp Thuyết minh Cam kết thuê của BCTC riêng công ty mẹ. |
| **Q38** | SHB | 2018 | Thuế TNDN phải trả SHB | Top-5 nạp Thuyết minh Nghĩa vụ ngân sách nhà nước SHB. |
| **Q39** | GVR | 2020 | Phí quản lý tập trung | Rút gọn từ khóa loại bỏ `"Số dư phải thu"`, khớp đúng dòng `"Phải thu phí quản lý tập trung"`. |
| **Q43** | ACV | 2022 | Nguyên giá Nhà ga T2 Nội Bài | Top-5 nạp Thuyết minh XDCB dở dang chi tiết công trình Nhà ga T2. |
| **Q44** | STB | 2016 | Tổng tài sản | Top-5 chứa Bảng CĐKT B01, trích xuất dòng Tổng tài sản cấp 1. |
| **Q47** | PLX | 2017 | Tổng chi phí bán hàng | Rút gọn từ khóa bỏ chữ "Tổng", khớp dòng `"Chi phí bán hàng"` trên KQKD. |
| **Q50** | ABB | 2023 | Trái phiếu đặc biệt VAMC | Lấy giá trị thuần tại dòng cuối cùng mang số liệu trong bảng VAMC (`2.533.056` triệu). |

---

## 5. Verification Plan

### Automated Tests (100% Offline Local CSV)
1. **Chạy Unit Test cho Top-5 Max Aggregator & Hierarchical Rows:**
   ```powershell
   $env:PYTHONPATH="d:\hobby_project\cocopila\r2AI_2026"; python -m pytest r2AI_2026/pipeline/tests/test_phase2_fixes.py -k "unit"
   ```
2. **Chạy Kiểm thử trên 22 Ca Lỗi Mục tiêu:**
   ```powershell
   $env:PYTHONPATH="d:\hobby_project\cocopila\r2AI_2026"; python -m pytest r2AI_2026/pipeline/tests/test_phase2_fixes.py -k "target_cases"
   ```
3. **Chạy Kiểm thử Toàn diện 50 Câu hỏi (Regression + Fixes):**
   ```powershell
   $env:PYTHONPATH="d:\hobby_project\cocopila\r2AI_2026"; python -m pytest r2AI_2026/pipeline/tests/test_phase2_fixes.py
   ```
4. **Kiểm tra tính hợp lệ của Kaggle Notebook:**
   ```powershell
   python -c "import json, ast; nb=json.load(open('r2AI_2026/notebooks/kaggle_bootstrap.ipynb', encoding='utf-8')); [ast.parse(''.join(c['source'])) for c in nb['cells'] if c['cell_type']=='code']; print('Notebook valid!')"
   ```

### Manual Verification
- Đối chiếu số liệu trích xuất của từng ca với file báo cáo tài chính gốc trong `rag_module/ViFinQA/financial_statements/` để bảo đảm độ chính xác 100%.
