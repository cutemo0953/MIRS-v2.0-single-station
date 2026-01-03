#!/usr/bin/env python3
"""
健保手術碼合併腳本
==================

將 ChatGPT 萃取的健保第七節手術碼合併到 MIRS surgery_codes 表

Usage:
    python3 scripts/merge_nhi_surgery_codes.py

功能：
1. 讀取 data/packs/nhi_sec7/sec7_surgery_codes_points.csv
2. 與現有 surgery_codes 表合併
3. 保留原有 is_common=1 標記
4. 輸出統計報告
"""

import csv
import sqlite3
import json
from pathlib import Path
from datetime import datetime


# =============================================================================
# Configuration
# =============================================================================

MIRS_DIR = Path(__file__).parent.parent
DB_PATH = MIRS_DIR / "medical_inventory.db"
NHI_CSV = MIRS_DIR / "data" / "packs" / "nhi_sec7" / "sec7_surgery_codes_points.csv"


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 60)
    print("健保手術碼合併工具")
    print("=" * 60)

    # 檢查檔案
    if not NHI_CSV.exists():
        print(f"❌ CSV 檔案不存在: {NHI_CSV}")
        return 1

    if not DB_PATH.exists():
        print(f"❌ 資料庫不存在: {DB_PATH}")
        return 1

    # 連接資料庫
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1. 取得現有資料統計
    print("\n📊 現有資料統計:")
    cur.execute("SELECT COUNT(*) as total, SUM(is_common) as common FROM surgery_codes")
    row = cur.fetchone()
    existing_total = row['total']
    existing_common = row['common'] or 0
    print(f"   surgery_codes: {existing_total} 筆 (is_common=1: {existing_common})")

    # 取得現有 code 列表
    cur.execute("SELECT code, points, is_common FROM surgery_codes")
    existing_codes = {r['code']: {'points': r['points'], 'is_common': r['is_common']} for r in cur.fetchall()}

    # 2. 讀取 NHI CSV
    print(f"\n📄 讀取 NHI 資料: {NHI_CSV.name}")
    nhi_records = []
    with open(NHI_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nhi_records.append({
                'code': row['code'].strip(),
                'points': int(row['points']),
                'name': row['name'].strip(),
                'group': row.get('group', '').strip(),
                'subgroup': row.get('subgroup', '').strip()
            })
    print(f"   NHI 記錄: {len(nhi_records)} 筆")

    # 3. 分析差異
    print("\n🔍 分析差異:")

    new_codes = []
    updated_codes = []
    points_diff = []

    for rec in nhi_records:
        code = rec['code']
        if code not in existing_codes:
            new_codes.append(rec)
        else:
            existing = existing_codes[code]
            if existing['points'] != rec['points']:
                points_diff.append({
                    'code': code,
                    'old_points': existing['points'],
                    'new_points': rec['points']
                })

    print(f"   新增 code: {len(new_codes)}")
    print(f"   已存在 code: {len(nhi_records) - len(new_codes)}")
    print(f"   點數不一致: {len(points_diff)}")

    if points_diff:
        print("\n   ⚠️ 點數差異樣本 (最多 10 筆):")
        for diff in points_diff[:10]:
            print(f"      {diff['code']}: {diff['old_points']} → {diff['new_points']}")

    # 4. 合併資料
    print("\n📥 合併資料:")

    inserted = 0
    updated = 0

    for rec in nhi_records:
        code = rec['code']

        if code not in existing_codes:
            # 新增
            cur.execute("""
                INSERT INTO surgery_codes
                (code, name_zh, name_en, category_code, points, keywords, is_common, is_active, notes)
                VALUES (?, ?, '', ?, ?, ?, 0, 1, ?)
            """, (
                code,
                rec['name'],
                rec['subgroup'][:20] if rec['subgroup'] else '7',  # category_code
                rec['points'],
                rec['subgroup'],  # keywords
                f"NHI {rec['group']}"  # notes
            ))
            inserted += 1
        else:
            # 更新點數 (保留 is_common)
            # 只更新點數不一致的
            if existing_codes[code]['points'] != rec['points']:
                cur.execute("""
                    UPDATE surgery_codes
                    SET points = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE code = ?
                """, (rec['points'], code))
                updated += 1

    conn.commit()

    print(f"   新增: {inserted} 筆")
    print(f"   更新點數: {updated} 筆")

    # 5. 重建 FTS 索引
    print("\n🔄 重建 FTS 索引:")
    try:
        cur.execute("DELETE FROM surgery_codes_fts")
        cur.execute("""
            INSERT INTO surgery_codes_fts (rowid, code, name_zh, name_en, keywords)
            SELECT rowid, code, name_zh, name_en, keywords FROM surgery_codes
        """)
        conn.commit()
        print("   ✓ FTS 索引重建完成")
    except Exception as e:
        print(f"   ⚠️ FTS 重建失敗 (可忽略): {e}")

    # 6. 最終統計
    print("\n📊 最終統計:")
    cur.execute("SELECT COUNT(*) as total, SUM(is_common) as common FROM surgery_codes")
    row = cur.fetchone()
    final_total = row['total']
    final_common = row['common'] or 0
    print(f"   surgery_codes: {final_total} 筆")
    print(f"   is_common=1: {final_common} 筆 (骨科常用)")
    print(f"   is_common=0: {final_total - final_common} 筆 (NHI 完整)")

    # 點數範圍
    cur.execute("SELECT MIN(points) as min_pts, MAX(points) as max_pts FROM surgery_codes")
    row = cur.fetchone()
    print(f"   點數範圍: {row['min_pts']} ~ {row['max_pts']}")

    # 7. 取樣驗證
    print("\n✅ 取樣驗證:")
    cur.execute("""
        SELECT code, name_zh, points
        FROM surgery_codes
        WHERE code IN ('62001C', '64029B', '33126B')
    """)
    for row in cur.fetchall():
        print(f"   {row['code']}: {row['name_zh'][:30]}... ({row['points']} 點)")

    conn.close()

    print("\n" + "=" * 60)
    print("✅ 合併完成!")
    print("=" * 60)

    return 0


if __name__ == '__main__':
    exit(main())
