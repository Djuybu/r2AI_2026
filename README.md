# Cocopila: Pandas Data Agent Pipeline 🥥📊

Hệ thống **Pandas Data Agent Pipeline** xây dựng trên LangGraph và **Qwen3.5-2B** (self-hosted qua vLLM / OpenAI-compatible API).
Cho phép người dùng hỏi đáp dữ liệu bằng ngôn ngữ tự nhiên, tự động chuyển đổi thành mã Pandas xử lý CSV/Excel và thực thi an toàn trong Sandbox.

---

## 🌟 Đắc điểm chính
- **Self-hosted LLM**: Sử dụng `Qwen/Qwen3.5-2B` (Instruct) tương thích GPU T4 trên Kaggle.
- **LangGraph Workflow**: Architecture 5 nodes với Reflection Loop tự gỡ lỗi.
- **Kaggle-First**: Sẵn sàng chạy trên Kaggle Notebook với vLLM background server.
- **AST Sandbox Execution**: Đảm bảo an toàn khi chạy code Python/Pandas sinh ra từ LLM.
- **Evaluation Suite**: Bộ kiểm thử chất lượng đa tầng với Golden Dataset.

---

## 📁 Cấu trúc dự án
```text
cocopila/
├── notebooks/           # Notebooks cho Kaggle execution & evals
├── src/                 # Mã nguồn agent
│   ├── nodes/           # LangGraph nodes (Query Parser, Discovery, Mapper, CodeGen, Executor)
│   ├── prompts/         # Prompt templates (YAML)
│   ├── utils/           # Sandbox, JSON Repair, Registry
│   ├── config.py        # Environment variables & settings
│   ├── state.py         # AgentState schema
│   ├── llm_provider.py  # LLM Factory (vLLM / local)
│   └── graph.py         # StateGraph definition
├── evals/               # Evaluation framework & Golden Dataset
├── tests/               # Unit tests
└── data/                # Chứa file CSV/Excel mẫu
```

---

## 🚀 Hướng dẫn nhanh

### 1. Khởi chạy trên Kaggle
Mở file `notebooks/kaggle_bootstrap.ipynb` trên Kaggle Notebook với GPU T4 và chạy theo thứ tự các cell.

### 2. Chạy Local (Dev)
```bash
# Cài đặt môi trường
pip install -e .

# Copy file cấu hình
cp .env.example .env

# Chạy unit tests
pytest tests/ -v
```
