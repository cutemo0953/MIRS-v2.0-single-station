#!/usr/bin/env python3
"""
MIRS v1.4.2-plus - 預載資料庫
依據「急救站設置參考指引公開版本.pdf」衛生福利部建議清單
統一預載所有藥品/設備/耗材至 items 表
藥品使用 MED- 前綴，耗材使用原有代碼
"""

# ============================================================================
# 藥品清單 (使用 MED- 前綴，存入 items 表)
# ============================================================================

MEDICINES_DATA = [
    # ========== 急救藥品 (18種) - 附件四 ==========
    {'code': 'MED-EMER-001', 'name': 'Epinephrine 1:1000', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-002', 'name': 'Atropine 1mg/ml', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-003', 'name': 'Amiodarone 150mg', 'unit': 'Amp', 'min_stock': 10, 'category': '急救藥品'},
    {'code': 'MED-EMER-004', 'name': 'Adenosine 6mg', 'unit': 'Amp', 'min_stock': 10, 'category': '急救藥品'},
    {'code': 'MED-EMER-005', 'name': 'Lidocaine 2%', 'unit': 'Vial', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-006', 'name': 'Calcium Gluconate 10%', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-007', 'name': 'Sodium Bicarbonate 8.4%', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-008', 'name': 'Dextrose 50%', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-009', 'name': 'Naloxone 0.4mg', 'unit': 'Amp', 'min_stock': 10, 'category': '急救藥品'},
    {'code': 'MED-EMER-010', 'name': 'Flumazenil 0.5mg', 'unit': 'Amp', 'min_stock': 10, 'category': '急救藥品'},
    {'code': 'MED-EMER-011', 'name': 'Vasopressin 20U', 'unit': 'Amp', 'min_stock': 10, 'category': '急救藥品'},
    {'code': 'MED-EMER-012', 'name': 'Dopamine 200mg', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-013', 'name': 'Norepinephrine 4mg', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-014', 'name': 'Dobutamine 250mg', 'unit': 'Vial', 'min_stock': 10, 'category': '急救藥品'},
    {'code': 'MED-EMER-015', 'name': 'Hydrocortisone 100mg', 'unit': 'Vial', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-016', 'name': 'Diphenhydramine 30mg', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},
    {'code': 'MED-EMER-017', 'name': 'Nitroglycerin 0.6mg SL', 'unit': 'Tab', 'min_stock': 30, 'category': '急救藥品'},
    {'code': 'MED-EMER-018', 'name': 'Aspirin 100mg', 'unit': 'Tab', 'min_stock': 30, 'category': '急救藥品'},
    {'code': 'MED-EMER-019', 'name': 'Aminophylline 250mg/10ml', 'unit': 'Amp', 'min_stock': 20, 'category': '急救藥品'},

    # ========== 止痛/消炎/退燒藥 ==========
    {'code': 'MED-PAIN-001', 'name': 'Acetaminophen 500mg', 'unit': 'Tab', 'min_stock': 200, 'category': '常用藥品'},
    {'code': 'MED-PAIN-002', 'name': 'Ibuprofen 400mg', 'unit': 'Tab', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-PAIN-003', 'name': 'Diclofenac 25mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-PAIN-004', 'name': 'Ketorolac 30mg/ml', 'unit': 'Amp', 'min_stock': 30, 'category': '常用藥品'},
    {'code': 'MED-PAIN-005', 'name': 'Tramadol 50mg', 'unit': 'Cap', 'min_stock': 50, 'category': '管制藥品'},
    {'code': 'MED-PAIN-006', 'name': 'Morphine 10mg/ml', 'unit': 'Amp', 'min_stock': 20, 'category': '管制藥品'},
    {'code': 'MED-PAIN-007', 'name': 'Meperidine 50mg/ml', 'unit': 'Amp', 'min_stock': 20, 'category': '管制藥品'},
    {'code': 'MED-PAIN-008', 'name': 'Fentanyl 0.05mg/ml', 'unit': 'Amp', 'min_stock': 20, 'category': '管制藥品'},
    {'code': 'MED-PAIN-009', 'name': 'Nalbuphine 10mg/ml', 'unit': 'Amp', 'min_stock': 20, 'category': '常用藥品'},
    {'code': 'MED-PAIN-010', 'name': 'Celecoxib 200mg', 'unit': 'Cap', 'min_stock': 30, 'category': '常用藥品'},

    # ========== 呼吸道用藥 ==========
    {'code': 'MED-RESP-001', 'name': 'Salbutamol MDI 100mcg', 'unit': 'Inh', 'min_stock': 10, 'category': '常用藥品'},
    {'code': 'MED-RESP-002', 'name': 'Ipratropium MDI 20mcg', 'unit': 'Inh', 'min_stock': 10, 'category': '常用藥品'},
    {'code': 'MED-RESP-003', 'name': 'Dextromethorphan 15mg', 'unit': 'Tab', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-RESP-004', 'name': 'Ambroxol 30mg', 'unit': 'Tab', 'min_stock': 100, 'category': '常用藥品'},

    # ========== 消化道用藥 ==========
    {'code': 'MED-GI-001', 'name': 'Omeprazole 20mg', 'unit': 'Cap', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-GI-002', 'name': 'Ranitidine 150mg', 'unit': 'Tab', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-GI-003', 'name': 'Metoclopramide 10mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-GI-004', 'name': 'Metoclopramide 10mg/2ml', 'unit': 'Amp', 'min_stock': 30, 'category': '常用藥品'},
    {'code': 'MED-GI-005', 'name': 'Loperamide 2mg', 'unit': 'Cap', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-GI-006', 'name': 'Sennoside 12mg', 'unit': 'Tab', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-GI-007', 'name': 'MgO 250mg', 'unit': 'Tab', 'min_stock': 100, 'category': '常用藥品'},

    # ========== 心血管用藥 ==========
    {'code': 'MED-CV-001', 'name': 'Furosemide 20mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-CV-002', 'name': 'Furosemide 20mg/2ml', 'unit': 'Amp', 'min_stock': 30, 'category': '常用藥品'},
    {'code': 'MED-CV-003', 'name': 'Amlodipine 5mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-CV-004', 'name': 'Atenolol 50mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-CV-005', 'name': 'Enalapril 10mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},

    # ========== 抗感染藥品 ==========
    {'code': 'MED-ATB-001', 'name': 'Amoxicillin 500mg', 'unit': 'Cap', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-ATB-002', 'name': 'Augmentin 375mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-ATB-003', 'name': 'Cephalexin 500mg', 'unit': 'Cap', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-ATB-004', 'name': 'Ceftriaxone 1g', 'unit': 'Vial', 'min_stock': 30, 'category': '常用藥品'},
    {'code': 'MED-ATB-005', 'name': 'Metronidazole 250mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-ATB-006', 'name': 'Azithromycin 250mg', 'unit': 'Tab', 'min_stock': 30, 'category': '常用藥品'},
    {'code': 'MED-ATB-007', 'name': 'Ciprofloxacin 500mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-ATB-008', 'name': 'Tetanus Toxoid', 'unit': 'Vial', 'min_stock': 20, 'category': '常用藥品'},

    # ========== 麻醉藥品 ==========
    {'code': 'MED-ANES-001', 'name': 'Propofol 200mg/20ml', 'unit': 'Amp', 'min_stock': 20, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-002', 'name': 'Ketamine 500mg/10ml', 'unit': 'Vial', 'min_stock': 10, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-003', 'name': 'Midazolam 5mg/ml', 'unit': 'Amp', 'min_stock': 20, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-004', 'name': 'Etomidate 20mg/10ml', 'unit': 'Amp', 'min_stock': 10, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-005', 'name': 'Succinylcholine 100mg', 'unit': 'Vial', 'min_stock': 10, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-006', 'name': 'Rocuronium 50mg/5ml', 'unit': 'Vial', 'min_stock': 10, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-007', 'name': 'Bupivacaine 0.5%', 'unit': 'Vial', 'min_stock': 20, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-008', 'name': 'Lidocaine 2% (局麻)', 'unit': 'Vial', 'min_stock': 30, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-009', 'name': 'Neostigmine 0.5mg', 'unit': 'Amp', 'min_stock': 20, 'category': '麻醉藥品'},
    {'code': 'MED-ANES-010', 'name': 'Atracurium 25mg', 'unit': 'Amp', 'min_stock': 20, 'category': '麻醉藥品'},

    # ========== 輸液 ==========
    {'code': 'MED-IV-001', 'name': 'Normal Saline 500ml', 'unit': 'Bag', 'min_stock': 100, 'category': '輸液'},
    {'code': 'MED-IV-002', 'name': 'Normal Saline 1000ml', 'unit': 'Bag', 'min_stock': 100, 'category': '輸液'},
    {'code': 'MED-IV-003', 'name': 'Lactated Ringer 500ml', 'unit': 'Bag', 'min_stock': 100, 'category': '輸液'},
    {'code': 'MED-IV-004', 'name': 'Lactated Ringer 1000ml', 'unit': 'Bag', 'min_stock': 100, 'category': '輸液'},
    {'code': 'MED-IV-005', 'name': 'D5W 500ml', 'unit': 'Bag', 'min_stock': 50, 'category': '輸液'},
    {'code': 'MED-IV-006', 'name': 'D5W 1000ml', 'unit': 'Bag', 'min_stock': 50, 'category': '輸液'},
    {'code': 'MED-IV-007', 'name': 'D5NS 500ml', 'unit': 'Bag', 'min_stock': 30, 'category': '輸液'},
    {'code': 'MED-IV-008', 'name': 'D5NS 1000ml', 'unit': 'Bag', 'min_stock': 30, 'category': '輸液'},
    {'code': 'MED-IV-009', 'name': 'Mannitol 20% 250ml', 'unit': 'Bag', 'min_stock': 20, 'category': '輸液'},

    # ========== 其他常用藥品 ==========
    {'code': 'MED-OTH-001', 'name': 'Chlorpheniramine 4mg', 'unit': 'Tab', 'min_stock': 100, 'category': '常用藥品'},
    {'code': 'MED-OTH-002', 'name': 'Loratadine 10mg', 'unit': 'Tab', 'min_stock': 50, 'category': '常用藥品'},
    {'code': 'MED-OTH-003', 'name': 'Diazepam 5mg', 'unit': 'Tab', 'min_stock': 30, 'category': '管制藥品'},
    {'code': 'MED-OTH-004', 'name': 'Diazepam 10mg/2ml', 'unit': 'Amp', 'min_stock': 20, 'category': '管制藥品'},
    {'code': 'MED-OTH-005', 'name': 'Phenytoin 250mg/5ml', 'unit': 'Amp', 'min_stock': 10, 'category': '常用藥品'},
    {'code': 'MED-OTH-006', 'name': 'Levetiracetam 500mg', 'unit': 'Tab', 'min_stock': 30, 'category': '常用藥品'},
    {'code': 'MED-OTH-007', 'name': 'Dexamethasone 4mg/ml', 'unit': 'Amp', 'min_stock': 30, 'category': '常用藥品'},
    {'code': 'MED-OTH-008', 'name': 'Methylprednisolone 40mg', 'unit': 'Vial', 'min_stock': 20, 'category': '常用藥品'},
    {'code': 'MED-OTH-009', 'name': 'Vitamin K 10mg', 'unit': 'Amp', 'min_stock': 20, 'category': '常用藥品'},
    {'code': 'MED-OTH-010', 'name': 'Tranexamic Acid 500mg', 'unit': 'Amp', 'min_stock': 30, 'category': '常用藥品'},
]

# ============================================================================
# 耗材清單 (存入 items 表)
# ============================================================================

CONSUMABLES_DATA = [
    # ========== 紗布與敷料 ==========
    {'code': 'GAUZE-001', 'name': '無菌紗布 2x2', 'unit': '包', 'min_stock': 200, 'category': '敷料'},
    {'code': 'GAUZE-002', 'name': '無菌紗布 4x4', 'unit': '包', 'min_stock': 300, 'category': '敷料'},
    {'code': 'GAUZE-003', 'name': '無菌紗布 8x8', 'unit': '包', 'min_stock': 100, 'category': '敷料'},
    {'code': 'BAND-001', 'name': '彈性繃帶 2吋', 'unit': '捲', 'min_stock': 50, 'category': '敷料'},
    {'code': 'BAND-002', 'name': '彈性繃帶 3吋', 'unit': '捲', 'min_stock': 50, 'category': '敷料'},
    {'code': 'BAND-003', 'name': '彈性繃帶 4吋', 'unit': '捲', 'min_stock': 50, 'category': '敷料'},
    {'code': 'TAPE-001', 'name': '透氣膠帶 1吋', 'unit': '捲', 'min_stock': 50, 'category': '敷料'},
    {'code': 'TAPE-002', 'name': '透氣膠帶 2吋', 'unit': '捲', 'min_stock': 30, 'category': '敷料'},

    # ========== 注射用品 ==========
    {'code': 'SYR-001', 'name': '注射器 1ml', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'SYR-002', 'name': '注射器 3ml', 'unit': '支', 'min_stock': 200, 'category': '注射用品'},
    {'code': 'SYR-003', 'name': '注射器 5ml', 'unit': '支', 'min_stock': 200, 'category': '注射用品'},
    {'code': 'SYR-004', 'name': '注射器 10ml', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'SYR-005', 'name': '注射器 20ml', 'unit': '支', 'min_stock': 50, 'category': '注射用品'},
    {'code': 'NDL-001', 'name': '針頭 18G', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'NDL-002', 'name': '針頭 20G', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'NDL-003', 'name': '針頭 22G', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'NDL-004', 'name': '針頭 25G', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},

    # ========== 靜脈輸液用品 ==========
    {'code': 'IVC-001', 'name': '靜脈留置針 18G', 'unit': '支', 'min_stock': 50, 'category': '注射用品'},
    {'code': 'IVC-002', 'name': '靜脈留置針 20G', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'IVC-003', 'name': '靜脈留置針 22G', 'unit': '支', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'IVC-004', 'name': '靜脈留置針 24G', 'unit': '支', 'min_stock': 50, 'category': '注射用品'},
    {'code': 'IVSET-001', 'name': '點滴套組', 'unit': '組', 'min_stock': 100, 'category': '注射用品'},
    {'code': 'IVSET-002', 'name': '輸血套組', 'unit': '組', 'min_stock': 30, 'category': '注射用品'},
    {'code': 'EXT-001', 'name': '三向活栓', 'unit': '個', 'min_stock': 50, 'category': '注射用品'},

    # ========== 防護用品 ==========
    {'code': 'PPE-001', 'name': '外科口罩', 'unit': '盒', 'min_stock': 50, 'category': '防護用品'},
    {'code': 'PPE-002', 'name': 'N95口罩', 'unit': '盒', 'min_stock': 20, 'category': '防護用品'},
    {'code': 'PPE-003', 'name': '乳膠手套 M', 'unit': '盒', 'min_stock': 30, 'category': '防護用品'},
    {'code': 'PPE-004', 'name': '乳膠手套 L', 'unit': '盒', 'min_stock': 30, 'category': '防護用品'},
    {'code': 'PPE-005', 'name': '隔離衣', 'unit': '件', 'min_stock': 50, 'category': '防護用品'},
    {'code': 'PPE-006', 'name': '面罩', 'unit': '個', 'min_stock': 20, 'category': '防護用品'},
    {'code': 'PPE-007', 'name': '護目鏡', 'unit': '個', 'min_stock': 10, 'category': '防護用品'},

    # ========== 傷口處理 ==========
    {'code': 'CLEAN-001', 'name': '生理食鹽水 250ml (沖洗)', 'unit': '瓶', 'min_stock': 50, 'category': '清潔用品'},
    {'code': 'CLEAN-002', 'name': '優碘溶液', 'unit': '瓶', 'min_stock': 20, 'category': '清潔用品'},
    {'code': 'CLEAN-003', 'name': '75%酒精', 'unit': '瓶', 'min_stock': 30, 'category': '清潔用品'},
    {'code': 'CLEAN-004', 'name': '棉棒', 'unit': '包', 'min_stock': 100, 'category': '清潔用品'},
    {'code': 'CLEAN-005', 'name': '棉球', 'unit': '包', 'min_stock': 50, 'category': '清潔用品'},

    # ========== 縫合材料 ==========
    {'code': 'SUTURE-001', 'name': 'Vicryl 2-0', 'unit': '條', 'min_stock': 30, 'category': '手術耗材'},
    {'code': 'SUTURE-002', 'name': 'Vicryl 3-0', 'unit': '條', 'min_stock': 30, 'category': '手術耗材'},
    {'code': 'SUTURE-003', 'name': 'Vicryl 4-0', 'unit': '條', 'min_stock': 30, 'category': '手術耗材'},
    {'code': 'SUTURE-004', 'name': 'Nylon 3-0', 'unit': '條', 'min_stock': 30, 'category': '手術耗材'},
    {'code': 'SUTURE-005', 'name': 'Nylon 4-0', 'unit': '條', 'min_stock': 30, 'category': '手術耗材'},
    {'code': 'SUTURE-006', 'name': 'Silk 3-0', 'unit': '條', 'min_stock': 20, 'category': '手術耗材'},

    # ========== 呼吸道用品 ==========
    {'code': 'AIRWAY-001', 'name': 'ETT 6.5', 'unit': '支', 'min_stock': 5, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-002', 'name': 'ETT 7.0', 'unit': '支', 'min_stock': 10, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-003', 'name': 'ETT 7.5', 'unit': '支', 'min_stock': 10, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-004', 'name': 'ETT 8.0', 'unit': '支', 'min_stock': 5, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-005', 'name': 'LMA #3', 'unit': '支', 'min_stock': 3, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-006', 'name': 'LMA #4', 'unit': '支', 'min_stock': 5, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-007', 'name': 'Ambu Bag', 'unit': '組', 'min_stock': 5, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-008', 'name': '抽痰管 12Fr', 'unit': '支', 'min_stock': 50, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-009', 'name': '抽痰管 14Fr', 'unit': '支', 'min_stock': 50, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-010', 'name': '氧氣鼻導管', 'unit': '條', 'min_stock': 30, 'category': '呼吸道用品'},
    {'code': 'AIRWAY-011', 'name': '氧氣面罩', 'unit': '個', 'min_stock': 20, 'category': '呼吸道用品'},

    # ========== 導管類 ==========
    {'code': 'CATH-001', 'name': 'Foley 14Fr', 'unit': '支', 'min_stock': 10, 'category': '導管類'},
    {'code': 'CATH-002', 'name': 'Foley 16Fr', 'unit': '支', 'min_stock': 20, 'category': '導管類'},
    {'code': 'CATH-003', 'name': 'Foley 18Fr', 'unit': '支', 'min_stock': 10, 'category': '導管類'},
    {'code': 'CATH-004', 'name': 'NG 14Fr', 'unit': '支', 'min_stock': 20, 'category': '導管類'},
    {'code': 'CATH-005', 'name': 'NG 16Fr', 'unit': '支', 'min_stock': 20, 'category': '導管類'},
    {'code': 'CATH-006', 'name': 'Chest Tube 28Fr', 'unit': '支', 'min_stock': 5, 'category': '導管類'},
    {'code': 'CATH-007', 'name': 'Chest Tube 32Fr', 'unit': '支', 'min_stock': 5, 'category': '導管類'},
]

# ============================================================================
# 設備清單
# ============================================================================

EQUIPMENT_DATA = [
    # ========== 基礎水電維生設備 (附件五) - v2.0 新增 type_code ==========
    {'id': 'UTIL-001', 'name': '行動電源站', 'category': '電力設備', 'quantity': 2, 'type_code': 'POWER_STATION'},
    {'id': 'UTIL-002', 'name': '發電機 (備用)', 'category': '電力設備', 'quantity': 1, 'type_code': 'GENERATOR'},
    {'id': 'UTIL-003', 'name': '光觸媒空氣清淨機', 'category': '空氣淨化', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'UTIL-004', 'name': '淨水器 (RO)', 'category': '水處理', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'UTIL-005', 'name': '行動冰箱', 'category': '冷藏設備', 'quantity': 2, 'type_code': 'GENERAL'},
    {'id': 'UTIL-006', 'name': '醫療級冷凍櫃', 'category': '冷藏設備', 'quantity': 1, 'type_code': 'GENERAL'},

    # ========== 一般醫療設備 (附件二) ==========
    {'id': 'DIAG-001', 'name': '血壓計 (電子式)', 'category': '診斷設備', 'quantity': 3, 'type_code': 'MONITOR'},
    {'id': 'DIAG-002', 'name': '體溫計 (額溫槍)', 'category': '診斷設備', 'quantity': 5, 'type_code': 'MONITOR'},
    {'id': 'DIAG-003', 'name': '血氧機 (指夾式)', 'category': '診斷設備', 'quantity': 3, 'type_code': 'MONITOR'},
    {'id': 'DIAG-004', 'name': '聽診器', 'category': '診斷設備', 'quantity': 3, 'type_code': 'GENERAL'},
    {'id': 'DIAG-005', 'name': '血糖機', 'category': '診斷設備', 'quantity': 2, 'type_code': 'MONITOR'},
    {'id': 'DIAG-006', 'name': '12導程心電圖機', 'category': '診斷設備', 'quantity': 1, 'type_code': 'MONITOR'},

    # ========== 急救設備 ==========
    {'id': 'EMER-EQ-001', 'name': 'AED 自動體外除顫器', 'category': '急救設備', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'EMER-EQ-002', 'name': '甦醒球 (成人)', 'category': '急救設備', 'quantity': 2, 'type_code': 'GENERAL'},
    {'id': 'EMER-EQ-003', 'name': '甦醒球 (兒童)', 'category': '急救設備', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'EMER-EQ-004', 'name': '喉頭鏡組', 'category': '急救設備', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'EMER-EQ-005', 'name': '氣管內管組', 'category': '急救設備', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'EMER-EQ-006', 'name': '氧氣瓶 (E size)', 'category': '急救設備', 'quantity': 4, 'type_code': 'O2_CYLINDER_E'},
    {'id': 'EMER-EQ-007', 'name': '抽吸機', 'category': '急救設備', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'EMER-EQ-008', 'name': '脊椎固定板', 'category': '急救設備', 'quantity': 2, 'type_code': 'GENERAL'},
    {'id': 'EMER-EQ-009', 'name': '頸圈 (各尺寸)', 'category': '急救設備', 'quantity': 5, 'type_code': 'GENERAL'},

    # ========== BORP 手術器械包 ==========
    {'id': 'BORP-SURG-001', 'name': '共同基本包 (一)', 'category': '手術器械', 'quantity': 8, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-002', 'name': '共同基本包 (二)', 'category': '手術器械', 'quantity': 8, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-003', 'name': '骨科包', 'category': '手術器械', 'quantity': 8, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-004', 'name': '開腹輔助包', 'category': '手術器械', 'quantity': 8, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-005', 'name': '腹部開創器', 'category': '手術器械', 'quantity': 8, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-006', 'name': '開胸基本包', 'category': '手術器械', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-007', 'name': '血管包', 'category': '手術器械', 'quantity': 3, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-008', 'name': '心外基本包', 'category': '手術器械', 'quantity': 4, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-009', 'name': 'ASSET包', 'category': '手術器械', 'quantity': 8, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-010', 'name': '皮膚縫合包', 'category': '手術器械', 'quantity': 2, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-011', 'name': '氣切輔助包', 'category': '手術器械', 'quantity': 8, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-012', 'name': 'Bull dog血管夾', 'category': '手術器械', 'quantity': 4, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-013', 'name': '顱骨手搖鑽', 'category': '手術器械', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-014', 'name': '鑽/切骨電動工具組', 'category': '手術器械', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-015', 'name': '電池式電動骨鑽', 'category': '手術器械', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'BORP-SURG-016', 'name': '電池式電動骨鋸', 'category': '手術器械', 'quantity': 3, 'type_code': 'GENERAL'},

    # ========== 呼吸設備 ==========
    {'id': 'RESP-001', 'name': '氧氣鋼瓶 (H型)', 'category': '呼吸設備', 'quantity': 5, 'type_code': 'O2_CYLINDER_H'},
    {'id': 'RESP-002', 'name': '氧氣濃縮機', 'category': '呼吸設備', 'quantity': 2, 'type_code': 'O2_CONCENTRATOR'},
    {'id': 'RESP-003', 'name': '呼吸器 (Transport)', 'category': '呼吸設備', 'quantity': 1, 'type_code': 'VENTILATOR'},
    {'id': 'RESP-004', 'name': '霧化器', 'category': '呼吸設備', 'quantity': 3, 'type_code': 'GENERAL'},

    # ========== 輸液設備 ==========
    {'id': 'INF-001', 'name': '點滴架', 'category': '輸液設備', 'quantity': 10, 'type_code': 'GENERAL'},
    {'id': 'INF-002', 'name': '輸液幫浦', 'category': '輸液設備', 'quantity': 5, 'type_code': 'GENERAL'},
    {'id': 'INF-003', 'name': '血液加溫器', 'category': '輸液設備', 'quantity': 1, 'type_code': 'GENERAL'},

    # ========== 固定搬運設備 ==========
    {'id': 'TRANS-001', 'name': '輪椅', 'category': '搬運設備', 'quantity': 3, 'type_code': 'GENERAL'},
    {'id': 'TRANS-002', 'name': '擔架床', 'category': '搬運設備', 'quantity': 5, 'type_code': 'GENERAL'},
    {'id': 'TRANS-003', 'name': '脊椎板', 'category': '搬運設備', 'quantity': 3, 'type_code': 'GENERAL'},
    {'id': 'TRANS-004', 'name': '頸圈組', 'category': '搬運設備', 'quantity': 5, 'type_code': 'GENERAL'},
    {'id': 'TRANS-005', 'name': '骨折固定夾板組', 'category': '搬運設備', 'quantity': 5, 'type_code': 'GENERAL'},

    # ========== 其他設備 ==========
    {'id': 'OTH-001', 'name': '冰箱 (藥品)', 'category': '儲存設備', 'quantity': 1, 'type_code': 'GENERAL'},
    {'id': 'OTH-002', 'name': '冰箱 (血液)', 'category': '儲存設備', 'quantity': 1, 'type_code': 'GENERAL'},
]

# ============================================================================
# 試劑清單 (REA- 前綴，用於韌性計算)
# ============================================================================

REAGENTS_DATA = [
    {'code': 'REA-CBC-001', 'name': '全血球計數試劑', 'unit': 'Kit', 'min_stock': 5, 'category': '檢驗試劑',
     'endurance_type': 'REAGENT', 'tests_per_unit': 100, 'valid_days_after_open': 28},
    {'code': 'REA-TROP-001', 'name': '心肌旋轉蛋白試劑', 'unit': 'Kit', 'min_stock': 3, 'category': '檢驗試劑',
     'endurance_type': 'REAGENT', 'tests_per_unit': 25, 'valid_days_after_open': 14},
    {'code': 'REA-GLU-001', 'name': '血糖試紙', 'unit': 'Box', 'min_stock': 10, 'category': '檢驗試劑',
     'endurance_type': 'REAGENT', 'tests_per_unit': 50, 'valid_days_after_open': None},
    {'code': 'REA-ABG-001', 'name': '血氣分析試劑', 'unit': 'Kit', 'min_stock': 3, 'category': '檢驗試劑',
     'endurance_type': 'REAGENT', 'tests_per_unit': 25, 'valid_days_after_open': 7},
    {'code': 'REA-COVID-001', 'name': 'COVID快篩試劑', 'unit': 'Kit', 'min_stock': 10, 'category': '檢驗試劑',
     'endurance_type': 'REAGENT', 'tests_per_unit': 25, 'valid_days_after_open': None},
    {'code': 'REA-CRP-001', 'name': 'C反應蛋白試劑', 'unit': 'Kit', 'min_stock': 3, 'category': '檢驗試劑',
     'endurance_type': 'REAGENT', 'tests_per_unit': 50, 'valid_days_after_open': 30},
]

# ============================================================================
# 整合函數 - 取得所有 items (藥品 + 耗材 + 試劑)
# ============================================================================

def get_all_items():
    """取得所有 items (藥品 + 耗材 + 試劑)"""
    return MEDICINES_DATA + CONSUMABLES_DATA + REAGENTS_DATA


def get_reagents_data():
    """取得試劑資料"""
    return REAGENTS_DATA


def get_reagents_count():
    """取得試劑數量"""
    return len(REAGENTS_DATA)


def get_medicines_count():
    """取得藥品數量"""
    return len(MEDICINES_DATA)


def get_consumables_count():
    """取得耗材數量"""
    return len(CONSUMABLES_DATA)


def get_equipment_data():
    """取得設備資料"""
    return EQUIPMENT_DATA


def get_equipment_count():
    """取得設備數量"""
    return len(EQUIPMENT_DATA)


# 保持向後相容
def get_all_preload_data():
    """取得所有預載資料 (向後相容)"""
    return {
        'items': get_all_items(),
        'equipment': EQUIPMENT_DATA
    }


if __name__ == '__main__':
    # 測試輸出
    print(f"藥品數量: {get_medicines_count()}")
    print(f"耗材數量: {get_consumables_count()}")
    print(f"設備數量: {get_equipment_count()}")
    print(f"總 items 數量: {len(get_all_items())}")

    print(f"\n藥品分類統計:")
    categories = {}
    for item in MEDICINES_DATA:
        cat = item['category']
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")

    print(f"\n耗材分類統計:")
    categories = {}
    for item in CONSUMABLES_DATA:
        cat = item['category']
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
