#!/usr/bin/env python3
"""
NHI 健保手術碼萃取器 (第七節)
===========================

從健保署 form4-001.pdf 萃取第七節手術碼 + 點數

Usage:
    python3 scripts/extract_nhi_surgery_codes.py --pdf /path/to/form4-001.pdf --out ./data/packs/nhi_sec7

Output:
    - nhi_surgery_codes_sec7.csv
    - nhi_surgery_codes_sec7.json

Requirements:
    pip install PyMuPDF

Based on ChatGPT's dev spec for Section 7 extraction.
"""

import argparse
import csv
import json
import re
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict

try:
    import fitz  # PyMuPDF
except ImportError:
    print("請先安裝 PyMuPDF: pip install PyMuPDF")
    exit(1)


# =============================================================================
# Constants
# =============================================================================

SEC7_START_MARKER = "第二部第二章第七節"
SEC8_START_MARKER = "第二部第二章第八節"

# 術式碼格式: 5 位數字 + 1 大寫英文
CODE_PATTERN = re.compile(r'^(\d{5}[A-Z])\s+')
CODE_ONLY = re.compile(r'^\d{5}[A-Z]$')

# 點數格式: 2-6 位純數字
POINTS_PATTERN = re.compile(r'^(\d{2,6})$')

# 排除模式: code 後接頓號（通常是敘述文字）
EXCLUDE_PATTERN = re.compile(r'\d{5}[A-Z][、，]')

# 章節標題模式
GROUP_PATTERN = re.compile(r'^第[一二三四五六七八九十]+[項款目]')


@dataclass
class SurgeryCode:
    code: str
    points: int
    name: str
    group: str = ""
    subgroup: str = ""
    page: int = 0


# =============================================================================
# Section 7 Boundary Detection
# =============================================================================

def find_section7_pages(doc: fitz.Document) -> tuple[int, int]:
    """
    找出第七節的頁面範圍

    Returns:
        (start_page, end_page) - 0-indexed
    """
    sec7_pages = []
    sec8_pages = []

    for page_num in range(len(doc)):
        text = doc[page_num].get_text()
        if SEC7_START_MARKER in text:
            sec7_pages.append(page_num)
        if SEC8_START_MARKER in text:
            sec8_pages.append(page_num)

    # 忽略目錄頁 (通常在前 10 頁)
    # 取第七節標記中，頁碼最大的連續區段
    sec7_start = max(p for p in sec7_pages if p > 10) if any(p > 10 for p in sec7_pages) else min(sec7_pages)

    # 第八節開始頁 (大於 sec7_start 的最小值)
    sec8_candidates = [p for p in sec8_pages if p > sec7_start]
    sec7_end = min(sec8_candidates) - 1 if sec8_candidates else len(doc) - 1

    return sec7_start, sec7_end


# =============================================================================
# Row Extraction State Machine
# =============================================================================

def extract_codes_from_pages(doc: fitz.Document, start_page: int, end_page: int) -> List[SurgeryCode]:
    """
    從指定頁面範圍萃取術式碼

    使用狀態機處理 PDF 跨行/欄位錯位問題
    """
    results: List[SurgeryCode] = []

    current_group = ""
    current_subgroup = ""

    for page_num in range(start_page, end_page + 1):
        page = doc[page_num]
        text = page.get_text()
        lines = text.split('\n')

        pending_row: Optional[Dict[str, Any]] = None
        last_points_candidate: Optional[int] = None
        lines_since_pending = 0
        lines_since_points = 0
        prev_line = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 檢查章節標題
            if GROUP_PATTERN.match(line):
                if "項" in line:
                    current_group = line
                    current_subgroup = ""
                elif "款" in line or "目" in line:
                    current_subgroup = line

            # 排除敘述段落中的 code
            if EXCLUDE_PATTERN.search(line):
                prev_line = line
                continue

            # 嘗試匹配 code 行
            code_match = CODE_PATTERN.match(line)
            if code_match:
                code = code_match.group(1)
                # 取 code 後面的文字作為名稱
                name = line[code_match.end():].strip()
                # 清理名稱中的點數 (如果混在一起)
                name = re.sub(r'\s+\d{2,6}$', '', name).strip()

                # 檢查是否有 lastPointsCandidate 可用 (點數在 code 之前的情況)
                if last_points_candidate and lines_since_points <= 4:
                    results.append(SurgeryCode(
                        code=code,
                        points=last_points_candidate,
                        name=name,
                        group=current_group,
                        subgroup=current_subgroup,
                        page=page_num + 1
                    ))
                    last_points_candidate = None
                else:
                    # 儲存為 pending，等待點數
                    pending_row = {
                        'code': code,
                        'name': name,
                        'group': current_group,
                        'subgroup': current_subgroup,
                        'page': page_num + 1
                    }
                    lines_since_pending = 0

                prev_line = line
                continue

            # 嘗試匹配點數行
            points_match = POINTS_PATTERN.match(line)
            if points_match:
                points = int(points_match.group(1))

                # 檢查是否符合綁定條件
                if pending_row and lines_since_pending <= 8:
                    # 檢查前一行是否有 'v' (PDF 表格分隔符)
                    # 或者直接接在 code 行後面
                    if 'v' in prev_line.lower() or 'ｖ' in prev_line or lines_since_pending <= 2:
                        results.append(SurgeryCode(
                            code=pending_row['code'],
                            points=points,
                            name=pending_row['name'],
                            group=pending_row['group'],
                            subgroup=pending_row['subgroup'],
                            page=pending_row['page']
                        ))
                        pending_row = None
                    else:
                        # 可能是點數在 code 之前的情況
                        last_points_candidate = points
                        lines_since_points = 0
                else:
                    last_points_candidate = points
                    lines_since_points = 0

            # 更新計數器
            if pending_row:
                lines_since_pending += 1
            if last_points_candidate:
                lines_since_points += 1

            prev_line = line

    return results


