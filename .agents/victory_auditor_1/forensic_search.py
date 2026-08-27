import os
import re
from pathlib import Path

root = Path("d:/hobby_project/cocopila/r2AI_2026")
src_dirs = [root / "pipeline" / "src", root / "notebooks"]

target_numbers = ["907768712503", "1855837", "200405269967", "264000000000"]
target_queries = ["Q28", "Q42", "Q32", "Q41", "Q19", "Q1", "Q3", "Q4"]

findings = []

for s_dir in src_dirs:
    for path in s_dir.rglob("*"):
        if path.is_file() and path.suffix in [".py", ".yaml", ".yml", ".ipynb"]:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                for num in target_numbers:
                    if num in content:
                        findings.append((path, f"Found target number: {num}"))
                for q in ["Q28", "Q42", "Q32", "Q41", "Q19"]:
                    if re.search(rf"\b{q}\b", content):
                        findings.append((path, f"Found target query tag: {q}"))
            except Exception as e:
                findings.append((path, f"Error reading file: {e}"))

print(f"Total findings in source/notebook files: {len(findings)}")
for p, msg in findings:
    print(f"  {p.relative_to(root)}: {msg}")
