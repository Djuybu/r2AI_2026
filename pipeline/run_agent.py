import os
import sys
import argparse
import json
from pathlib import Path
from dotenv import load_dotenv

# Ensure root directory is in sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from pipeline.src.graph import create_cocopila_graph

def main():
    parser = argparse.ArgumentParser(description="Chạy Cocopila Pandas Data Agent Pipeline từ Terminal")
    parser.add_argument("--query", type=str, required=True, help="Câu hỏi ngôn ngữ tự nhiên cần truy vấn dữ liệu")
    args = parser.parse_args()

    # Load environment variables
    load_dotenv()

    # Initialize agent graph
    print("🤖 Đang khởi tạo Agent workflow...")
    try:
        app = create_cocopila_graph()
    except Exception as e:
        print(f"❌ Không thể tạo workflow graph: {e}")
        sys.exit(1)

    print(f"🚀 Bắt đầu thực hiện truy vấn: '{args.query}'")
    print("-" * 60)

    # Initial state
    inputs = {
        "user_query": args.query,
        "retry_count": 0,
        "node_latencies": {},
        "status": "pending"
    }

    # Run and stream node state transitions
    try:
        for output in app.stream(inputs):
            for node_name, node_state in output.items():
                latency = node_state.get('node_latencies', {}).get(node_name, 'N/A')
                print(f"\n📍 Node: [{node_name.upper()}] (Latency: {latency}s)")
                
                # Custom logging depending on node
                if node_name == "query_parser":
                    pq = node_state.get('parsed_query', {})
                    print(f"   Mục tiêu: {pq.get('muc_tieu')}")
                    print(f"   Nội dung: {pq.get('noi_dung')}")
                    print(f"   Tên công ty: {pq.get('ten_cong_ty')}")
                    print(f"   Số năm: {pq.get('so_nam')}")
                    print(f"   Tiêu chí phụ: {pq.get('tieu_chi_phu')}")
                elif node_name == "data_discovery":
                    tables = node_state.get('discovered_tables', [])
                    print(f"   Số bảng tìm thấy: {len(tables)}")
                    for tbl in tables:
                        print(f"      - {tbl.get('Ten_Bang')} ({tbl.get('Nam_Tai_Chinh')}): {tbl.get('csv_path')}")
                elif node_name == "schema_mapper":
                    print(f"   Column mapping: {node_state.get('column_mapping')}")
                elif node_name == "code_generator":
                    print("   Code sinh ra:")
                    code = node_state.get('generated_code', '')
                    for line in code.split('\n'):
                        print(f"      {line}")
                elif node_name == "executor":
                    status = node_state.get('status')
                    print(f"   Status: {status.upper()}")
                    if status == "success":
                        result = node_state.get('execution_result', {})
                        print(f"   Result Type: {result.get('type')}")
                        print("   Result Data:")
                        print(json.dumps(result.get('data'), indent=6, ensure_ascii=False))
                    else:
                        print(f"   Error Traceback:\n{node_state.get('error_traceback')}")
                        print(f"   Retry Count: {node_state.get('retry_count')}")
                
                if node_state.get("status") == "error" and node_name != "executor":
                    print(f"   ❌ Node error: {node_state.get('error_message')}")
                    break
        
    except Exception as e:
        print(f"❌ Đã xảy ra lỗi hệ thống: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
