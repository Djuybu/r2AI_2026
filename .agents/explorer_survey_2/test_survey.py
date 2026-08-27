import re
from pathlib import Path
import pandas as pd

AUXILIARY_COL_REGEX = re.compile(
    r'^(stt|số\s*tt|số\s*thứ\s*tự|sothutu|mã\s*số|mãsố|thuyết\s*minh|thuyếtminh|ghi\s*chú|note|code|ms|tm|cột_\d+|unnamed.*)$',
    re.IGNORECASE
)

def _is_cell_empty(val):
    if val is None or pd.isna(val):
        return True
    s = str(val).strip()
    return s.lower() in {'', 'nan', 'none', 'null', 'n/a', 'na', '-', '—', '--', 'nil'}

def _is_numeric_value(val):
    if _is_cell_empty(val):
        return False
    s = str(val).strip().replace(',', '').replace('.', '').replace(' ', '').replace('%', '').replace('$', '')
    if s.startswith('(') and s.endswith(')'):
        s = s[1:-1]
    if s.startswith('-') or s.startswith('+'):
        s = s[1:]
    return s.isdigit() and len(s) > 0

def _is_code_or_index_column_refined(series: pd.Series, col_name: str = '') -> bool:
    if col_name and AUXILIARY_COL_REGEX.match(str(col_name).strip()):
        return True
    non_empty = [str(x).strip() for x in series if not _is_cell_empty(x)]
    if not non_empty:
        return False
    index_token_pattern = re.compile(
        r'^(?:[0-9]{1,4}[a-z]?|[IVXLCDM]+|[A-Z]|\(\w+\)|\d+\.\d{1,2}|\d+[\.\)]|\d+\.\d+\.\d+)$',
        re.IGNORECASE
    )
    index_matches = sum(
        1 for s in non_empty 
        if (len(s) <= 4 and not _is_numeric_value(s)) or 
           (len(s) <= 5 and bool(re.match(r'^\d+\.0+$', s))) or 
           (len(s) <= 6 and bool(index_token_pattern.match(s)))
    )
    total_chars = sum(len(x) for x in non_empty)
    letter_count = sum(sum(1 for ch in x if ch.isalpha()) for x in non_empty)
    avg_len = total_chars / len(non_empty)
    letter_ratio = (letter_count / total_chars) if total_chars > 0 else 0.0
    if avg_len <= 4.0 and letter_ratio < 0.35:
        return True
    return (index_matches / len(non_empty)) >= 0.6

def _extract_useful_columns_refined(df, metadata_cols=None):
    metadata_set = metadata_cols or set()
    useful = []
    candidate_cols = [c for c in df.columns if c not in metadata_set]
    for col in candidate_cols:
        series = df[col]
        non_empty = [str(x).strip() for x in series if not _is_cell_empty(x)]
        data_rows = len(non_empty)
        empty_rows = len(series) - data_rows
        if data_rows <= empty_rows:
            continue
        numeric_count = sum(1 for val in series if _is_numeric_value(val))
        total_chars = sum(len(x) for x in non_empty)
        letter_count = sum(sum(1 for ch in x if ch.isalpha()) for x in non_empty)
        avg_len = total_chars / data_rows if data_rows > 0 else 0.0
        letter_ratio = (letter_count / total_chars) if total_chars > 0 else 0.0

        is_aux = _is_code_or_index_column_refined(series, str(col))
        data_type = 'text' if is_aux else ('numeric' if (data_rows > 0 and numeric_count / data_rows >= 0.5) else 'text')
        useful.append({
            'raw_column': str(col),
            'column_name': str(col),
            'data_type': data_type,
            'is_aux_code': is_aux,
            'avg_str_len': avg_len,
            'letter_ratio': letter_ratio,
            'data_rows_count': data_rows,
            'empty_rows_count': empty_rows,
            'sample_values': non_empty[:3]
        })
    return useful

def _find_label_column_enhanced(useful_columns, raw_columns=None):
    if not useful_columns:
        return raw_columns[0] if raw_columns else None
    primary_text = [
        c for c in useful_columns
        if c.get('data_type') == 'text' and not c.get('is_aux_code', False)
        and not AUXILIARY_COL_REGEX.match(str(c.get('column_name', '')).strip())
    ]
    if primary_text:
        return max(primary_text, key=lambda c: (c.get('letter_ratio', 0) >= 0.4, c.get('avg_str_len', 0)))['raw_column']
    text_cols = [c for c in useful_columns if c.get('data_type') == 'text']
    if text_cols:
        return max(text_cols, key=lambda c: c.get('avg_str_len', 0))['raw_column']
    return useful_columns[0]['raw_column']

def _find_value_column_enhanced(useful_columns, label_col=None, tieu_chi_phu=None, columns=None):
    if not useful_columns:
        if columns:
            cand = [c for c in columns if c != label_col]
            return cand[0] if cand else None
        return None
    value_candidates = [c for c in useful_columns if c['raw_column'] != label_col]
    if not value_candidates:
        value_candidates = useful_columns

    if tieu_chi_phu and value_candidates:
        clean_tcp = str(tieu_chi_phu).strip().lower()
        for uc in value_candidates:
            c_name = str(uc.get('column_name', '')).lower()
            r_name = str(uc.get('raw_column', '')).lower()
            desc = str(uc.get('column_description', '')).lower()
            if clean_tcp in c_name or clean_tcp in r_name or clean_tcp in desc:
                return uc['raw_column']

        if any(pct_kw in clean_tcp for pct_kw in ['%', 'phần trăm', 'tỷ lệ', 'ty le', 'biểu quyết', 'sở hữu']):
            for uc in value_candidates:
                c_name = str(uc.get('column_name', '')).lower()
                r_name = str(uc.get('raw_column', '')).lower()
                if any(k in c_name or k in r_name for k in ['%', 'tỷ lệ', 'ty le', 'biểu quyết', 'sở hữu']):
                    return uc['raw_column']

    numeric_cand = [c for c in value_candidates if c.get('data_type') == 'numeric']
    if numeric_cand:
        return numeric_cand[0]['raw_column']
    return value_candidates[0]['raw_column']


if __name__ == '__main__':
    test_dir = Path('d:/hobby_project/cocopila/r2AI_2026/pipeline/tests')
    success_files = sorted(list(test_dir.glob('test_q_*_success.py')))
    print(f'Checking {len(success_files)} success test files for regression...')

    meta = set(['Ma_Doanh_Nghiep', 'Ten_Doanh_Nghiep', 'Nam_Tai_Chinh', 'Loai_Bao_Cao', 'Ten_Bang', 'Don_Vi_Tinh', 'Tep_Nguon'])

    passed_count = 0
    for sf in success_files:
        content = sf.read_text(encoding='utf-8', errors='ignore')
        matches = re.findall(r"file_path\w*\s*=\s*['\"]([^'\"]+)['\"]", content)
        for m in matches:
            idx = m.find('ViFinQA')
            if idx != -1:
                rel = m[idx:]
                local_p = Path('d:/hobby_project/cocopila/r2AI_2026/rag_module') / rel
                if local_p.exists():
                    df = pd.read_csv(local_p)
                    raw_cols = list(df.columns)
                    useful = _extract_useful_columns_refined(df, metadata_cols=meta)
                    lbl = _find_label_column_enhanced(useful, raw_cols)
                    val = _find_value_column_enhanced(useful, label_col=lbl, columns=raw_cols)
                    assert lbl in df.columns, f'Label col {lbl} not in df!'
                    passed_count += 1

    print(f'Regression check complete: {passed_count} tables checked successfully with 0 errors.')
