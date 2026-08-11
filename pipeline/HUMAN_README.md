# Hướng dẫn Khởi chạy Pandas Data Agent Pipeline ở Local 🥥💻

Tài liệu này hướng dẫn chi tiết cách cài đặt, cấu hình mô hình ngôn ngữ lớn (LLM), chạy thử nghiệm và thực hiện kiểm thử tự động hệ thống **Cocopila Agent Pipeline** trên môi trường máy cá nhân (Local).

---

## 📁 Cấu trúc thư mục liên quan
- [pipeline/src/](file:///d:/hobby_project/cocopila/pipeline/src): Mã nguồn của Agent (LangGraph nodes, state, config, prompts).
- [pipeline/tests/](file:///d:/hobby_project/cocopila/pipeline/tests): Bộ unit tests kiểm thử chức năng các Node độc lập.
- [pipeline/data/](file:///d:/hobby_project/cocopila/pipeline/data): Thư mục chứa dữ liệu đầu vào mẫu (CSV/Excel).
- [pipeline/run_agent.py](file:///d:/hobby_project/cocopila/pipeline/run_agent.py): Script chạy thử Agent end-to-end từ Terminal.

---

## 🛠️ Bước 1: Chuẩn bị Môi trường & Cài đặt Dependency

Hệ thống yêu cầu **Python >= 3.9** (Khuyến nghị sử dụng **Python 3.11**).

### 1. Khởi tạo và kích hoạt môi trường ảo (Virtual Environment)
Mở terminal tại thư mục gốc của dự án (`cocopila/`) và chạy:

**Trên Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Trên Windows (CMD):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

**Trên macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Cài đặt các thư viện phụ thuộc
Cài đặt gói nguồn `pipeline/src` ở chế độ **Editable (`-e`)** kèm theo các thư viện dùng cho nhà phát triển (`[dev]`):

```bash
pip install -e ./pipeline/src[dev]
```

*Lưu ý:* Nếu bạn có ý định chạy thử nghiệm mô-đun lưu trữ schema bằng Vector Database (ChromaDB), hãy cài đặt thêm:
```bash
pip install chromadb
```

---

## 🧠 Bước 2: Cài đặt và Tải xuống Mô hình (LLM Setup)

Agent Cocopila được thiết kế để tương thích với bất kỳ LLM nào cung cấp API chuẩn OpenAI (OpenAI-compatible). Bạn có thể chọn một trong các cách cấu hình dưới đây:

### Cách A: Sử dụng Ollama (Khuyến nghị cho Windows & macOS)
Ollama chạy cực kỳ nhẹ nhàng và ổn định trên môi trường local.

1. Tải và cài đặt Ollama từ [ollama.com](https://ollama.com).
2. Tải mô hình Qwen tối ưu cho việc sinh mã (Code Generation):
   ```bash
   ollama pull qwen2.5-coder:7b
   # Hoặc phiên bản nhẹ hơn cho máy cấu hình yếu:
   ollama pull qwen2.5-coder:1.5b
   ```
3. Sau khi chạy, Ollama sẽ khởi tạo API server mặc định tại `http://localhost:11434/v1`.

### Cách B: Sử dụng LM Studio (GGUF UI)
1. Cài đặt [LM Studio](https://lmstudio.ai).
2. Tìm kiếm và tải về các dòng model `Qwen/Qwen2.5-Coder` (hoặc `Qwen/Qwen3.5` nếu có bản GGUF).
3. Khởi động **Local Server** trên LM Studio (mặc định tại `http://localhost:1234/v1`).

### Cách C: Sử dụng vLLM (Dành cho Linux/WSL2 có GPU)
Nếu bạn có GPU mạnh và muốn sử dụng cấu hình tương tự như trên Kaggle:
```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen3.5-2B --port 8000
```

---

## ⚙️ Bước 3: Cấu hình Biến Môi trường

1. Tạo file `.env` từ file mẫu `.env.example`:
   ```bash
   # Trên Linux/macOS/Git Bash:
   cp .env.example .env

   # Trên Windows PowerShell:
   Copy-Item .env.example .env
   ```
2. Mở file `.env` vừa tạo và chỉnh sửa cấu hình phù hợp với LLM bạn đang dùng. Ví dụ cấu hình cho **Ollama**:
   ```env
   # Model Configuration
   MODEL_NAME=qwen2.5-coder:1.5b
   LLM_API_BASE=http://localhost:11434/v1
   LLM_API_KEY=ollama
   TEMPERATURE=0.0
   MAX_TOKENS=1024

   # Data & Prompts Paths
   DATA_DIR=./pipeline/data
   PROMPTS_DIR=./pipeline/src/prompts

   # Execution Config
   MAX_RETRIES=3
   EXECUTION_TIMEOUT=10
   ```

---

## 🚀 Bước 4: Khởi chạy Agent và Thực hiện Kiểm tra

Chúng ta sử dụng file [pipeline/run_agent.py](file:///d:/hobby_project/cocopila/pipeline/run_agent.py) để chạy thử nghiệm Agent với câu hỏi ngôn ngữ tự nhiên. 

### Chạy thử câu hỏi cơ bản
Hãy kiểm tra xem Agent có thể tìm kiếm dữ liệu và sinh code xử lý trên tệp [sample_sales.csv](file:///d:/hobby_project/cocopila/pipeline/data/sample_sales.csv) hay không:

```bash
python pipeline/run_agent.py --query "Tính tổng doanh thu (revenue) nhóm theo category từ file sample_sales"
```

### 🔍 Thực hiện kiểm tra thủ công & Phân tích các bước:

Khi chạy lệnh trên, bạn cần theo dõi terminal để đảm bảo luồng LangGraph chạy đúng trình tự 5 Node sau:

1. **`[QUERY_PARSER]`**:
   - Trích xuất được `intent` (ở đây là `aggregate`).
   - Trích xuất chính xác `file_name` đích là `sample_sales`.
2. **`[DATA_DISCOVERY]`**:
   - Định vị thành công tệp thực tế: `pipeline\data\sample_sales.csv`.
   - Trích xuất tự động Metadata Schema (các cột: `date`, `product_name`, `category`, `quantity`, `revenue`, `region`).
3. **`[SCHEMA_MAPPER]`**:
   - Ánh xạ từ khóa của người dùng sang cột thực tế (ví dụ: `revenue` -> `revenue`, `category` -> `category`).
4. **`[CODE_GENERATOR]`**:
   - Xem mã Python sinh ra. Đảm bảo mã sử dụng thư viện `pandas` và gán kết quả cuối cùng vào biến **`result`** (Yêu cầu bắt buộc của Executor).
   - Ví dụ mã hợp lệ:
     ```python
     import pandas as pd
     df = pd.read_csv(file_path)
     result = df.groupby('category')['revenue'].sum().reset_index()
     ```
5. **`[EXECUTOR]`**:
   - Thực thi mã trong môi trường **AST Sandbox** (chặn các mã độc hại như `import os` hay `exec()`).
   - Trả về dữ liệu dạng JSON, hiển thị kết quả tổng doanh thu theo từng nhóm hàng điện tử (Electronics), đồ nội thất (Furniture), v.v.

> [!TIP]
> **Reflection Loop (Vòng lặp sửa lỗi tự động):** Nếu mã Pandas sinh ra bị lỗi cú pháp hoặc lỗi logic (như KeyError do sai tên cột), Node `EXECUTOR` sẽ trả về trạng thái `error` và chuyển ngược Traceback về `CODE_GENERATOR` tối đa **3 lần** để tự động sửa lỗi và chạy lại. Bạn có thể test tính năng này bằng cách hỏi một câu phức tạp hoặc nhập nhằng về tên cột để quan sát vòng lặp kích hoạt.

---

## 🧪 Bước 5: Chạy Kiểm thử Chức năng Tự động (Unit Tests)

Bộ kiểm thử tự động giúp đảm bảo các hàm phân tích cú pháp, sàng lọc mã độc AST Sandbox, fuzzy matching và registry hoạt động ổn định.

Để chạy toàn bộ unit tests, thực hiện lệnh sau từ thư mục gốc dự án:

```bash
python -m pytest pipeline/tests/ -v
```

Các ca kiểm thử chính bao gồm:
- `test_query_parser.py`: Kiểm tra khả năng sửa chữa JSON lỗi (`json-repair`) và parser intent.
- `test_data_discovery.py`: Kiểm tra tính năng tìm kiếm tệp bằng thuật toán so khớp mờ (`thefuzz`).
- `test_schema_mapper.py`: Kiểm tra ánh xạ tên cột.
- `test_executor.py` & `test_sandbox.py`: Kiểm tra cơ chế Sandbox bảo mật (đảm bảo chặn đứng hành vi nguy hiểm như `import os; os.system(...)`).
- `test_vector_store.py`: Kiểm thử giả lập (mock) hoạt động của thư viện lưu trữ vector ChromaDB.
