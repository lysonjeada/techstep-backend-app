"""Testes funcionais de DELETE /videos/{video_id}: exclusão do próprio
vídeo, remoção do arquivo em disco, e as regras básicas de acesso
(as regras de dono/IDOR mais específicas ficam em
tests/security/test_idor.py).
"""

import pytest

from app.videos.router import UPLOAD_DIR
from tests import factories

pytestmark = pytest.mark.integration


async def test_delete_own_video_succeeds_and_removes_from_list(
    authenticated_client, db_session, user
):
    video = factories.create_video(db_session, user)

    response = await authenticated_client.delete(f"/videos/{video.id}")
    assert response.status_code == 204

    remaining = await authenticated_client.get("/videos/mine")
    ids = [item["id"] for item in remaining.json()["items"]]
    assert str(video.id) not in ids


async def test_delete_own_video_removes_file_from_disk(
    authenticated_client, db_session, user
):
    video = factories.create_video(db_session, user)

    file_path = UPLOAD_DIR / video.file_name
    file_path.write_bytes(b"fake video bytes")
    assert file_path.exists()

    response = await authenticated_client.delete(f"/videos/{video.id}")
    assert response.status_code == 204
    assert not file_path.exists()


async def test_delete_video_requires_authentication(client, db_session, user):
    video = factories.create_video(db_session, user)

    response = await client.delete(f"/videos/{video.id}")
    assert response.status_code == 401


async def test_delete_unknown_video_returns_404(authenticated_client):
    response = await authenticated_client.delete(
        "/videos/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404


async def test_delete_video_twice_returns_404_on_second_attempt(
    authenticated_client, db_session, user
):
    video = factories.create_video(db_session, user)

    first = await authenticated_client.delete(f"/videos/{video.id}")
    assert first.status_code == 204

    second = await authenticated_client.delete(f"/videos/{video.id}")
    assert second.status_code == 404
