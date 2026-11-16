from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, Request, Response
from pydantic import BaseModel
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
    AccountSetSetting,
    Contract,
    ContractPlan,
    User,
    UserSession,
    UserAccountSet,
)
from .schemas import (VoucherCreate, VoucherStatusUpdate, StatementTagUpdate, ReverseVoucherRequest,
                      AccountSetSettingsUpdate, ContractIn, ContractPlanIn)
from .services.ledger_service import create_voucher, transition_voucher, get_trial_balance, carry_forward_pnl
from .services.report_service import build_category_summary, build_income_statement, build_balance_sheet, build_subsidiary_ledger, export_financial_statements_excel
from .services.statement_agent import ingest_bank_statement_file, ingest_bank_statement_batch, expand_statement_archives, gemini_status
from .services.voucher_synthesis import synthesize_vouchers_from_statements
from .services.migration_engine import (
    export_xiaokuaiji_compatible_excel,
    import_xiaokuaiji_excel,
    inspect_xiaokuaiji_excel,
)
from .services.financial_import import (
    import_financial_workbook,
    inspect_financial_workbook,
    list_financial_imports,
)
from .auth import SESSION_COOKIE, authenticated_user, create_session, hash_password, require_admin, token_hash, verify_password
from datetime import datetime
import os

app = FastAPI(title="Coxiaoac API", version="1.0.0")

PUBLIC_API_PATHS = {"/api/v1/auth/login"}


@app.middleware("http")
async def authentication_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in PUBLIC_API_PATHS:
        user = await authenticated_user(request)
        if not user:
            return Response(content='{"detail":"请先登录"}', status_code=401, media_type="application/json")
        request.state.user = user
        if user.must_change_password and request.url.path not in {"/api/v1/auth/me", "/api/v1/auth/change-password", "/api/v1/auth/logout"}:
            return Response(content='{"detail":"请先修改初始密码"}', status_code=403, media_type="application/json")
        if user.role == "VIEWER" and request.method not in {"GET", "HEAD", "OPTIONS"}:
            return Response(content='{"detail":"只读用户不能修改数据"}', status_code=403, media_type="application/json")
        if request.url.path.startswith("/api/v1/users") and user.role != "ADMIN":
            return Response(content='{"detail":"需要系统管理员权限"}', status_code=403, media_type="application/json")
    return await call_next(request)

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
        else:
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
        else:
            yt_set.company_name = "昆山宇天新能源科技有限公司"

        # 科目体系只能由已校验的财务基准导入，启动时不混入通用假定科目。
        # 3. 确保昆山宇天银行账户存在
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

        admin_username = os.getenv("ADMIN_USERNAME", "admin").strip().lower()
        admin_password = os.getenv("ADMIN_PASSWORD", "")
        admin = (await db.execute(select(User).where(User.username == admin_username))).scalar_one_or_none()
        if not admin and admin_password:
            db.add(User(
                username=admin_username,
                display_name="系统管理员",
                password_hash=hash_password(admin_password),
                role="ADMIN",
                is_active=True,
                must_change_password=True,
            ))

        await db.commit()


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class UserIn(BaseModel):
    username: str
    display_name: str
    password: str | None = None
    role: str = "ACCOUNTANT"
    is_active: bool = True
    account_set_ids: list[str] = []


def _user_dict(user: User, account_set_ids: list[str] | None = None):
    return {"id": user.id, "username": user.username, "display_name": user.display_name,
            "role": user.role, "is_active": user.is_active,
            "must_change_password": user.must_change_password,
            "account_set_ids": account_set_ids or []}


@app.post("/api/v1/auth/login")
async def login(payload: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.username == payload.username.strip().lower()))).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token, _expires = await create_session(user.id)
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    is_https = forwarded_proto == "https" or (not forwarded_proto and request.url.scheme == "https")
    response.set_cookie(SESSION_COOKIE, token, max_age=7 * 24 * 60 * 60, httponly=True, secure=is_https, samesite="lax", path="/")
    return _user_dict(user)


@app.get("/api/v1/auth/me")
async def auth_me(request: Request):
    return _user_dict(request.state.user)


@app.post("/api/v1/auth/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = (await db.execute(select(UserSession).where(UserSession.token_hash == token_hash(token)))).scalar_one_or_none()
        if session:
            await db.delete(session)
            await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "LOGGED_OUT"}


@app.post("/api/v1/auth/change-password")
async def change_password(payload: PasswordChangeIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == request.state.user.id))).scalar_one()
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    try:
        user.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    user.must_change_password = False
    await db.commit()
    return {"status": "CHANGED"}


