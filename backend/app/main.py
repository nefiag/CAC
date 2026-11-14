from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import io
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import engine, Base, get_db, AsyncSessionLocal
from .models import (
    AccountSet,
    ChartOfAccount,
    BankAccount,
    BankStatement,
    Voucher,
    VoucherEntry,
    ReaAgent,
)
from .schemas import VoucherCreate, StatementTagUpdate, ReverseVoucherRequest
from .services.ledger_service import create_voucher, get_trial_balance
from .services.report_service import build_category_summary, build_income_statement, build_balance_sheet, build_subsidiary_ledger, export_financial_statements_excel
from .services.statement_agent import ingest_bank_statement_file, ingest_bank_statement_batch
from .services.voucher_synthesis import synthesize_vouchers_from_statements
from .services.migration_engine import (
    export_xiaokuaiji_compatible_excel,
    import_xiaokuaiji_excel,
)

app = FastAPI(title="GeAccounting API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


DEFAULT_ACCOUNT_SET_ID = "00000000-0000-0000-0000-000000000001"
YT_ACCOUNT_SET_ID = "00000000-0000-0000-0000-000000000002"
DEFAULT_BANK_ACCOUNT_ID = "00000000-0000-0000-0000-000000000010"
YT_BANK_ACCOUNT_ID = "00000000-0000-0000-0000-000000000020"


@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. 确保博士特账套存在并更新正式企业名称
        bster_set = (
            await db.execute(select(AccountSet).where(AccountSet.id == DEFAULT_ACCOUNT_SET_ID))
        ).scalar_one_or_none()
        if not bster_set:
            db.add(
                AccountSet(
                    id=DEFAULT_ACCOUNT_SET_ID,
                    company_name="博士特电子科技（昆山）有限公司",
                    taxpayer_type="GENERAL",
                    accounting_standard="SMALL_ENT_2013",
                    start_period="2026-01",
                    current_period="2026-11",
                )
            )
        elif "示例科技" in bster_set.company_name:
            bster_set.company_name = "博士特电子科技（昆山）有限公司"

        # 2. 确保昆山宇天独立账套存在
        yt_set = (
            await db.execute(select(AccountSet).where(AccountSet.id == YT_ACCOUNT_SET_ID))
        ).scalar_one_or_none()
        if not yt_set:
            db.add(
                AccountSet(
                    id=YT_ACCOUNT_SET_ID,
                    company_name="昆山宇天新能源科技有限公司",
                    taxpayer_type="GENERAL",
                    accounting_standard="SMALL_ENT_2013",
                    start_period="2026-01",
                    current_period="2026-11",
                )
            )

        # 3. 为缺少科目的账套初始化完整科目体系
        base_seed_accounts = [
            ("1001", "库存现金", "KCXJ", "资产", "DEBIT", True, []),
            ("1002", "银行存款", "YHCK", "资产", "DEBIT", False, []),
            ("100201", "银行存款_宁波银行494642", "YHCKNBYH", "资产", "DEBIT", True, []),
            ("100208", "银行存款_农商行监管账户7104", "YHCKJGZH", "资产", "DEBIT", True, []),
            ("100209", "银行存款_农商行城北支行7103", "YHCKCBZH", "资产", "DEBIT", True, []),
            ("100210", "银行存款_农商行贷款专户10047", "YHCKDKZH", "资产", "DEBIT", True, []),
            ("100211", "银行存款_宁波银行1502/98005", "YHCK1502", "资产", "DEBIT", True, []),
            ("100212", "银行存款_宁波银行1446", "YHCK1446", "资产", "DEBIT", True, []),
            ("100215", "银行存款_农商行6321", "YHCK6321", "资产", "DEBIT", True, []),
            ("1131", "应收账款", "YSZK", "资产", "DEBIT", False, ["CUSTOMER"]),
            ("1131_1131036", "应收账款_一般客户", "YSZKYBKH", "资产", "DEBIT", True, ["CUSTOMER"]),
            ("113213", "预付账款_电费", "YFZKDF", "资产", "DEBIT", True, []),
            ("113214", "预付账款_水费", "YFZKSF", "资产", "DEBIT", True, []),
            ("113340", "其他应收款_关联方往来", "QTYSKGLF", "资产", "DEBIT", True, []),
            ("1405", "库存商品", "KCSP", "资产", "DEBIT", True, []),
            ("1601", "固定资产", "GDZC", "资产", "DEBIT", True, []),
            ("2121", "应付账款", "YFZK", "负债", "CREDIT", False, ["VENDOR"]),
            ("2121_011", "应付账款_一般供应商", "YFZKYBGYS", "负债", "CREDIT", True, ["VENDOR"]),
            ("2151", "应付职工薪酬", "YFZGXC", "负债", "CREDIT", True, []),
            ("217115", "应交税费_税费扣缴", "YJSFSFKJ", "负债", "CREDIT", True, []),
            ("218108", "其他应付款_股东往来", "QTYFKGDWL", "负债", "CREDIT", True, []),
            ("230102", "长期借款_农商行贷款", "CQJKNSH", "负债", "CREDIT", True, []),
            ("230103", "长期借款_宁波银行贷款", "CQJKNBYH", "负债", "CREDIT", True, []),
            ("4001", "实收资本", "SSZB", "权益", "CREDIT", True, []),
            ("510105", "主营业务收入_光伏发电", "ZYYWSRGF", "损益", "CREDIT", True, []),
            ("510203", "其他业务收入_停车费", "QTYWSRTC", "损益", "CREDIT", True, []),
            ("540106", "主营业务成本_垃圾清运", "ZYYWCBLJ", "损益", "DEBIT", True, []),
            ("550203", "管理费用_办公费", "GLFYBGF", "损益", "DEBIT", True, []),
            ("550204", "管理费用_差旅费", "GLFYCLF", "损益", "DEBIT", True, []),
            ("550210", "管理费用_保险费", "GLFYBXF", "损益", "DEBIT", True, []),
            ("550212", "管理费用_住房公积金", "GLFYGJJ", "损益", "DEBIT", True, []),
            ("550213", "管理费用_社会保险费", "GLFYSB", "损益", "DEBIT", True, []),
            ("550220", "管理费用_维修维保费", "GLFYWXF", "损益", "DEBIT", True, []),
            ("550301", "财务费用_手续费", "CWFYSXF", "损益", "DEBIT", True, []),
            ("550302", "财务费用_利息收入", "CWFYLXSR", "损益", "CREDIT", True, []),
            ("550303", "财务费用_利息支出", "CWFYLXZC", "损益", "DEBIT", True, []),
        ]

        for set_id in (DEFAULT_ACCOUNT_SET_ID, YT_ACCOUNT_SET_ID):
            existing_codes = set(
                (
                    await db.execute(
                        select(ChartOfAccount.code).where(ChartOfAccount.account_set_id == set_id)
                    )
                ).scalars().all()
            )
            for code, name, py, cat, d, leaf, aux in base_seed_accounts:
                if code not in existing_codes:
                    db.add(
                        ChartOfAccount(
                            account_set_id=set_id,
                            code=code,
                            name=name,
                            pinyin_abbr=py,
                            level=1 if len(code) == 4 else 2,
                            category=cat,
                            balance_direction=d,
                            is_leaf=leaf,
                            aux_types=aux,
                        )
                    )

        # 4. 确保昆山宇天银行账户存在
        yt_bank = (
            await db.execute(select(BankAccount).where(BankAccount.id == YT_BANK_ACCOUNT_ID))
        ).scalar_one_or_none()
        if not yt_bank:
            db.add(
                BankAccount(
                    id=YT_BANK_ACCOUNT_ID,
                    account_set_id=YT_ACCOUNT_SET_ID,
                    bank_name="宁波银行（昆山宇天494642）",
                    account_no="494642",
                    linked_account_code="100201",
                )
            )

        # 5. 自动将此前误入博士特账套的宇天未制证流水迁移到宇天独立账套
        misplaced_yt = (
            await db.execute(
                select(BankStatement).where(
                    BankStatement.account_set_id == DEFAULT_ACCOUNT_SET_ID,
                    BankStatement.voucher_id.is_(None),
                )
            )
        ).scalars().all()
        for s in misplaced_yt:
            src_file = str((s.ai_tags or {}).get("source_file", ""))
            if "宇天" in src_file or "494642" in src_file or "98005" in src_file:
                s.account_set_id = YT_ACCOUNT_SET_ID
                s.bank_account_id = YT_BANK_ACCOUNT_ID

        await db.commit()


@app.get("/api/v1/bootstrap")
async def bootstrap_context(account_set_id: str | None = None, db: AsyncSession = Depends(get_db)):
    all_sets = (
        await db.execute(select(AccountSet).order_by(AccountSet.id))
    ).scalars().all()
    target_id = account_set_id or DEFAULT_ACCOUNT_SET_ID
    acc_set = next((s for s in all_sets if s.id == target_id), all_sets[0])

    accounts = (
        await db.execute(
            select(ChartOfAccount)
            .where(ChartOfAccount.account_set_id == acc_set.id)
            .order_by(ChartOfAccount.code)
        )
    ).scalars().all()
    bank_accounts = (
        await db.execute(
            select(BankAccount).where(BankAccount.account_set_id == acc_set.id)
        )
    ).scalars().all()
    agents = (
        await db.execute(
            select(ReaAgent).where(ReaAgent.account_set_id == acc_set.id)
        )
    ).scalars().all()
    return {
        "account_set": acc_set,
        "account_sets": all_sets,
        "accounts": accounts,
        "bank_accounts": bank_accounts,
        "agents": agents,
    }


@app.post("/api/v1/vouchers")
async def api_create_voucher(payload: VoucherCreate, db: AsyncSession = Depends(get_db)):
    try:
        v = await create_voucher(db, payload)
        return {"id": v.id, "voucher_word": v.voucher_word, "voucher_no": v.voucher_no}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/vouchers")
async def api_list_vouchers(account_set_id: str, period: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(Voucher)
        .where(Voucher.account_set_id == account_set_id, Voucher.period == period)
        .order_by(Voucher.voucher_no.desc())
    )
    vouchers = res.scalars().all()
    out = []
    for v in vouchers:
        e_res = await db.execute(
            select(VoucherEntry).where(VoucherEntry.voucher_id == v.id).order_by(VoucherEntry.line_no)
        )
        entries = e_res.scalars().all()
        out.append(
            {
                "id": v.id,
                "voucher_word": v.voucher_word,
                "voucher_no": v.voucher_no,
                "voucher_date": str(v.voucher_date),
                "status": v.status,
                "entries": [
                    {
                        "id": e.id,
                        "summary": e.summary,
                        "account_code": e.account_code,
                        "debit_amount": float(e.debit_amount),
                        "credit_amount": float(e.credit_amount),
                    }
                    for e in entries
                ],
            }
        )
    return out


@app.get("/api/v1/reports/trial-balance")
async def api_trial_balance(account_set_id: str, period: str, db: AsyncSession = Depends(get_db)):
    return await get_trial_balance(db, account_set_id, period)


@app.post("/api/v1/statements/import")
async def api_import_statements(
    account_set_id: str = Form(...),
    bank_account_id: str = Form(...),
    auto_generate_voucher: bool = Form(True),
    confidence_threshold: float = Form(0.85),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    statements = await ingest_bank_statement_file(
        db, account_set_id, bank_account_id, file.filename or "upload.xlsx", content
    )

    generated_count = 0
    if auto_generate_voucher and statements:
        eligible_ids = [
            s.id for s in statements if float(s.confidence_score) >= confidence_threshold
        ]
        if eligible_ids:
            vouchers = await synthesize_vouchers_from_statements(
                db, account_set_id, eligible_ids, merge_mode="ONE_TO_ONE"
            )
            generated_count = len(vouchers)

    return {
        "parsed_count": len(statements),
        "generated_vouchers_count": generated_count,
    }


@app.get("/api/v1/statements")
async def api_list_statements(account_set_id: str, db: AsyncSession = Depends(get_db)):
    res = await db.execute(
        select(BankStatement)
        .where(BankStatement.account_set_id == account_set_id)
        .order_by(BankStatement.tx_date.desc())
    )
    stmts = res.scalars().all()
    v_ids = {s.voucher_id for s in stmts if s.voucher_id}
    v_map = {}
    if v_ids:
        v_res = await db.execute(select(Voucher).where(Voucher.id.in_(v_ids)))
        v_map = {v.id: f"{v.voucher_word}-{v.voucher_no}" for v in v_res.scalars().all()}

    return [
        {
            "id": s.id,
            "tx_date": s.tx_date.strftime("%Y-%m-%d %H:%M:%S"),
            "direction": s.direction,
            "amount": float(s.amount),
            "balance_after": float(s.balance_after) if s.balance_after is not None else None,
            "counterparty_name": s.counterparty_name,
            "raw_summary": s.raw_summary,
            "ai_tags": s.ai_tags,
            "matched_agent_id": s.matched_agent_id,
            "suggested_account_code": s.suggested_account_code,
            "confidence_score": float(s.confidence_score),
            "voucher_id": s.voucher_id,
            "voucher_label": v_map.get(s.voucher_id, ""),
            "status": s.status,
        }
        for s in stmts
    ]


@app.patch("/api/v1/statements/{statement_id}/tags")
async def api_update_statement_tags(
    statement_id: str, payload: StatementTagUpdate, db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(BankStatement).where(BankStatement.id == statement_id))
    stmt = res.scalar_one_or_none()
    if not stmt:
        raise HTTPException(status_code=404, detail="对账单记录不存在")

    if payload.suggested_account_code is not None:
        stmt.suggested_account_code = payload.suggested_account_code
    if payload.matched_agent_id is not None:
        stmt.matched_agent_id = payload.matched_agent_id
    if payload.counterparty_name is not None:
        stmt.counterparty_name = payload.counterparty_name
    if payload.normalized_summary is not None:
        tags = dict(stmt.ai_tags or {})
        tags["normalized_summary"] = payload.normalized_summary
        stmt.ai_tags = tags
    if payload.status is not None:
        stmt.status = payload.status

    await db.commit()
    return {"status": "UPDATED"}


@app.post("/api/v1/statements/reverse-generate-vouchers")
async def api_reverse_generate_vouchers(
    payload: ReverseVoucherRequest, db: AsyncSession = Depends(get_db)
):
    vouchers = await synthesize_vouchers_from_statements(
        db=db,
        account_set_id=payload.account_set_id,
        statement_ids=payload.statement_ids,
        merge_mode=payload.merge_mode,
        voucher_word=payload.voucher_word,
        overwrite_existing=payload.overwrite_existing,
    )
    return {
        "generated_count": len(vouchers),
        "voucher_ids": [v.id for v in vouchers],
    }


@app.get("/api/v1/migration/export-xiaokuaiji")
async def api_export_xiaokuaiji(account_set_id: str, period: str, db: AsyncSession = Depends(get_db)):
    data = await export_xiaokuaiji_compatible_excel(db, account_set_id, period)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=xiaokuaiji_export_{period}.xlsx"},
    )


@app.post("/api/v1/migration/import-xiaokuaiji")
async def api_import_xiaokuaiji(
    account_set_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    return await import_xiaokuaiji_excel(db, account_set_id, content)
@app.post("/api/v1/statements/import-batch")
async def api_import_statements_batch(
    account_set_id: str = Form(...),
    bank_account_id: str = Form(...),
    auto_generate_voucher: bool = Form(True),
    confidence_threshold: float = Form(0.85),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    file_pairs = []
    for f in files:
        content = await f.read()
        file_pairs.append((f.filename or "upload.xlsx", content))

    batch_res = await ingest_bank_statement_batch(
        db, account_set_id, bank_account_id, file_pairs
    )
    statements = batch_res["statements"]

    generated_count = 0
    if auto_generate_voucher and statements:
        eligible_ids = [
            s.id for s in statements if float(s.confidence_score) >= confidence_threshold
        ]
        if eligible_ids:
            vouchers = await synthesize_vouchers_from_statements(
                db, account_set_id, eligible_ids, merge_mode="ONE_TO_ONE"
            )
            generated_count = len(vouchers)

    return {
        "files_count": len(files),
        "total_extracted": batch_res["total_extracted"],
        "dedup_skipped": batch_res["dedup_skipped"],
        "parsed_count": len(statements),
        "generated_vouchers_count": generated_count,
    }

@app.get("/api/v1/reports/category-summary")
async def api_category_summary(account_set_id: str, period: str, db: AsyncSession = Depends(get_db)):
    return await build_category_summary(db, account_set_id, period)


@app.get("/api/v1/reports/income-statement")
async def api_income_statement(account_set_id: str, period: str, db: AsyncSession = Depends(get_db)):
    return await build_income_statement(db, account_set_id, period)


@app.get("/api/v1/reports/balance-sheet")
async def api_balance_sheet(account_set_id: str, period: str, db: AsyncSession = Depends(get_db)):
    return await build_balance_sheet(db, account_set_id, period)


@app.get("/api/v1/reports/subsidiary-ledger")
async def api_subsidiary_ledger(
    account_set_id: str,
    account_code: str,
    start_period: str,
    end_period: str,
    db: AsyncSession = Depends(get_db),
):
    return await build_subsidiary_ledger(db, account_set_id, account_code, start_period, end_period)


@app.get("/api/v1/reports/export-financial-excel")
async def api_export_financial_excel(
    account_set_id: str,
    period: str,
    detail_code: str = "1002",
    db: AsyncSession = Depends(get_db),
):
    xlsx_bytes = await export_financial_statements_excel(db, account_set_id, period, detail_code)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=financial_statements_{period}.xlsx"},
    )


import os
import sys
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

if getattr(sys, 'frozen', False):
    _base_dir = sys._MEIPASS
else:
    _base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

_frontend_dist = os.path.join(_base_dir, "frontend", "dist")
if os.path.exists(_frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = os.path.join(_frontend_dist, full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(_frontend_dist, "index.html"))

