import pytest
from httpx import ASGITransport, AsyncClient

import app.dashboard.router as dashboard_router
from tests.conftest import auth_headers_for

pytestmark = pytest.mark.security


FAKE_SENSITIVE_DETAIL = (
    "connection to postgresql://postgres:postgres@localhost:5433/"
    "techstep_test failed"
)


async def test_caught_exception_returns_generic_detail_not_raw_error(
    authenticated_client, db_session, monkeypatch
):
    def _boom(*args, **kwargs):
        raise RuntimeError(FAKE_SENSITIVE_DETAIL)

    monkeypatch.setattr(db_session, "commit", _boom)

    response = await authenticated_client.post(
        "/interviews/",
        json={
            "company_name": "Empresa X",
            "job_title": "Engenheiro de Software",
            "job_seniority": "Pleno",
        },
    )

    assert response.status_code == 500
    body = response.text
    assert FAKE_SENSITIVE_DETAIL not in body
    assert "Traceback" not in body
    assert response.json()["detail"] == "Erro ao salvar entrevista."


async def test_unhandled_exception_falls_back_to_generic_500(
    app_instance, user, monkeypatch
):
    def _boom(*args, **kwargs):
        raise RuntimeError(FAKE_SENSITIVE_DETAIL)

    monkeypatch.setattr(
        dashboard_router, "build_progress_dashboard", _boom
    )

    # Starlette's ServerErrorMiddleware sends the generic 500 response and
    # then re-raises the original exception (so servers can log it). With
    # the default ASGITransport, httpx re-raises that exception instead of
    # exposing the response, so we disable that here to inspect the body
    # actually sent to the client.
    transport = ASGITransport(app=app_instance, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=auth_headers_for(user),
    ) as async_client:
        response = await async_client.get("/dashboard/progress")

    assert response.status_code == 500
    body = response.text
    assert FAKE_SENSITIVE_DETAIL not in body
    assert "Traceback" not in body
    assert "RuntimeError" not in body


async def test_validation_error_never_leaks_internal_paths(client):
    response = await client.post("/interviews/", json={})

    assert response.status_code in (401, 422)
    body = response.text
    assert "site-packages" not in body
    assert __file__.rsplit("/", 1)[0] not in body


async def test_404_for_unknown_resource_never_leaks_sql(
    authenticated_client,
):
    response = await authenticated_client.get(
        "/interviews/00000000-0000-0000-0000-000000000000"
    )

    assert response.status_code == 404
    body = response.text
    assert "SELECT" not in body.upper()
    assert "psycopg" not in body.lower()