# =============================================================================
# Deduplication & Normalization
# =============================================================================

def deduplicate_codes(codes: List[SurgeryCode]) -> List[SurgeryCode]:
    """
    去重：同一 code 保留名稱最長的一筆
    檢查點數一致性
    """
    by_code: Dict[str, List[SurgeryCode]] = {}

    for c in codes:
        if c.code not in by_code:
            by_code[c.code] = []
        by_code[c.code].append(c)

    results = []
    inconsistent = []

    for code, entries in by_code.items():
        # 檢查點數一致性
        points_set = set(e.points for e in entries)
        if len(points_set) > 1:
            inconsistent.append((code, points_set))

        # 取名稱最長的
        best = max(entries, key=lambda e: len(e.name))
        results.append(best)

    if inconsistent:
        print(f"⚠️ 發現 {len(inconsistent)} 個 code 有不一致的點數:")
        for code, pts in inconsistent[:5]:
            print(f"   {code}: {pts}")
        if len(inconsistent) > 5:
            print(f"   ... 還有 {len(inconsistent) - 5} 個")

    return sorted(results, key=lambda c: c.code)


# =============================================================================
# Output Writers
# =============================================================================

def write_csv(codes: List[SurgeryCode], path: Path):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['code', 'points', 'name', 'group', 'subgroup'])
        writer.writeheader()
        for c in codes:
            writer.writerow({
                'code': c.code,
                'points': c.points,
                'name': c.name,
                'group': c.group,
                'subgroup': c.subgroup
            })


def write_json(codes: List[SurgeryCode], path: Path):
    data = [asdict(c) for c in codes]
    # 移除 page 欄位
    for d in data:
        d.pop('page', None)

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compute_hash(path: Path) -> str:
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='NHI 健保手術碼萃取器 (第七節)')
    parser.add_argument('--pdf', required=True, help='form4-001.pdf 路徑')
    parser.add_argument('--out', default='./data/packs/nhi_sec7', help='輸出目錄')
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not pdf_path.exists():
        print(f"❌ PDF 檔案不存在: {pdf_path}")
        return 1

    print(f"📄 開啟 PDF: {pdf_path}")
    doc = fitz.open(pdf_path)
    print(f"   總頁數: {len(doc)}")

    # 找第七節範圍
    print("\n🔍 定位第七節範圍...")
    start_page, end_page = find_section7_pages(doc)
    print(f"   第七節: 第 {start_page + 1} 頁 ~ 第 {end_page + 1} 頁 ({end_page - start_page + 1} 頁)")

    # 萃取
    print("\n📊 萃取術式碼...")
    raw_codes = extract_codes_from_pages(doc, start_page, end_page)
    print(f"   原始筆數: {len(raw_codes)}")

    # 去重
    print("\n🔄 去重與正規化...")
    unique_codes = deduplicate_codes(raw_codes)
    print(f"   唯一 code: {len(unique_codes)}")

    # 驗收測試
    print("\n✅ 驗收測試...")
    all_valid = all(CODE_ONLY.match(c.code) for c in unique_codes)
    print(f"   code 格式正確: {'✓' if all_valid else '✗'}")
    print(f"   數量 > 1000: {'✓' if len(unique_codes) > 1000 else '✗'} ({len(unique_codes)})")

    # 輸出
    print("\n💾 寫入檔案...")
    csv_path = out_dir / 'nhi_surgery_codes_sec7.csv'
    json_path = out_dir / 'nhi_surgery_codes_sec7.json'

    write_csv(unique_codes, csv_path)
    write_json(unique_codes, json_path)

    csv_hash = compute_hash(csv_path)
    json_hash = compute_hash(json_path)

    print(f"   {csv_path} (SHA256: {csv_hash})")
    print(f"   {json_path} (SHA256: {json_hash})")

    # Summary
    print("\n" + "="*50)
    print("📋 Summary")
    print("="*50)
    print(f"   PDF: {pdf_path.name}")
    print(f"   Pages: {start_page + 1} - {end_page + 1}")
    print(f"   Unique codes: {len(unique_codes)}")
    print(f"   Groups: {len(set(c.group for c in unique_codes if c.group))}")

    # 點數統計
    points_list = [c.points for c in unique_codes]
    print(f"   Points range: {min(points_list)} - {max(points_list)}")

    doc.close()
    return 0


if __name__ == '__main__':
    exit(main())
