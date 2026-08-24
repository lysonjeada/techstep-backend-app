"""Testes funcionais de DELETE /videos/{video_id} e
POST /videos/{video_id}/resend-review: exclusão do próprio vídeo,
remoção do arquivo em disco, reenvio da notificação de revisão
limitado a 1x por dia, e as regras básicas de acesso (as regras de
dono/IDOR mais específicas ficam em tests/security/test_idor.py).
"""

from datetime import datetime, timedelta, timezone

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


# --- POST /videos/{video_id}/resend-review ---


async def test_resend_review_succeeds_when_never_notified_before(
    authenticated_client, db_session, user, _mock_video_review_email
):
    video = factories.create_video(
        db_session, user, review_notification_sent_at=None
    )

    response = await authenticated_client.post(
        f"/videos/{video.id}/resend-review"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["video"]["id"] == str(video.id)
    assert body["next_resend_allowed_at"] is not None
    assert len(_mock_video_review_email) == 1
    assert _mock_video_review_email[0]["uploader_email"] == user.email


async def test_resend_review_succeeds_after_24h_since_last_notification(
    authenticated_client, db_session, user, _mock_video_review_email
):
    sent_yesterday = datetime.now(timezone.utc) - timedelta(days=1, minutes=1)
    video = factories.create_video(
        db_session, user, review_notification_sent_at=sent_yesterday
    )

    response = await authenticated_client.post(
        f"/videos/{video.id}/resend-review"
    )

    assert response.status_code == 200
    assert len(_mock_video_review_email) == 1


async def test_resend_review_within_24h_is_rejected(
    authenticated_client, db_session, user, _mock_video_review_email
):
    sent_minutes_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
    video = factories.create_video(
        db_session, user, review_notification_sent_at=sent_minutes_ago
    )

    response = await authenticated_client.post(
        f"/videos/{video.id}/resend-review"
    )

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "RESEND_TOO_SOON"
    assert "Retry-After" in response.headers
    assert len(_mock_video_review_email) == 0


async def test_resend_review_on_approved_video_is_rejected(
    authenticated_client, db_session, user, _mock_video_review_email
):
    video = factories.create_video(db_session, user, status="approved")

    response = await authenticated_client.post(
        f"/videos/{video.id}/resend-review"
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VIDEO_NOT_PENDING"
    assert len(_mock_video_review_email) == 0


async def test_resend_review_requires_authentication(client, db_session, user):
    video = factories.create_video(db_session, user)

    response = await client.post(f"/videos/{video.id}/resend-review")
    assert response.status_code == 401


async def test_resend_review_for_unknown_video_returns_404(
    authenticated_client,
):
    response = await authenticated_client.post(
        "/videos/00000000-0000-0000-0000-000000000000/resend-review"
    )
    assert response.status_code == 404


async def test_resend_review_of_other_users_video_is_forbidden(
    authenticated_client, db_session, second_user, _mock_video_review_email
):
    video = factories.create_video(db_session, second_user)

    response = await authenticated_client.post(
        f"/videos/{video.id}/resend-review"
    )

    assert response.status_code == 403
    assert len(_mock_video_review_email) == 0
