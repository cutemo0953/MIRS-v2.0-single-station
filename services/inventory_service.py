"""
統一的庫存服務層
使用 ABC 模式設計抽象基類與具體實作
"""

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any
import uuid


class InventoryService(ABC):
    """
    庫存服務抽象基類
    定義通用的庫存管理介面
    """

    def __init__(self, db_path: str):
        """
        初始化服務

        Args:
            db_path: 資料庫路徑
        """
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        """取得資料庫連接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @abstractmethod
    def _get_table_name(self) -> str:
        """
        取得主表格名稱（抽象方法）

        Returns:
            表格名稱
        """
        pass

    @abstractmethod
    def _get_id_column(self) -> str:
        """
        取得ID欄位名稱（抽象方法）

        Returns:
            ID欄位名稱
        """
        pass

    @abstractmethod
    def _get_transaction_table(self) -> str:
        """
        取得交易表格名稱（抽象方法）

        Returns:
            交易表格名稱
        """
        pass

    def calculate_coverage_days(self, item_id: str) -> float:
        """
        計算可支撐天數

        Args:
            item_id: 物品/藥品ID

        Returns:
            可支撐天數，如果 baseline_qty_7days 為 0 則返回 0
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        table_name = self._get_table_name()
        id_column = self._get_id_column()

        cursor.execute(
            f"SELECT current_stock, baseline_qty_7days FROM {table_name} WHERE {id_column} = ?",
            (item_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            raise ValueError(f"找不到物品: {item_id}")

        current_stock = row['current_stock'] or 0
        baseline_qty_7days = row['baseline_qty_7days'] or 0

        if baseline_qty_7days == 0:
            return 0.0

        # coverage_days = current_quantity / (baseline_qty_7days / 7.0)
        coverage_days = current_stock / (baseline_qty_7days / 7.0)

        return coverage_days

    def create_transaction(
        self,
        item_id: str,
        transaction_type: str,
        quantity: int,
        operator: str,
        **kwargs
    ) -> str:
        """
        創建交易記錄（抽象方法，子類實作）

        Args:
            item_id: 物品/藥品ID
            transaction_type: 交易類型 (IN/OUT/TRANSFER/ADJUST/RETURN)
            quantity: 數量
            operator: 操作人員
            **kwargs: 其他參數

        Returns:
            交易ID
        """
        raise NotImplementedError("子類必須實作 create_transaction 方法")

    def get_item_info(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        取得物品資訊

        Args:
            item_id: 物品/藥品ID

        Returns:
            物品資訊字典，如果不存在則返回 None
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        table_name = self._get_table_name()
        id_column = self._get_id_column()

        cursor.execute(f"SELECT * FROM {table_name} WHERE {id_column} = ?", (item_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def update_stock(self, item_id: str, quantity_change: int) -> bool:
        """
        更新庫存數量

        Args:
            item_id: 物品/藥品ID
            quantity_change: 數量變化（正數為增加，負數為減少）

        Returns:
            是否成功
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        table_name = self._get_table_name()
        id_column = self._get_id_column()

        # 更新庫存
        cursor.execute(
            f"UPDATE {table_name} SET current_stock = current_stock + ? WHERE {id_column} = ?",
            (quantity_change, item_id)
        )

        success = cursor.rowcount > 0
        conn.commit()
        conn.close()

        return success


class PharmacyService(InventoryService):
    """
    藥局服務
    處理藥品庫存與交易，包含管制藥品的特殊邏輯
    """

    VALID_OPERATOR_ROLES = ['PHARMACIST', 'NURSE', 'PHYSICIAN']

    def _get_table_name(self) -> str:
        return "medicines"

    def _get_id_column(self) -> str:
        return "medicine_code"

    def _get_transaction_table(self) -> str:
        return "pharmacy_transactions"

    def create_transaction(
        self,
        item_id: str,
        transaction_type: str,
        quantity: int,
        operator: str,
        **kwargs
    ) -> str:
        """
        創建藥品交易記錄

        Args:
            item_id: 藥品代碼
            transaction_type: 交易類型 (IN/OUT/TRANSFER/ADJUST/RETURN)
            quantity: 數量
            operator: 操作人員
            **kwargs: 其他參數
                - operator_role: 操作人員角色（必填）
                - verified_by: 核驗人員（管制藥必填）
                - station_code: 站點代碼
                - remarks: 備註
                - patient_id: 病患ID
                - patient_name: 病患姓名

        Returns:
            交易ID

        Raises:
            ValueError: 參數驗證失敗
        """
        # 驗證 operator_role
        operator_role = kwargs.get('operator_role')
        if not operator_role:
            raise ValueError("operator_role 為必填欄位")
        if operator_role not in self.VALID_OPERATOR_ROLES:
            raise ValueError(f"operator_role 必須是 {', '.join(self.VALID_OPERATOR_ROLES)} 之一")

        # 取得藥品資訊
        medicine_info = self.get_item_info(item_id)
        if not medicine_info:
            raise ValueError(f"找不到藥品: {item_id}")

        is_controlled = medicine_info.get('is_controlled_drug', 0)
        verified_by = kwargs.get('verified_by')

        # 管制藥必須有 verified_by（雙人簽核）
        if is_controlled and not verified_by:
            raise ValueError("管制藥品交易必須提供 verified_by（雙人簽核）")

        # 生成交易ID
        transaction_id = f"PT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"

        # 計算庫存變化
        if transaction_type in ['IN', 'RETURN']:
            quantity_change = quantity
        elif transaction_type in ['OUT', 'TRANSFER']:
            quantity_change = -quantity
        elif transaction_type == 'ADJUST':
            # ADJUST 可以是正數或負數
            quantity_change = kwargs.get('quantity_change', quantity)
        else:
            raise ValueError(f"不支援的交易類型: {transaction_type}")

        # 取得當前庫存（用於管制藥品記錄）
        current_stock = medicine_info.get('current_stock', 0)
        balance_before = current_stock
        balance_after = current_stock + quantity_change

        # 檢查庫存是否足夠
        if balance_after < 0:
            raise ValueError(f"庫存不足：當前 {balance_before}，需要 {abs(quantity_change)}")

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 取得站點資訊
            cursor.execute("SELECT station_code FROM station_metadata LIMIT 1")
            station_row = cursor.fetchone()
            station_code = kwargs.get('station_code') or (station_row['station_code'] if station_row else 'UNKNOWN')

            # 插入交易記錄
            cursor.execute("""
                INSERT INTO pharmacy_transactions (
                    transaction_id, transaction_type, transaction_date,
                    medicine_code, generic_name, brand_name,
                    is_controlled_drug, controlled_level,
                    quantity, unit, station_code,
                    operator, operator_role, verified_by,
                    patient_id, patient_name,
                    remarks, status, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction_id,
                transaction_type,
                datetime.now().isoformat(),
                item_id,
                medicine_info.get('generic_name', ''),
                medicine_info.get('brand_name', ''),
                is_controlled,
                medicine_info.get('controlled_level'),
                quantity,
                medicine_info.get('unit', ''),
                station_code,
                operator,
                operator_role,
                verified_by,
                kwargs.get('patient_id'),
                kwargs.get('patient_name'),
                kwargs.get('remarks'),
                'COMPLETED',
                operator
            ))

            # 更新庫存
            cursor.execute(
                "UPDATE medicines SET current_stock = current_stock + ? WHERE medicine_code = ?",
                (quantity_change, item_id)
            )

            # 注意：controlled_drug_log 會由資料庫 trigger 自動處理

            conn.commit()
            return transaction_id

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()


class GeneralInventoryService(InventoryService):
    """
    一般庫存服務
    處理衛材、設備、試劑等非藥品物資的庫存與交易
    """

    def _get_table_name(self) -> str:
        return "items"

    def _get_id_column(self) -> str:
        return "item_code"

    def _get_transaction_table(self) -> str:
        return "transactions"

    def create_transaction(
        self,
        item_id: str,
        transaction_type: str,
        quantity: int,
        operator: str,
        **kwargs
    ) -> str:
        """
        創建一般庫存交易記錄

        Args:
            item_id: 物品代碼
            transaction_type: 交易類型 (IN/OUT/TRANSFER/ADJUST/RETURN)
            quantity: 數量
            operator: 操作人員
            **kwargs: 其他參數
                - station_code: 站點代碼
                - from_station: 來源站點（調撥用）
                - to_station: 目標站點（調撥用）
                - remarks: 備註
                - reason: 交易原因
                - purpose: 用途

        Returns:
            交易ID

        Raises:
            ValueError: 參數驗證失敗
        """
        # 取得物品資訊
        item_info = self.get_item_info(item_id)
        if not item_info:
            raise ValueError(f"找不到物品: {item_id}")

        # 生成交易ID
        transaction_id = f"GT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"

        # 計算庫存變化
        if transaction_type in ['IN', 'RETURN']:
            quantity_change = quantity
        elif transaction_type in ['OUT', 'TRANSFER']:
            quantity_change = -quantity
        elif transaction_type == 'ADJUST':
            quantity_change = kwargs.get('quantity_change', quantity)
        else:
            raise ValueError(f"不支援的交易類型: {transaction_type}")

        # 檢查庫存是否足夠
        current_stock = item_info.get('current_stock', 0)
        if current_stock + quantity_change < 0:
            raise ValueError(f"庫存不足：當前 {current_stock}，需要 {abs(quantity_change)}")

        conn = self._get_connection()
        cursor = conn.cursor()

        try:
            # 取得站點資訊
            cursor.execute("SELECT station_code FROM station_metadata LIMIT 1")
            station_row = cursor.fetchone()
            station_code = kwargs.get('station_code') or (station_row['station_code'] if station_row else 'UNKNOWN')

            # 插入交易記錄
            cursor.execute("""
                INSERT INTO transactions (
                    transaction_id, transaction_type, transaction_date,
                    item_code, item_name, item_category,
                    quantity, unit, station_code,
                    from_station, to_station,
                    operator, reason, purpose, remarks,
                    status, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction_id,
                transaction_type,
                datetime.now().isoformat(),
                item_id,
                item_info.get('item_name', ''),
                item_info.get('item_category', ''),
                quantity,
                item_info.get('unit', ''),
                station_code,
                kwargs.get('from_station'),
                kwargs.get('to_station'),
                operator,
                kwargs.get('reason'),
                kwargs.get('purpose'),
                kwargs.get('remarks'),
                'COMPLETED',
                operator
            ))

            # 更新庫存
            cursor.execute(
                "UPDATE items SET current_stock = current_stock + ? WHERE item_code = ?",
                (quantity_change, item_id)
            )

            conn.commit()
            return transaction_id

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()


# 導出所有公開介面
__all__ = [
    'InventoryService',
    'PharmacyService',
    'GeneralInventoryService'
]
