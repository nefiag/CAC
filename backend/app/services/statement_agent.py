# -*- coding: utf-8 -*-
import io
import os
import re
import json
import base64
import hashlib
import calendar
import urllib.request
from decimal import Decimal
from datetime import datetime, date
from typing import List, Dict, Any, Tuple
import pandas as pd
import pdfplumber
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ChartOfAccount, BankAccount, BankStatement

OPENING_CUTOFF = date(2024, 1, 1)

BSTER_SET_ID = "00000000-0000-0000-0000-000000000001"
YT_SET_ID = "00000000-0000-0000-0000-000000000002"
YT_DEFAULT_BANK_ID = "00000000-0000-0000-0000-000000000020"

BANK_TAIL_TO_CODE = {
    "7103": "100209",   # 博士特-农商行城北支行7103
    "6321": "100215",   # 博士特-农商行6321
    "1502": "100211",   # 博士特-宁波银行1502
    "1446": "100212",   # 博士特-宁波银行1446
    "7104": "100208",   # 博士特-农商行监管账户7104
    "10047": "100210",  # 博士特-农商行贷款专户10047
    "494642": "100201", # 宇天-宁波银行494642
    "98005": "100211",  # 宇天-内部账户98005
}


def _detect_company_set_id(filename: str, text_hint: str, fallback_set_id: str) -> str:
    combined = f"{filename} {text_hint}"
    if any(k in combined for k in ("宇天", "494642", "98005")):
        return YT_SET_ID
    if any(k in combined for k in ("博士特", "7103", "6321", "1502", "1446", "7104", "10047")):
        return BSTER_SET_ID
    return fallback_set_id

LOAN_TAIL_TO_CODE = {
    "67859": "230102",   # 长期借款_银行贷款（农商行城北支行）
    "077006": "230103",  # 长期借款_银行贷款（宁波银行）
}

# 仅针对【摘要 + 附言】匹配的业务关键词（绝不扫描对方户名）
SUMMARY_KEYWORD_RULES = [
    (["工资", "年终奖", "代发工资"], "2151", "SALARY_PAYOUT", Decimal("0.9800"), False),
    (["入息", "结息", "利息收入"], "550302", "BANK_INTEREST_RED", Decimal("0.9900"), True),
    (["手续费", "短信收费", "网银服务费", "账户管理费", "年费", "工本费"], "550301", "BANK_FEE", Decimal("0.9900"), False),
    (["归还利息", "贷款利息", "利息支出"], "550303", "LOAN_INTEREST", Decimal("0.9800"), False),
    (["归还贷款", "还本金", "贷款本金", "贷款批扣"], "230102", "LOAN_PRINCIPAL", Decimal("0.9800"), False),
    (["公积金", "住房公积金"], "550212", "HOUSING_FUND", Decimal("0.9800"), False),
    (["社保", "社会保险"], "550213", "SOCIAL_SECURITY", Decimal("0.9800"), False),
    (["税费扣缴", "暂收款", "税务"], "217115", "TAX_WITHHOLDING", Decimal("0.9700"), False),
    (["光伏发电", "分布式光伏"], "510105", "SOLAR_REVENUE", Decimal("0.9800"), False),
    (["停车费", "神州路通"], "510203", "PARKING_REVENUE", Decimal("0.9800"), False),
    (["维保费", "修缮", "装修", "门窗", "维修费"], "550220", "MAINTENANCE_EXP", Decimal("0.9300"), False),
    (["垃圾清运"], "540106", "GARBAGE_COST", Decimal("0.9600"), False),
    (["财产保险", "车险", "保费"], "550210", "INSURANCE_EXP", Decimal("0.9600"), False),
    (["代理记账", "办公费", "检测费", "刻字"], "550203", "OFFICE_EXP", Decimal("0.9300"), False),
    (["差旅", "机票", "高铁", "住宿"], "550204", "TRAVEL_EXP", Decimal("0.9200"), False),
    (["电费", "供电"], "113213", "PREPAID_POWER", Decimal("0.9500"), False),
    (["水费", "自来水"], "113214", "PREPAID_WATER", Decimal("0.9500"), False),
]


