"""
MIRS Surgery Codes & Self-Pay Items API
Version: 1.0.0

提供:
1. 術式代碼 CRUD + FTS5 搜尋
2. 自費項目 CRUD + FTS5 搜尋
3. 分類對照表管理
4. 點數計算 API
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/surgery-codes", tags=["surgery-codes"])


# =============================================================================
# Pydantic Models
# =============================================================================

class SurgeryCategory(BaseModel):
    category_code: str
    category_name: str
    code_range: Optional[str] = None
    notes: Optional[str] = None
    is_active: int = 1


class SurgeryCode(BaseModel):
    code: str
    name_zh: str
    name_en: Optional[str] = None
    category_code: str
    points: int = 0
    keywords: Optional[str] = None
    is_common: int = 0
    is_active: int = 1
    notes: Optional[str] = None


class SurgeryCodeCreate(BaseModel):
    code: str = Field(..., max_length=20)
    name_zh: str = Field(..., max_length=200)
    name_en: Optional[str] = None
    category_code: str = Field(..., max_length=10)
    points: int = Field(default=0, ge=0)
    keywords: Optional[str] = None
    is_common: bool = False
    notes: Optional[str] = None


class SurgeryCodeUpdate(BaseModel):
    name_zh: Optional[str] = None
    name_en: Optional[str] = None
    category_code: Optional[str] = None
    points: Optional[int] = Field(None, ge=0)
    keywords: Optional[str] = None
    is_common: Optional[bool] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class SelfPayItem(BaseModel):
    item_id: str
    name: str
    category: str
    unit_price: float = 0
    unit: str = "組"
    is_common: int = 0
    display_order: int = 0
    is_active: int = 1
    notes: Optional[str] = None


class SelfPayItemCreate(BaseModel):
    item_id: str = Field(..., max_length=50)
    name: str = Field(..., max_length=200)
    category: str = Field(..., max_length=100)
    unit_price: float = Field(default=0, ge=0)
    unit: str = Field(default="組", max_length=20)
    is_common: bool = False
    display_order: int = Field(default=0, ge=0)
    notes: Optional[str] = None


class SelfPayItemUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit_price: Optional[float] = Field(None, ge=0)
    unit: Optional[str] = None
    is_common: Optional[bool] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class PointsCalculationItem(BaseModel):
    """點數計算項目"""
    code: str
    name: str
    points: int
    category_code: Optional[str] = None  # 用於判斷同類/不同類遞減


class PointsCalculationRequest(BaseModel):
    """點數計算請求"""
    surgeries: List[PointsCalculationItem]
    apply_reduction: bool = True


class PointsCalculationResult(BaseModel):
    """點數計算結果項目"""
    code: str
    name: str
    sequence: int
    original_points: int
    reduction_rate: float
    final_points: int


class PointsCalculationResponse(BaseModel):
    """點數計算回應"""
    items: List[PointsCalculationResult]
    total_original_points: int
    total_final_points: int
    reduction_applied: bool


# =============================================================================
# Database Helper
# =============================================================================

def get_db_connection():
    """Get database connection from main"""
    from main import db
    return db.get_connection()


# =============================================================================
# Schema Initialization (called from main.py on startup)
# =============================================================================

def init_surgery_codes_schema(cursor):
    """
    Initialize surgery codes schema and seed data if empty.
    Called from main.py during database initialization.
    """
    from pathlib import Path

    # 1. Run migration SQL using executescript (handles multi-statement SQL properly)
    migration_path = Path(__file__).parent.parent / "database" / "migrations" / "add_surgery_codes_selfpay.sql"

    if migration_path.exists():
        logger.info("Running surgery codes migration...")
        with open(migration_path, 'r', encoding='utf-8') as f:
            migration_sql = f.read()

        try:
            # executescript handles multiple statements including CREATE TRIGGER
            cursor.connection.executescript(migration_sql)
            logger.info("✓ Surgery codes schema initialized")
        except Exception as e:
            # Log but continue - tables might already exist
            if "already exists" not in str(e).lower():
                logger.warning(f"Migration warning: {e}")
    else:
        logger.warning(f"Migration file not found: {migration_path}")
        return

    # 2. Check if data needs seeding
    try:
        cursor.execute("SELECT COUNT(*) FROM surgery_codes")
        code_count = cursor.fetchone()[0]
    except Exception:
        # Table might not exist yet
        code_count = 0

    if code_count == 0:
        logger.info("Surgery codes table empty, seeding from data pack...")
        _seed_surgery_data(cursor)
    else:
        logger.info(f"Surgery codes table has {code_count} records, skipping seed")


def _parse_bool(value) -> int:
    """Parse boolean-like value to int (0 or 1)."""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.upper() in ('TRUE', 'YES', '1', 'Y') else 0
    return 0


def _seed_surgery_data(cursor):
    """Seed surgery codes data from data/packs CSV files."""
    import csv
    from pathlib import Path

    pack_dir = Path(__file__).parent.parent / "data" / "packs"

    # Find CSV files
    categories_csv = None
    codes_csv = None
    selfpay_csv = None

    for f in pack_dir.glob("*.csv"):
        fname = f.name.lower()
        if "categories" in fname:
            categories_csv = f
        elif "surgeries" in fname or "surgery_codes" in fname:
            codes_csv = f
        elif "selfpay" in fname:
            selfpay_csv = f

    # 1. Import categories
    if categories_csv and categories_csv.exists():
        with open(categories_csv, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO surgery_categories
                        (category_code, category_name, code_range, notes)
                        VALUES (?, ?, ?, ?)
                    """, (
                        row.get('category_code', '').strip(),
                        row.get('category_name', '').strip(),
                        row.get('code_range', '').strip(),
                        row.get('notes', '').strip()
                    ))
                    count += 1
                except Exception as e:
                    logger.warning(f"Category import error: {e}")
            cursor.connection.commit()
            logger.info(f"✓ Imported {count} surgery categories")

    # 2. Import surgery codes
    if codes_csv and codes_csv.exists():
        with open(codes_csv, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO surgery_codes
                        (code, name_zh, name_en, category_code, points, keywords, is_common, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('code', '').strip(),
                        row.get('name_zh', '').strip(),
                        row.get('name_en', '').strip(),
                        row.get('category_code', row.get('category', '')).strip(),
                        int(row.get('points', 0) or 0),
                        row.get('keywords', '').strip(),
                        _parse_bool(row.get('is_common', 0)),
                        row.get('notes', '').strip()
                    ))
                    count += 1
                except Exception as e:
                    logger.warning(f"Surgery code import error: {e}")
            cursor.connection.commit()
            logger.info(f"✓ Imported {count} surgery codes")

    # 3. Import self-pay items
    if selfpay_csv and selfpay_csv.exists():
        with open(selfpay_csv, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    cursor.execute("""
                        INSERT OR IGNORE INTO selfpay_items
                        (item_id, name, category, unit_price, unit, is_common, display_order, notes)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        row.get('item_id', '').strip(),
                        row.get('name', '').strip(),
                        row.get('category', '').strip(),
                        float(row.get('unit_price', 0) or 0),
                        row.get('unit', '組').strip(),
                        _parse_bool(row.get('is_common', 0)),
                        int(row.get('display_order', 0) or 0),
                        row.get('notes', '').strip()
                    ))
                    count += 1
                except Exception as e:
                    logger.warning(f"Self-pay item import error: {e}")
            cursor.connection.commit()
            logger.info(f"✓ Imported {count} self-pay items")

    # 4. Import NHI Section 7 surgery codes (additional)
    nhi_csv = pack_dir / "nhi_sec7" / "sec7_surgery_codes_points.csv"
    if nhi_csv.exists():
        logger.info("Importing NHI Section 7 surgery codes...")
        with open(nhi_csv, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                try:
                    # Use name as name_zh, subgroup as keywords
                    cursor.execute("""
                        INSERT OR IGNORE INTO surgery_codes
                        (code, name_zh, name_en, category_code, points, keywords, is_common, notes)
                        VALUES (?, ?, '', ?, ?, ?, 0, ?)
                    """, (
                        row.get('code', '').strip(),
                        row.get('name', '').strip(),
                        row.get('subgroup', '')[:20] if row.get('subgroup') else '7',
                        int(row.get('points', 0) or 0),
                        row.get('subgroup', '').strip(),
                        f"NHI {row.get('group', '')}"
                    ))
                    count += 1
                except Exception as e:
                    logger.warning(f"NHI surgery code import error: {e}")
            cursor.connection.commit()
            logger.info(f"✓ Imported {count} NHI surgery codes")

    # 5. Rebuild FTS index
    try:
        cursor.execute("DELETE FROM surgery_codes_fts")
        cursor.execute("""
            INSERT INTO surgery_codes_fts (rowid, code, name_zh, name_en, keywords)
            SELECT rowid, code, name_zh, name_en, keywords FROM surgery_codes
        """)
        cursor.connection.commit()
        logger.info("✓ FTS index rebuilt")
    except Exception as e:
        logger.warning(f"FTS rebuild warning: {e}")


# =============================================================================
# Surgery Categories Endpoints
# =============================================================================

@router.get("/categories")
async def get_surgery_categories(include_inactive: bool = False):
    """取得手術分類列表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if include_inactive:
            cursor.execute("SELECT * FROM surgery_categories ORDER BY category_code")
        else:
            cursor.execute("SELECT * FROM surgery_categories WHERE is_active = 1 ORDER BY category_code")

        rows = cursor.fetchall()
        categories = [dict(row) for row in rows]

        return {"categories": categories, "count": len(categories)}

    except Exception as e:
        logger.error(f"Error fetching categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =============================================================================
# Surgery Codes Endpoints
# =============================================================================

@router.get("/codes")
async def get_surgery_codes(
    category: Optional[str] = None,
    is_common: Optional[bool] = None,
    include_inactive: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """取得術式代碼列表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = "SELECT * FROM surgery_codes WHERE 1=1"
        params = []

        if not include_inactive:
            query += " AND is_active = 1"

        if category:
            query += " AND category_code = ?"
            params.append(category)

        if is_common is not None:
            query += " AND is_common = ?"
            params.append(1 if is_common else 0)

        query += " ORDER BY is_common DESC, points DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        codes = [dict(row) for row in rows]

        # Get total count
        count_query = "SELECT COUNT(*) FROM surgery_codes WHERE 1=1"
        count_params = []
        if not include_inactive:
            count_query += " AND is_active = 1"
        if category:
            count_query += " AND category_code = ?"
            count_params.append(category)
        if is_common is not None:
            count_query += " AND is_common = ?"
            count_params.append(1 if is_common else 0)

        cursor.execute(count_query, count_params)
        total = cursor.fetchone()[0]

        return {"codes": codes, "count": len(codes), "total": total}

    except Exception as e:
        logger.error(f"Error fetching surgery codes: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/codes/search")
async def search_surgery_codes(
    q: str = Query(..., min_length=1, description="搜尋關鍵字"),
    category: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """FTS5 全文搜尋術式代碼"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # 建立 FTS5 搜尋查詢
        # 支援前綴搜尋 (e.g., "骨折*")
        search_term = q.strip()
        if not search_term.endswith('*'):
            search_term = f'"{search_term}"*'

        query = """
            SELECT s.*, bm25(surgery_codes_fts) as relevance
            FROM surgery_codes s
            JOIN surgery_codes_fts fts ON s.rowid = fts.rowid
            WHERE surgery_codes_fts MATCH ?
            AND s.is_active = 1
        """
        params = [search_term]

        if category:
            query += " AND s.category_code = ?"
            params.append(category)

        query += " ORDER BY s.is_common DESC, relevance LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        codes = [dict(row) for row in rows]

        return {"codes": codes, "count": len(codes), "query": q}

    except Exception as e:
        logger.error(f"Error searching surgery codes: {e}")
        # Fallback to LIKE search if FTS fails
        try:
            like_term = f"%{q}%"
            query = """
                SELECT * FROM surgery_codes
                WHERE is_active = 1 AND (
                    code LIKE ? OR name_zh LIKE ? OR name_en LIKE ? OR keywords LIKE ?
                )
            """
            params = [like_term, like_term, like_term, like_term]

            if category:
                query += " AND category_code = ?"
                params.append(category)

            query += " ORDER BY is_common DESC, points DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            codes = [dict(row) for row in rows]

            return {"codes": codes, "count": len(codes), "query": q, "fallback": True}

        except Exception as e2:
            raise HTTPException(status_code=500, detail=str(e2))
    finally:
        conn.close()


@router.get("/codes/common")
async def get_common_surgery_codes(limit: int = Query(20, ge=1, le=100)):
    """取得常用術式代碼"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT * FROM surgery_codes
            WHERE is_active = 1 AND is_common = 1
            ORDER BY points DESC
            LIMIT ?
        """, (limit,))

        rows = cursor.fetchall()
        codes = [dict(row) for row in rows]

        return {"codes": codes, "count": len(codes)}

    except Exception as e:
        logger.error(f"Error fetching common codes: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/codes/{code}")
async def get_surgery_code(code: str):
    """取得單一術式代碼"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM surgery_codes WHERE code = ?", (code,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Surgery code not found: {code}")

        return dict(row)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching surgery code: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/codes")
async def create_surgery_code(data: SurgeryCodeCreate):
    """新增術式代碼"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO surgery_codes (code, name_zh, name_en, category_code, points, keywords, is_common, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.code,
            data.name_zh,
            data.name_en,
            data.category_code,
            data.points,
            data.keywords,
            1 if data.is_common else 0,
            data.notes
        ))
        conn.commit()

        return {"success": True, "code": data.code, "message": "Surgery code created"}

    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating surgery code: {e}")
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail=f"Surgery code already exists: {data.code}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.put("/codes/{code}")
async def update_surgery_code(code: str, data: SurgeryCodeUpdate):
    """更新術式代碼"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Build dynamic update
        updates = []
        params = []

        if data.name_zh is not None:
            updates.append("name_zh = ?")
            params.append(data.name_zh)
        if data.name_en is not None:
            updates.append("name_en = ?")
            params.append(data.name_en)
        if data.category_code is not None:
            updates.append("category_code = ?")
            params.append(data.category_code)
        if data.points is not None:
            updates.append("points = ?")
            params.append(data.points)
        if data.keywords is not None:
            updates.append("keywords = ?")
            params.append(data.keywords)
        if data.is_common is not None:
            updates.append("is_common = ?")
            params.append(1 if data.is_common else 0)
        if data.is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if data.is_active else 0)
        if data.notes is not None:
            updates.append("notes = ?")
            params.append(data.notes)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(code)
        query = f"UPDATE surgery_codes SET {', '.join(updates)} WHERE code = ?"

        cursor.execute(query, params)
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Surgery code not found: {code}")

        return {"success": True, "code": code, "message": "Surgery code updated"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating surgery code: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.delete("/codes/{code}")
async def delete_surgery_code(code: str):
    """刪除術式代碼 (軟刪除)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE surgery_codes SET is_active = 0 WHERE code = ?", (code,))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Surgery code not found: {code}")

        return {"success": True, "code": code, "message": "Surgery code deleted (soft)"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting surgery code: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =============================================================================
# Self-Pay Items Endpoints
# =============================================================================

@router.get("/selfpay")
async def get_selfpay_items(
    category: Optional[str] = None,
    is_common: Optional[bool] = None,
    include_inactive: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """取得自費項目列表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        query = "SELECT * FROM selfpay_items WHERE 1=1"
        params = []

        if not include_inactive:
            query += " AND is_active = 1"

        if category:
            query += " AND category = ?"
            params.append(category)

        if is_common is not None:
            query += " AND is_common = ?"
            params.append(1 if is_common else 0)

        query += " ORDER BY category, display_order LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(query, params)
        rows = cursor.fetchall()
        items = [dict(row) for row in rows]

        return {"items": items, "count": len(items)}

    except Exception as e:
        logger.error(f"Error fetching selfpay items: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/selfpay/search")
async def search_selfpay_items(
    q: str = Query(..., min_length=1, description="搜尋關鍵字"),
    category: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100)
):
    """FTS5 全文搜尋自費項目"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        search_term = q.strip()
        if not search_term.endswith('*'):
            search_term = f'"{search_term}"*'

        query = """
            SELECT s.*, bm25(selfpay_items_fts) as relevance
            FROM selfpay_items s
            JOIN selfpay_items_fts fts ON s.rowid = fts.rowid
            WHERE selfpay_items_fts MATCH ?
            AND s.is_active = 1
        """
        params = [search_term]

        if category:
            query += " AND s.category = ?"
            params.append(category)

        query += " ORDER BY s.is_common DESC, relevance LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)
        rows = cursor.fetchall()
        items = [dict(row) for row in rows]

        return {"items": items, "count": len(items), "query": q}

    except Exception as e:
        logger.error(f"Error searching selfpay items: {e}")
        # Fallback to LIKE search
        try:
            like_term = f"%{q}%"
            query = """
                SELECT * FROM selfpay_items
                WHERE is_active = 1 AND (
                    item_id LIKE ? OR name LIKE ? OR category LIKE ?
                )
            """
            params = [like_term, like_term, like_term]

            if category:
                query += " AND category = ?"
                params.append(category)

            query += " ORDER BY is_common DESC, unit_price DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            items = [dict(row) for row in rows]

            return {"items": items, "count": len(items), "query": q, "fallback": True}

        except Exception as e2:
            raise HTTPException(status_code=500, detail=str(e2))
    finally:
        conn.close()


@router.get("/selfpay/categories")
async def get_selfpay_categories():
    """取得自費項目分類列表"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT DISTINCT category, COUNT(*) as item_count
            FROM selfpay_items
            WHERE is_active = 1
            GROUP BY category
            ORDER BY category
        """)

        rows = cursor.fetchall()
        categories = [{"category": row[0], "item_count": row[1]} for row in rows]

        return {"categories": categories, "count": len(categories)}

    except Exception as e:
        logger.error(f"Error fetching selfpay categories: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/selfpay/{item_id}")
async def get_selfpay_item(item_id: str):
    """取得單一自費項目"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM selfpay_items WHERE item_id = ?", (item_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Self-pay item not found: {item_id}")

        return dict(row)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching selfpay item: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/selfpay")
async def create_selfpay_item(data: SelfPayItemCreate):
    """新增自費項目"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO selfpay_items (item_id, name, category, unit_price, unit, is_common, display_order, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.item_id,
            data.name,
            data.category,
            data.unit_price,
            data.unit,
            1 if data.is_common else 0,
            data.display_order,
            data.notes
        ))
        conn.commit()

        return {"success": True, "item_id": data.item_id, "message": "Self-pay item created"}

    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating selfpay item: {e}")
        if "UNIQUE constraint" in str(e):
            raise HTTPException(status_code=400, detail=f"Self-pay item already exists: {data.item_id}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.put("/selfpay/{item_id}")
async def update_selfpay_item(item_id: str, data: SelfPayItemUpdate):
    """更新自費項目"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        updates = []
        params = []

        if data.name is not None:
            updates.append("name = ?")
            params.append(data.name)
        if data.category is not None:
            updates.append("category = ?")
            params.append(data.category)
        if data.unit_price is not None:
            updates.append("unit_price = ?")
            params.append(data.unit_price)
        if data.unit is not None:
            updates.append("unit = ?")
            params.append(data.unit)
        if data.is_common is not None:
            updates.append("is_common = ?")
            params.append(1 if data.is_common else 0)
        if data.display_order is not None:
            updates.append("display_order = ?")
            params.append(data.display_order)
        if data.is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if data.is_active else 0)
        if data.notes is not None:
            updates.append("notes = ?")
            params.append(data.notes)

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        params.append(item_id)
        query = f"UPDATE selfpay_items SET {', '.join(updates)} WHERE item_id = ?"

        cursor.execute(query, params)
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Self-pay item not found: {item_id}")

        return {"success": True, "item_id": item_id, "message": "Self-pay item updated"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating selfpay item: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.delete("/selfpay/{item_id}")
async def delete_selfpay_item(item_id: str):
    """刪除自費項目 (軟刪除)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("UPDATE selfpay_items SET is_active = 0 WHERE item_id = ?", (item_id,))
        conn.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Self-pay item not found: {item_id}")

        return {"success": True, "item_id": item_id, "message": "Self-pay item deleted (soft)"}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting selfpay item: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# =============================================================================
# Points Calculation Endpoints (Phase 2)
# =============================================================================

@router.post("/calculate-points", response_model=PointsCalculationResponse)
async def calculate_surgery_points(request: PointsCalculationRequest):
    """
    計算多項手術點數 (含遞減規則)

    遞減規則 (依全民健康保險醫療服務給付項目及支付標準):
    - 術式依點數由高到低排列
    - 同類手術 (同 category_code): 100% → 50% → 50% → 0%
    - 不同類手術: 100% → 100% → 50% → 0%

    若未提供 category_code，使用簡易規則: 100% → 50% → 0%
    """
    if not request.surgeries:
        return PointsCalculationResponse(
            items=[],
            total_original_points=0,
            total_final_points=0,
            reduction_applied=request.apply_reduction
        )

    # 按點數降序排列 (最高點數的為主手術)
    sorted_surgeries = sorted(request.surgeries, key=lambda x: x.points, reverse=True)

    items = []
    total_original = 0
    total_final = 0
    categories_seen = set()  # 追蹤已出現的分類
    same_category_count = {}  # 追蹤每個分類出現的次數

    for idx, surgery in enumerate(sorted_surgeries):
        original = surgery.points
        total_original += original

        if request.apply_reduction:
            cat = surgery.category_code

            if cat is None:
                # 無分類資訊，使用簡易規則
                if idx == 0:
                    rate = 1.0
                elif idx == 1:
                    rate = 0.5
                else:
                    rate = 0.0
            else:
                # 有分類資訊，使用完整健保規則
                if idx == 0:
                    # 第一項永遠 100%
                    rate = 1.0
                elif cat in categories_seen:
                    # 同類手術：第2,3項 50%，第4項+ 0%
                    same_cat_order = same_category_count.get(cat, 0)
                    if same_cat_order < 3:  # 同類第2,3項 (count=1,2)
                        rate = 0.5
                    else:
                        rate = 0.0
                else:
                    # 不同類手術：第2項 100%，第3項 50%，第4項+ 0%
                    if idx == 1:
                        rate = 1.0
                    elif idx == 2:
                        rate = 0.5
                    else:
                        rate = 0.0

                # 更新計數
                categories_seen.add(cat)
                same_category_count[cat] = same_category_count.get(cat, 0) + 1
        else:
            rate = 1.0

        final = int(original * rate)
        total_final += final

        items.append(PointsCalculationResult(
            code=surgery.code,
            name=surgery.name,
            sequence=idx + 1,
            original_points=original,
            reduction_rate=rate,
            final_points=final
        ))

    return PointsCalculationResponse(
        items=items,
        total_original_points=total_original,
        total_final_points=total_final,
        reduction_applied=request.apply_reduction
    )


# =============================================================================
# Statistics Endpoints
# =============================================================================

@router.get("/stats")
async def get_surgery_codes_stats():
    """取得統計資訊"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        stats = {}

        # Surgery codes stats
        cursor.execute("SELECT COUNT(*) FROM surgery_codes WHERE is_active = 1")
        stats['surgery_codes_count'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM surgery_codes WHERE is_active = 1 AND is_common = 1")
        stats['surgery_codes_common'] = cursor.fetchone()[0]

        # Self-pay items stats
        cursor.execute("SELECT COUNT(*) FROM selfpay_items WHERE is_active = 1")
        stats['selfpay_items_count'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM selfpay_items WHERE is_active = 1 AND is_common = 1")
        stats['selfpay_items_common'] = cursor.fetchone()[0]

        # Categories stats
        cursor.execute("SELECT COUNT(*) FROM surgery_categories WHERE is_active = 1")
        stats['categories_count'] = cursor.fetchone()[0]

        # Last import info
        cursor.execute("SELECT * FROM master_data_imports ORDER BY applied_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            stats['last_import'] = dict(row)

        return stats

    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
