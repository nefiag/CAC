from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from backend.app import main
from backend.app.main import authentication_middleware, prepare_trial_mutation, user_can_access_account_set


class GrantSession:
    def __init__(self, grant):
        self.grant = grant

    async def scalar(self, _query):
        return self.grant


@pytest.mark.asyncio
async def test_admin_can_access_every_account_set_without_grant_query():
    user = SimpleNamespace(id="admin", role="ADMIN")
    assert await user_can_access_account_set(user, "any-account", GrantSession(None))


@pytest.mark.asyncio
async def test_non_admin_requires_explicit_account_set_grant():
    user = SimpleNamespace(id="u1", role="ACCOUNTANT")
    assert not await user_can_access_account_set(user, "set-b", GrantSession(None))
    assert await user_can_access_account_set(user, "set-a", GrantSession("grant-id"))


@pytest.mark.asyncio
async def test_unauthorized_mutation_is_blocked_before_backup_or_write():
    user = SimpleNamespace(id="u1", role="ACCOUNTANT")
    with pytest.raises(HTTPException) as caught:
        await prepare_trial_mutation(GrantSession(None), "set-b", "CREATE_VOUCHER", user)
    assert caught.value.status_code == 403
    assert caught.value.detail == "无权访问该账套"


def request_for(path: str, method: str = "GET", query: bytes = b"") -> Request:
    return Request({
        "type": "http", "http_version": "1.1", "method": method,
        "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": query, "headers": [], "client": ("127.0.0.1", 1),
        "server": ("test", 443),
    })


@pytest.mark.asyncio
async def test_viewer_cannot_modify_data(monkeypatch):
    monkeypatch.setattr(
        main, "authenticated_user",
        lambda _request: async_value(SimpleNamespace(role="VIEWER", must_change_password=False)),
    )
    response = await authentication_middleware(request_for("/api/v1/vouchers", "POST"), ok_response)
    assert response.status_code == 403
    assert "只读用户" in response.body.decode()


@pytest.mark.asyncio
async def test_query_for_unassigned_account_set_is_denied(monkeypatch):
    user = SimpleNamespace(id="u1", role="ACCOUNTANT", must_change_password=False)
    monkeypatch.setattr(main, "authenticated_user", lambda _request: async_value(user))
    monkeypatch.setattr(main, "user_can_access_account_set", lambda *_args: async_value(False))
    response = await authentication_middleware(
        request_for("/api/v1/reports/income-statement", query=b"account_set_id=set-b&period=2026-11"),
        ok_response,
    )
    assert response.status_code == 403
    assert "无权访问" in response.body.decode()


async def async_value(value):
    return value


async def ok_response(_request):
    return Response("ok")