def _parse_date(val: Any) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()[:10].replace("/", "-").replace(".", "-")
    if len(s) == 8 and s.isdigit():
        s = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _month_end_dt(d: date) -> datetime:
    last_day = calendar.monthrange(d.year, d.month)[1]
    return datetime(d.year, d.month, last_day, 12, 0, 0)


def _detect_account_code(filename: str, text_hint: str, fallback_code: str) -> str:
    combined = f"{filename} {text_hint}"
    for tail, code in BANK_TAIL_TO_CODE.items():
        if tail in combined:
            return code
    return fallback_code


def _call_gemini_generate(parts: List[Dict[str, Any]], timeout: int = 90) -> Any:
    """直接调用 Gemini REST API (gemini-2.5-flash) 并强制返回结构化 JSON"""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not api_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
    except Exception:
        return None


def _extract_pdf_via_vision(file_bytes: bytes, filename: str, file_bank_code: str) -> List[Dict[str, Any]]:
    file_set_id = _detect_company_set_id(filename, "", "")
    """多模态视觉兜底通道：直接将 PDF 字节流送入 Gemini 2.5 Flash 视觉解析表格"""
    prompt = (
        "你是资深中国企业会计与银行对账单视觉解析专家。请仔细查看这份银行对账单 PDF 的视觉表格，"
        "逐行提取所有真实交易明细（跳过期初余额、合计行、表头与页脚）。"
        "严格返回一个 JSON 数组，每个元素包含以下字段：\n"
        "- tx_date: 交易日期，格式 YYYY-MM-DD\n"
        "- direction: 收支方向，贷方/收入/转入为 'IN'，借方/支出/划出为 'OUT'\n"
        "- amount: 交易发生额（正数浮点数，绝不能把银行账号当成金额）\n"
        "- balance_after: 交易后账户余额（浮点数或 null，绝不能把对方账号填入余额）\n"
        "- counterparty_name: 对方户名（字符串，无则空串）\n"
        "- counterparty_account: 对方账号（字符串，无则空串）\n"
        "- raw_summary: 摘要与用途附言合并文本（字符串）"
    )
    parts = [
        {"text": prompt},
        {
            "inline_data": {
                "mime_type": "application/pdf",
                "data": base64.b64encode(file_bytes).decode("ascii"),
            }
        },
    ]
    parsed_list = _call_gemini_generate(parts, timeout=110)
    if not isinstance(parsed_list, list):
        return []

    vision_rows: List[Dict[str, Any]] = []
    for idx, item in enumerate(parsed_list):
        if not isinstance(item, dict):
            continue
        tx_d = _parse_date(item.get("tx_date"))
        if not tx_d or tx_d < OPENING_CUTOFF:
            continue
        try:
            amt = round(float(item.get("amount") or 0), 2)
        except Exception:
            continue
        if abs(amt) < 1e-6 or abs(amt) >= 1e14:
            continue
        bal_raw = item.get("balance_after")
        try:
            bal = round(float(bal_raw), 2) if bal_raw is not None else None
            if bal is not None and abs(bal) >= 1e14:
                bal = None
        except Exception:
            bal = None

        direction = "IN" if str(item.get("direction")).upper() == "IN" else "OUT"
        vision_rows.append({
            "source_file": filename,
            "row_idx": idx,
            "bank_code": file_bank_code,
            "target_set_id": file_set_id,
            "tx_date": tx_d,
            "direction": direction,
            "amount": abs(amt),
            "balance_after": bal,
            "counterparty_name": str(item.get("counterparty_name") or "").strip(),
            "counterparty_account": str(item.get("counterparty_account") or "").strip(),
            "raw_summary": str(item.get("raw_summary") or "").strip(),
        })
    return vision_rows