@app.get("/api/v1/users")
async def list_users(request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    users = (await db.execute(select(User).order_by(User.username))).scalars().all()
    result = []
    for user in users:
        grants = (await db.execute(select(UserAccountSet.account_set_id).where(UserAccountSet.user_id == user.id))).scalars().all()
        result.append(_user_dict(user, list(grants)))
    return result


@app.post("/api/v1/users")
async def create_user(payload: UserIn, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    if payload.role not in {"ADMIN", "ACCOUNTANT", "VIEWER"}:
        raise HTTPException(status_code=400, detail="无效角色")
    if not payload.password:
        raise HTTPException(status_code=400, detail="新用户必须设置初始密码")
    try:
        user = User(username=payload.username.strip().lower(), display_name=payload.display_name.strip(),
                    password_hash=hash_password(payload.password), role=payload.role,
                    is_active=payload.is_active, must_change_password=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.add(user)
    try:
        await db.flush()
        for account_set_id in payload.account_set_ids:
            db.add(UserAccountSet(user_id=user.id, account_set_id=account_set_id))
        await db.commit(); await db.refresh(user)
    except Exception:
        await db.rollback(); raise HTTPException(status_code=409, detail="用户名已存在或账套无效")
    return _user_dict(user, payload.account_set_ids)


@app.put("/api/v1/users/{user_id}")
async def update_user(user_id: str, payload: UserIn, request: Request, db: AsyncSession = Depends(get_db)):
    require_admin(request)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.role not in {"ADMIN", "ACCOUNTANT", "VIEWER"}:
        raise HTTPException(status_code=400, detail="无效角色")
    user.display_name = payload.display_name.strip(); user.role = payload.role; user.is_active = payload.is_active
    if payload.password:
        try:
            user.password_hash = hash_password(payload.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        user.must_change_password = True
    grants = (await db.execute(select(UserAccountSet).where(UserAccountSet.user_id == user_id))).scalars().all()
    for grant in grants:
        await db.delete(grant)
    for account_set_id in payload.account_set_ids:
        db.add(UserAccountSet(user_id=user_id, account_set_id=account_set_id))
    await db.commit()
    return _user_dict(user, payload.account_set_ids)


@app.get("/api/v1/bootstrap")
async def bootstrap_context(request: Request, account_set_id: str | None = None, db: AsyncSession = Depends(get_db)):
    all_sets = (
        await db.execute(select(AccountSet).order_by(AccountSet.id))
    ).scalars().all()
    if request.state.user.role != "ADMIN":
        allowed = set((await db.execute(select(UserAccountSet.account_set_id).where(UserAccountSet.user_id == request.state.user.id))).scalars().all())
        all_sets = [item for item in all_sets if item.id in allowed]
    if not all_sets:
        raise HTTPException(status_code=403, detail="当前用户尚未分配账套")
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


@app.patch("/api/v1/vouchers/{voucher_id}/status")
async def api_transition_voucher(
    voucher_id: str, payload: VoucherStatusUpdate, db: AsyncSession = Depends(get_db)
):
    voucher = (
        await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    ).scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="凭证不存在")
    try:
        updated = await transition_voucher(db, voucher, payload.action)
        return {"id": updated.id, "status": updated.status}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.delete("/api/v1/vouchers/{voucher_id}")
async def api_delete_voucher(voucher_id: str, db: AsyncSession = Depends(get_db)):
    voucher = (
        await db.execute(select(Voucher).where(Voucher.id == voucher_id))
    ).scalar_one_or_none()
    if not voucher:
        raise HTTPException(status_code=404, detail="凭证不存在")
    if voucher.status != "DRAFT":
        raise HTTPException(status_code=409, detail="只有草稿凭证可以删除")
    await db.delete(voucher)
    await db.commit()
    return {"status": "DELETED"}


@app.post("/api/v1/vouchers/carry-forward")
async def api_carry_forward_pnl(account_set_id: str, period: str, db: AsyncSession = Depends(get_db)):
    try:
        v = await carry_forward_pnl(db, account_set_id, period)
        return {
            "message": "损益结转凭证生成成功",
            "voucher_id": v.id,
            "voucher_word": v.voucher_word,
            "voucher_no": v.voucher_no,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@app.post("/api/v1/migration/inspect-xiaokuaiji")
async def api_inspect_xiaokuaiji(file: UploadFile = File(...)):
    return inspect_xiaokuaiji_excel(await file.read())


@app.post("/api/v1/financial-imports/inspect")
async def api_inspect_financial_imports(files: list[UploadFile] = File(...)):
    results = []
    for file in files:
        content = await file.read()
        results.append({"filename": file.filename or "upload.xlsx",
                        **inspect_financial_workbook(file.filename or "upload.xlsx", content)})
    return {"valid": all(row.get("valid") for row in results), "files": results}


@app.post("/api/v1/financial-imports/import")
async def api_import_financial_reports(files: list[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    results = []
    for file in files:
        content = await file.read()
        result = await import_financial_workbook(db, file.filename or "upload.xlsx", content)
        results.append({"filename": file.filename or "upload.xlsx", **result})
    return {"files": results,
            "imported": sum(row["status"] == "IMPORTED" for row in results),
            "duplicates": sum(row["status"] == "DUPLICATE" for row in results),
            "failed": sum(row["status"] == "INVALID" for row in results)}


@app.get("/api/v1/financial-imports")
async def api_list_financial_imports(account_set_id: str, db: AsyncSession = Depends(get_db)):
    return await list_financial_imports(db, account_set_id)

@app.post("/api/v1/statements/import-batch")
async def api_import_statements_batch(
    account_set_id: str = Form(...),
    bank_account_id: str = Form(...),
    auto_generate_voucher: bool = Form(True),
    confidence_threshold: float = Form(0.85),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    uploaded_pairs = []
    for f in files:
        content = await f.read()
        uploaded_pairs.append((f.filename or "upload.xlsx", content))

    try:
        expanded = expand_statement_archives(uploaded_pairs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    batch_res = await ingest_bank_statement_batch(
        db, account_set_id, bank_account_id, expanded["files"]
    )
    statements = batch_res["statements"]
    all_statements = batch_res.get("all_statements", statements)

    generated_count = 0
    if auto_generate_voucher and all_statements:
        eligible_by_set: dict[str, list[str]] = {}
        for statement in all_statements:
            if float(statement.confidence_score) >= confidence_threshold:
                eligible_by_set.setdefault(statement.account_set_id, []).append(statement.id)
        for target_set_id, eligible_ids in eligible_by_set.items():
            vouchers = await synthesize_vouchers_from_statements(db, target_set_id, eligible_ids, merge_mode="ONE_TO_ONE")
            generated_count += len(vouchers)

    return {
        "uploads_count": len(files),
        "files_count": len(expanded["files"]),
        "ignored_files": expanded["ignored"],
        "total_extracted": batch_res["total_extracted"],
        "dedup_skipped": batch_res["dedup_skipped"],
        "parsed_count": len(all_statements),
        "current_account_parsed_count": len(statements),
        "generated_vouchers_count": generated_count,
        "created_by_account_set": batch_res.get("created_by_account_set", {}),
        "file_results": batch_res.get("file_results", []),
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


@app.get("/api/v1/reports/auxiliary-balances")
async def api_auxiliary_balances(
    account_set_id: str, end_period: str, db: AsyncSession = Depends(get_db)
):
    """按凭证分录辅助维度汇总往来余额，仅统计已记账凭证。"""
    agents = (
        await db.execute(select(ReaAgent).where(ReaAgent.account_set_id == account_set_id))
    ).scalars().all()
    agent_map = {a.id: a for a in agents}
    rows = (
        await db.execute(
            select(VoucherEntry, Voucher)
            .join(Voucher, VoucherEntry.voucher_id == Voucher.id)
            .where(
                Voucher.account_set_id == account_set_id,
                Voucher.period <= end_period,
                Voucher.status == "POSTED",
            )
        )
    ).all()
    totals = {}
    for entry, voucher in rows:
        for dimension, agent_id in (entry.aux_dimensions or {}).items():
            key = (dimension, str(agent_id), entry.account_code)
            item = totals.setdefault(key, {"debit": 0.0, "credit": 0.0, "last_date": ""})
            item["debit"] += float(entry.debit_amount)
            item["credit"] += float(entry.credit_amount)
            item["last_date"] = max(item["last_date"], str(voucher.voucher_date))
    result = []
    for (dimension, agent_id, account_code), values in totals.items():
        agent = agent_map.get(agent_id)
        net = round(values["debit"] - values["credit"], 2)
        result.append({
            "dimension": dimension,
            "agent_id": agent_id,
            "agent_code": agent.code if agent else "",
            "agent_name": agent.name if agent else agent_id,
            "account_code": account_code,
            "debit_balance": net if net > 0 else 0.0,
            "credit_balance": -net if net < 0 else 0.0,
            "last_date": values["last_date"],
        })
    return sorted(result, key=lambda x: (x["dimension"], x["agent_name"], x["account_code"]))


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


@app.get("/api/v1/account-set-settings")
async def api_get_settings(account_set_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(AccountSetSetting).where(AccountSetSetting.account_set_id == account_set_id))).scalar_one_or_none()
    return {
        "voucher_rules": row.voucher_rules if row else {"allow_manual_no": False, "require_audit": True, "auto_next": True, "number_by_month": True},
        "display_rules": row.display_rules if row else {"show_aux_tip": True, "dense_tables": True},
        "backup_rules": row.backup_rules if row else {"enabled": False, "interval_days": 7},
    }


@app.put("/api/v1/account-set-settings")
async def api_put_settings(account_set_id: str, payload: AccountSetSettingsUpdate, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(AccountSetSetting).where(AccountSetSetting.account_set_id == account_set_id))).scalar_one_or_none()
    if not row:
        row = AccountSetSetting(account_set_id=account_set_id)
        db.add(row)
    row.voucher_rules = payload.voucher_rules
    row.display_rules = payload.display_rules
    row.backup_rules = payload.backup_rules
    await db.commit()
    return {"status": "SAVED"}


def _contract_dict(c, plans):
    settled = sum(float(p.settled_amount) for p in plans)
    return {"id": c.id, "contract_no": c.contract_no, "name": c.name,
            "counterparty_name": c.counterparty_name, "direction": c.direction,
            "amount": float(c.amount), "start_date": str(c.start_date) if c.start_date else None,
            "end_date": str(c.end_date) if c.end_date else None, "status": c.status,
            "note": c.note, "settled_amount": settled,
            "plans": [{"id": p.id, "due_date": str(p.due_date), "amount": float(p.amount),
                       "settled_amount": float(p.settled_amount), "note": p.note} for p in plans]}


@app.get("/api/v1/contracts")
async def api_list_contracts(account_set_id: str, db: AsyncSession = Depends(get_db)):
    contracts = (await db.execute(select(Contract).where(Contract.account_set_id == account_set_id).order_by(Contract.contract_no))).scalars().all()
    result = []
    for c in contracts:
        plans = (await db.execute(select(ContractPlan).where(ContractPlan.contract_id == c.id).order_by(ContractPlan.due_date))).scalars().all()
        result.append(_contract_dict(c, plans))
    return result


@app.get("/api/v1/statements/ai-status")
async def api_statement_ai_status():
    """Report AI availability without ever returning credential material."""
    return gemini_status()


@app.post("/api/v1/contracts")
async def api_create_contract(payload: ContractIn, db: AsyncSession = Depends(get_db)):
    if payload.direction not in {"RECEIVABLE", "PAYABLE"} or payload.amount < 0:
        raise HTTPException(status_code=400, detail="合同方向或金额无效")
    row = Contract(**payload.model_dump())
    db.add(row)
    try:
        await db.commit(); await db.refresh(row)
    except Exception:
        await db.rollback(); raise HTTPException(status_code=409, detail="合同编号已存在")
    return _contract_dict(row, [])


@app.post("/api/v1/contracts/{contract_id}/plans")
async def api_create_contract_plan(contract_id: str, payload: ContractPlanIn, db: AsyncSession = Depends(get_db)):
    contract = (await db.execute(select(Contract).where(Contract.id == contract_id))).scalar_one_or_none()
    if not contract: raise HTTPException(status_code=404, detail="合同不存在")
    if payload.amount <= 0 or payload.settled_amount < 0 or payload.settled_amount > payload.amount:
        raise HTTPException(status_code=400, detail="计划金额或已结金额无效")
    existing = (await db.execute(select(ContractPlan).where(ContractPlan.contract_id == contract_id))).scalars().all()
    if sum(float(p.amount) for p in existing) + float(payload.amount) > float(contract.amount) + 0.001:
        raise HTTPException(status_code=409, detail="收付款计划合计不能超过合同金额")
    row = ContractPlan(contract_id=contract_id, **payload.model_dump())
    db.add(row); await db.commit(); await db.refresh(row)
    return {"id": row.id}


@app.delete("/api/v1/contracts/{contract_id}")
async def api_delete_contract(contract_id: str, db: AsyncSession = Depends(get_db)):
    row = (await db.execute(select(Contract).where(Contract.id == contract_id))).scalar_one_or_none()
    if not row: raise HTTPException(status_code=404, detail="合同不存在")
    await db.delete(row); await db.commit()
    return {"status": "DELETED"}


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