def _extract_rows(file_bytes: bytes, filename: str, fallback_code: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    lower = filename.lower()

    if lower.endswith((".xlsx", ".xls", ".csv")):
        df_raw = (
            pd.read_csv(io.BytesIO(file_bytes), header=None)
            if lower.endswith(".csv")
            else pd.read_excel(io.BytesIO(file_bytes), header=None)
        )
        header_idx = 0
        for i in range(min(15, len(df_raw))):
            row_vals = [str(v).strip() for v in df_raw.iloc[i].tolist()]
            if any(k in row_vals for k in ["交易日期", "日期", "交易时间", "记账日期"]):
                header_idx = i
                break

        top_meta = " ".join(str(x) for x in df_raw.iloc[:header_idx].values.flatten() if pd.notna(x))
        df = df_raw.iloc[header_idx + 1:].copy()
        df.columns = [str(c).strip() for c in df_raw.iloc[header_idx].tolist()]
        file_bank_code = _detect_account_code(filename, f"{top_meta} {' '.join(df.columns)}", fallback_code)
        file_set_id = _detect_company_set_id(filename, f"{top_meta} {' '.join(df.columns)}", "")

        for idx, r in df.iterrows():
            tx_d = _parse_date(r.get("交易日期") or r.get("日期") or r.get("交易时间") or r.get("记账日期"))
            if not tx_d or tx_d < OPENING_CUTOFF:
                continue

            in_val = float(pd.to_numeric(r.get("收入") or r.get("收入金额") or r.get("贷方") or r.get("贷方金额") or r.get("贷方发生额") or 0, errors="coerce") or 0)
            out_val = float(pd.to_numeric(r.get("支出") or r.get("支出金额") or r.get("借方") or r.get("借方金额") or r.get("借方发生额") or 0, errors="coerce") or 0)
            single_amt = float(pd.to_numeric(r.get("交易金额") or r.get("发生额") or r.get("金额") or 0, errors="coerce") or 0)
            dc_flag = str(r.get("借贷标志") or r.get("收支方向") or r.get("借/贷") or "").strip()
            bal = float(pd.to_numeric(r.get("账户余额") or r.get("余额") or r.get("可用余额") or 0, errors="coerce") or 0)

            cp_name = str(r.get("对方户名") or r.get("交易对手") or r.get("对方单位名称") or "").strip()
            cp_acct = str(r.get("对方账号") or r.get("对方账户") or "").strip()
            summary = str(r.get("摘要") or r.get("交易类型") or "").strip()
            remark = str(r.get("用途/附言/备注") or r.get("用途") or r.get("附言") or r.get("备注") or "").strip()
            raw_sum = f"{summary} {remark}".strip()

            if abs(in_val) > 1e-6:
                direction, amt = "IN", in_val
            elif abs(out_val) > 1e-6:
                direction, amt = "OUT", out_val
            elif abs(single_amt) > 1e-6:
                if dc_flag in ("贷", "收", "收入", "CR", "C") or "转入" in raw_sum:
                    direction, amt = "IN", abs(single_amt)
                elif dc_flag in ("借", "支", "支出", "DR", "D") or "划出" in raw_sum:
                    direction, amt = "OUT", abs(single_amt)
                else:
                    direction, amt = ("IN", single_amt) if single_amt > 0 else ("OUT", abs(single_amt))
            else:
                continue

            if "他行转入" in raw_sum and "冲正" not in raw_sum:
                direction = "IN"
            elif "他行划出" in raw_sum and "冲正" not in raw_sum:
                direction = "OUT"

            row_acct_hint = str(r.get("本方账号") or r.get("账号") or "").strip()
            bank_code = _detect_account_code(filename, row_acct_hint, file_bank_code)

            rows.append({
                "source_file": filename,
                "row_idx": idx,
                "bank_code": bank_code,
                "target_set_id": _detect_company_set_id(filename, row_acct_hint, file_set_id),
                "tx_date": tx_d,
                "direction": direction,
                "amount": round(amt, 2),
                "balance_after": round(bal, 2) if abs(bal) < 1e14 else None,
                "counterparty_name": "" if cp_name in ("nan", "None", "--") else cp_name,
                "counterparty_account": "" if cp_acct in ("nan", "None", "--") else cp_acct,
                "raw_summary": raw_sum,
            })

    elif lower.endswith(".pdf"):
        file_bank_code = fallback_code
        extracted_chars = 0
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            head_text = "\n".join(p.extract_text() or "" for p in pdf.pages[:2])
            extracted_chars = len(head_text.strip())
            file_bank_code = _detect_account_code(filename, head_text[:800], fallback_code)
            file_set_id = _detect_company_set_id(filename, head_text[:800], "")
            for p_idx, page in enumerate(pdf.pages):
                for t_idx, tb in enumerate(page.extract_tables() or []):
                    for r_idx, line in enumerate(tb):
                        cells = [str(c or "").replace("\n", "").strip() for c in line]
                        if len(cells) < 5:
                            continue
                        tx_d = None
                        for c in cells[:3]:
                            tx_d = _parse_date(c)
                            if tx_d:
                                break
                        if not tx_d or tx_d < OPENING_CUTOFF:
                            continue
                        nums = []
                        for c in cells[2:7]:
                            cleaned = c.replace(",", "").replace("¥", "")
                            # 仅匹配合法金额（整数部分不超过 13 位，彻底隔离 15~22 位银行账号）
                            if re.match(r"^-?\d{1,13}(\.\d{1,2})?$", cleaned):
                                nums.append(float(cleaned))
                        if not nums:
                            continue
                        joined = " ".join(cells)
                        direction = "IN" if any(k in joined for k in ["贷", "收入", "转入", "入息", "房租", "光伏", "停车"]) else "OUT"
                        bal_val = round(nums[-1], 2) if len(nums) >= 2 else None
                        if bal_val is not None and abs(bal_val) >= 1e14:
                            bal_val = None
                        rows.append({
                            "source_file": filename,
                            "row_idx": p_idx * 10000 + t_idx * 100 + r_idx,
                            "bank_code": file_bank_code,
                            "target_set_id": file_set_id,
                            "tx_date": tx_d,
                            "direction": direction,
                            "amount": round(nums[0], 2),
                            "balance_after": bal_val,
                            "counterparty_name": cells[6] if len(cells) > 6 else "",
                            "counterparty_account": cells[5] if len(cells) > 5 else "",
                            "raw_summary": " ".join(cells[7:]) if len(cells) > 7 else joined[:80],
                        })

        # 若为扫描件/加密字体导致文本极少或未提取到有效流水，自动切换 Gemini 多模态视觉直读
        if extracted_chars < 40 or len(rows) == 0:
            vision_rows = _extract_pdf_via_vision(file_bytes, filename, file_bank_code)
            if vision_rows:
                rows = vision_rows

    return rows


def _batch_classify_unknown_rows(
    unknown_items: List[Dict[str, Any]],
    coa_list: List[ChartOfAccount],
) -> Dict[int, Dict[str, str]]:
    """将本地规则和历史缓存未命中的未知流水，合并为 1 次 Gemini JSON 批量推理"""
    if not unknown_items:
        return {}

    coa_brief = "\n".join(f"{c.code}: {c.name}" for c in coa_list if len(c.code) >= 4)[:3500]
    prompt = (
        "你是中国小企业会计准则智能记账助手。请根据提供的会计科目表，为以下银行流水批量匹配最合适的对方会计科目代码与业务标签。\n"
        f"【可用会计科目表】\n{coa_brief}\n\n"
        "【待分类流水列表】\n"
        f"{json.dumps(unknown_items, ensure_ascii=False)}\n\n"
        "严格返回 JSON 数组，每个元素包含：\n"
        "- idx: 对应的输入 idx 整数\n"
        "- code: 最匹配的科目代码（如 550203、1131_1131036、2121_011 等，必须在科目表中存在）\n"
        "- biz_tag: 英文业务标签（如 OFFICE_EXP、CUSTOMER_RECEIPT、VENDOR_PAYMENT 等）"
    )
    res = _call_gemini_generate([{"text": prompt}], timeout=60)
    mapping: Dict[int, Dict[str, str]] = {}
    if isinstance(res, list):
        valid_codes = {c.code for c in coa_list}
        for item in res:
            if isinstance(item, dict) and "idx" in item and item.get("code") in valid_codes:
                mapping[int(item["idx"])] = {
                    "code": str(item["code"]),
                    "biz_tag": str(item.get("biz_tag") or "AI_CLASSIFIED"),
                }
    return mapping


async def ingest_bank_statement_batch(
    db: AsyncSession,
    account_set_id: str,
    default_bank_account_id: str,
    files: List[Tuple[str, bytes]],
) -> Dict[str, Any]:
    bank_accs = (
        await db.execute(select(BankAccount).where(BankAccount.account_set_id == account_set_id))
    ).scalars().all()
    code_to_bank_id = {b.linked_account_code: b.id for b in bank_accs}
    fallback_bank = next((b for b in bank_accs if b.id == default_bank_account_id), None)
    fallback_code = fallback_bank.linked_account_code if fallback_bank else "100209"

    all_raw_rows: List[Dict[str, Any]] = []
    for fname, fbytes in files:
        try:
            all_raw_rows.extend(_extract_rows(fbytes, fname, fallback_code))
        except Exception as e:
            raise ValueError(f"文件 [{fname}] 解析异常：{str(e)}")

    total_extracted = len(all_raw_rows)
    if not all_raw_rows:
        return {"statements": [], "total_extracted": 0, "dedup_skipped": 0}

    coa_list = (
        await db.execute(
            select(ChartOfAccount).where(ChartOfAccount.account_set_id == account_set_id)
        )
    ).scalars().all()

    name_to_ar: Dict[str, str] = {}
    name_to_ap: Dict[str, str] = {}
    name_to_other: Dict[str, str] = {}
    for c in coa_list:
        tail_name = c.name.split("_")[-1].strip()
        if c.code.startswith("1131_"):
            name_to_ar[tail_name] = c.code
        elif c.code.startswith("2121_"):
            name_to_ap[tail_name] = c.code
        elif c.code.startswith("2181") and len(c.code) >= 6:
            name_to_other[tail_name] = c.code

    # 1. 加载历史对手方科目缓存（秒出常见对手方科目，零 AI 延迟）
    hist_rows = (
        await db.execute(
            select(
                BankStatement.counterparty_name,
                BankStatement.direction,
                BankStatement.suggested_account_code,
            )
            .where(BankStatement.account_set_id == account_set_id)
            .where(BankStatement.counterparty_name != "")
            .where(BankStatement.suggested_account_code != "")
        )
    ).all()
    history_cp_cache: Dict[Tuple[str, str], str] = {}
    for h_cp, h_dir, h_code in hist_rows:
        if h_code not in ("1131_1131036", "2121_011"):
            history_cp_cache[(h_cp.strip(), h_dir)] = h_code

    outgoing_internal = set()
    for r in all_raw_rows:
        if "博士特" in r["counterparty_name"] and r["direction"] == "OUT":
            for tail, t_code in BANK_TAIL_TO_CODE.items():
                if tail in r["counterparty_account"] and t_code != r["bank_code"]:
                    outgoing_internal.add((r["tx_date"], round(abs(r["amount"]), 2), r["bank_code"], t_code))

    # 2. 预计算所有待入库流水的指纹，并用单次 SQL IN 批量查询已存在指纹（消除 N+1 查询）
    seen_batch_fps = set()
    dedup_skipped = 0
    candidate_rows: List[Dict[str, Any]] = []

    for r in all_raw_rows:
        tx_d: date = r["tx_date"]
        cp = r["counterparty_name"]
        cp_acct = r["counterparty_account"]
        direction = r["direction"]
        amt = r["amount"]
        current_bank_code = r["bank_code"]
        raw_sum = r["raw_summary"]

        if "博士特" in cp and direction == "IN":
            skip_dup = False
            for tail, s_code in BANK_TAIL_TO_CODE.items():
                if tail in cp_acct and (tx_d, round(abs(amt), 2), s_code, current_bank_code) in outgoing_internal:
                    skip_dup = True
                    break
            if skip_dup:
                dedup_skipped += 1
                continue

        row_set_id = r.get("target_set_id") or account_set_id
        fp_raw = f"{row_set_id}|{current_bank_code}|{tx_d.isoformat()}|{direction}|{amt:.2f}|{cp}|{cp_acct}|{raw_sum}"
        fp = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()
        if fp in seen_batch_fps:
            dedup_skipped += 1
            continue
        seen_batch_fps.add(fp)
        r["_fp"] = fp
        candidate_rows.append(r)

    if not candidate_rows:
        return {"statements": [], "total_extracted": total_extracted, "dedup_skipped": dedup_skipped}

    all_fps = [r["_fp"] for r in candidate_rows]
    existing_fps = set(
        (
            await db.execute(
                select(BankStatement.tx_fingerprint).where(BankStatement.tx_fingerprint.in_(all_fps))
            )
        ).scalars().all()
    )

    unique_rows: List[Dict[str, Any]] = []
    for r in candidate_rows:
        if r["_fp"] in existing_fps:
            dedup_skipped += 1
        else:
            unique_rows.append(r)

    if not unique_rows:
        return {"statements": [], "total_extracted": total_extracted, "dedup_skipped": dedup_skipped}

    # 3. 本地确定性规则 + 历史缓存匹配；收集完全未知的流水准备单次批量 AI 推理
    unknown_for_llm: List[Dict[str, Any]] = []
    pre_classified: Dict[int, Tuple[str, str, Decimal, bool, str]] = {}

    for i, r in enumerate(unique_rows):
        cp = r["counterparty_name"]
        cp_acct = r["counterparty_account"]
        direction = r["direction"]
        amt = r["amount"]
        current_bank_code = r["bank_code"]
        raw_sum = r["raw_summary"]
        text_all = f"{cp} {raw_sum}"

        suggested_code = ""
        biz_tag = "GENERAL"
        conf = Decimal("0.8800")
        is_red = amt < 0
        label = raw_sum or ("收款" if direction == "IN" else "付款")

        # 规则 1：自有账户内部划转
        if "博士特" in cp and direction == "OUT":
            target_code = None
            for tail, t_code in BANK_TAIL_TO_CODE.items():
                if tail in cp_acct and t_code != current_bank_code:
                    target_code = t_code
                    break
            if target_code:
                suggested_code = target_code
                biz_tag = "INTERNAL_TRANSFER"
                conf = Decimal("0.9900")
                label = "往来款"
            elif current_bank_code == "100215" or "支取" in text_all:
                suggested_code = "1001"
                biz_tag = "CASH_WITHDRAWAL"
                conf = Decimal("0.9800")
                label = "支取"

        # 规则 2：跨公司关联方往来（博士特 <-> 昆山宇天 -> 113340）
        row_set_id = r.get("target_set_id") or account_set_id
        if not suggested_code and (
            (row_set_id == BSTER_SET_ID and ("昆山宇天" in cp or "宇天新能源" in cp))
            or (row_set_id == YT_SET_ID and "博士特" in cp)
        ):
            suggested_code = "113340"
            biz_tag = "INTERCOMPANY_RELATED"
            conf = Decimal("0.9800")

        # 规则 3：特殊贷款归集账号
        if not suggested_code:
            for l_tail, l_code in LOAN_TAIL_TO_CODE.items():
                if l_tail in cp_acct:
                    suggested_code = "550303" if "息" in raw_sum else l_code
                    biz_tag = "LOAN_INTEREST" if "息" in raw_sum else "LOAN_PRINCIPAL"
                    conf = Decimal("0.9800")
                    break

        # 规则 4：摘要专属业务关键词
        if not suggested_code:
            for kws, code, tag, c_score, red_flag in SUMMARY_KEYWORD_RULES:
                if any(k in raw_sum for k in kws):
                    suggested_code = code
                    biz_tag = tag
                    conf = c_score
                    if red_flag:
                        is_red = True
                    break

        # 规则 5：股东/高管往来（非工资场景下的黄旭）
        if not suggested_code and ("黄旭" in cp or "WONGKING" in cp or "WONG KING" in cp):
            suggested_code = "218108"
            biz_tag = "SHAREHOLDER_CURRENT"
            conf = Decimal("0.9800")

        # 规则 6：往来单位档案精确匹配 + 历史对手方缓存命中
        if not suggested_code and cp:
            if direction == "IN" and (name_to_ar.get(cp) or name_to_other.get(cp)):
                suggested_code = name_to_ar.get(cp) or name_to_other.get(cp) or ""
                biz_tag = "CUSTOMER_RECEIPT"
                conf = Decimal("0.9500")
            elif direction == "OUT" and (name_to_ap.get(cp) or name_to_other.get(cp)):
                suggested_code = name_to_ap.get(cp) or name_to_other.get(cp) or ""
                biz_tag = "VENDOR_PAYMENT"
                conf = Decimal("0.9500")
            elif (cp, direction) in history_cp_cache:
                suggested_code = history_cp_cache[(cp, direction)]
                biz_tag = "HISTORY_CACHE_HIT"
                conf = Decimal("0.9400")

        if suggested_code:
            pre_classified[i] = (suggested_code, biz_tag, conf, is_red, label)
        else:
            unknown_for_llm.append({
                "idx": i,
                "direction": direction,
                "amount": amt,
                "counterparty": cp,
                "summary": raw_sum,
            })

    # 4. 单次批量大模型聚合推理（仅针对未知新流水）
    llm_results = _batch_classify_unknown_rows(unknown_for_llm, coa_list)

    # 5. 组装对象并一次性批量写入 Supabase（add_all + 单次 commit）
    created_records: List[BankStatement] = []
    for i, r in enumerate(unique_rows):
        tx_d: date = r["tx_date"]
        cp = r["counterparty_name"]
        cp_acct = r["counterparty_account"]
        direction = r["direction"]
        amt = r["amount"]
        current_bank_code = r["bank_code"]
        target_bank_account_id = code_to_bank_id.get(current_bank_code, default_bank_account_id)
        raw_sum = r["raw_summary"]

        if i in pre_classified:
            suggested_code, biz_tag, conf, is_red, label = pre_classified[i]
        elif i in llm_results:
            suggested_code = llm_results[i]["code"]
            biz_tag = llm_results[i]["biz_tag"]
            conf = Decimal("0.8800")
            is_red = amt < 0
            label = raw_sum or ("收款" if direction == "IN" else "付款")
        else:
            suggested_code = "1131_1131036" if direction == "IN" else "2121_011"
            biz_tag = "CUSTOMER_RECEIPT" if direction == "IN" else "VENDOR_PAYMENT"
            conf = Decimal("0.7500")
            is_red = amt < 0
            label = raw_sum or ("收款" if direction == "IN" else "付款")

        mmdd = tx_d.strftime("%m/%d")
        norm_summary = label if label.startswith(mmdd) else f"{mmdd}{label}"
        if cp and cp not in norm_summary:
            norm_summary = f"{norm_summary}：{cp}"

        bal_val = r.get("balance_after")
        safe_bal = (
            Decimal(str(bal_val))
            if (bal_val is not None and abs(Decimal(str(bal_val))) < Decimal("1e14"))
            else None
        )

        row_set_id = r.get("target_set_id") or account_set_id
        if row_set_id == YT_SET_ID:
            target_bank_account_id = YT_DEFAULT_BANK_ID
        stmt = BankStatement(
            account_set_id=row_set_id,
            bank_account_id=target_bank_account_id,
            tx_fingerprint=r["_fp"],
            tx_date=_month_end_dt(tx_d),
            direction=direction,
            amount=Decimal(str(-abs(amt) if is_red else amt)),
            balance_after=safe_bal,
            counterparty_name=cp,
            counterparty_account=cp_acct,
            raw_summary=raw_sum,
            ai_tags={
                "biz_tag": biz_tag,
                "is_red_ink": is_red,
                "actual_tx_date": tx_d.isoformat(),
                "normalized_summary": norm_summary,
                "source_file": r["source_file"],
            },
            suggested_account_code=suggested_code,
            confidence_score=conf,
            status="PARSED",
        )
        created_records.append(stmt)

    db.add_all(created_records)
    await db.commit()

    current_view_records = [s for s in created_records if s.account_set_id == account_set_id]
    return {
        "statements": current_view_records,
        "total_created_all_sets": len(created_records),
        "total_extracted": total_extracted,
        "dedup_skipped": dedup_skipped,
    }


async def ingest_bank_statement_file(
    db: AsyncSession,
    account_set_id: str,
    bank_account_id: str,
    filename: str,
    content: bytes,
) -> List[BankStatement]:
    res = await ingest_bank_statement_batch(
        db=db,
        account_set_id=account_set_id,
        default_bank_account_id=bank_account_id,
        files=[(filename, content)],
    )
    return res["statements"]
