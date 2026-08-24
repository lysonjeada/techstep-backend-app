import pytest

from tests import factories

pytestmark = pytest.mark.security


INTERVIEW_PAYLOAD = {
    "company_name": "Empresa X",
    "job_title": "Engenheiro de Software",
    "job_seniority": "Pleno",
}


# --- /users/{user_id} ---


async def test_get_other_user_by_id_returns_404(
    authenticated_client, second_user
):
    response = await authenticated_client.get(
        f"/users/{second_user.id}"
    )
    assert response.status_code == 404


async def test_update_other_user_by_id_returns_404(
    authenticated_client, second_user
):
    response = await authenticated_client.put(
        f"/users/{second_user.id}",
        json={"username": "hacked_username"},
    )
    assert response.status_code == 404


async def test_delete_other_user_by_id_returns_404(
    authenticated_client, second_user, db_session
):
    response = await authenticated_client.delete(
        f"/users/{second_user.id}"
    )
    assert response.status_code == 404

    db_session.expire_all()
    still_there = (
        db_session.query(type(second_user))
        .filter(type(second_user).id == second_user.id)
        .first()
    )
    assert still_there is not None


async def test_own_user_by_id_is_accessible(authenticated_client, user):
    response = await authenticated_client.get(f"/users/{user.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)


# --- /interviews/{interview_id} ---


async def test_read_other_users_interview_returns_404(
    authenticated_client, db_session, second_user
):
    interview = factories.create_interview(db_session, second_user)

    response = await authenticated_client.get(
        f"/interviews/{interview.id}"
    )
    assert response.status_code == 404


async def test_update_other_users_interview_returns_404(
    authenticated_client, db_session, second_user
):
    interview = factories.create_interview(db_session, second_user)

    response = await authenticated_client.put(
        f"/interviews/{interview.id}",
        json=INTERVIEW_PAYLOAD,
    )
    assert response.status_code == 404


async def test_delete_other_users_interview_returns_404(
    authenticated_client, db_session, second_user
):
    interview = factories.create_interview(db_session, second_user)

    response = await authenticated_client.delete(
        f"/interviews/{interview.id}"
    )
    assert response.status_code == 404

    db_session.expire_all()
    still_there = (
        db_session.query(type(interview))
        .filter(type(interview).id == interview.id)
        .first()
    )
    assert still_there is not None


async def test_list_interviews_never_includes_other_users_data(
    authenticated_client, db_session, user, second_user
):
    factories.create_interview(db_session, second_user)
    own_interview = factories.create_interview(db_session, user)

    response = await authenticated_client.get("/interviews/")
    assert response.status_code == 200

    ids = [item["id"] for item in response.json()]
    assert str(own_interview.id) in ids
    assert len(ids) == 1


# --- /dashboard/progress cross-tenant isolation ---


async def test_dashboard_never_counts_other_users_interviews(
    authenticated_client, db_session, user, second_user
):
    factories.create_interview(db_session, second_user)

    response = await authenticated_client.get("/dashboard/progress")
    assert response.status_code == 200
    assert response.json()["summary"]["total_applications"] == 0

    factories.create_interview(db_session, user)

    response = await authenticated_client.get("/dashboard/progress")
    assert response.json()["summary"]["total_applications"] == 1


async def test_dashboard_requires_authentication(client):
    response = await client.get("/dashboard/progress")
    assert response.status_code == 401


# --- /videos IDOR ---


async def test_get_my_videos_never_returns_other_users_videos(
    authenticated_client, db_session, user, second_user
):
    factories.create_video(db_session, second_user)
    own_video = factories.create_video(db_session, user)

    response = await authenticated_client.get("/videos/mine")
    assert response.status_code == 200

    ids = [item["id"] for item in response.json()["items"]]
    assert str(own_video.id) in ids
    assert len(ids) == 1


async def test_get_unapproved_video_of_other_user_is_forbidden(
    authenticated_client, db_session, second_user
):
    video = factories.create_video(
        db_session, second_user, status="pending"
    )

    response = await authenticated_client.get(f"/videos/{video.id}")
    assert response.status_code == 403


async def test_get_approved_video_of_other_user_is_visible(
    authenticated_client, db_session, second_user
):
    video = factories.create_video(
        db_session, second_user, status="approved"
    )

    response = await authenticated_client.get(f"/videos/{video.id}")
    assert response.status_code == 200


async def test_approved_videos_feed_never_includes_pending_or_rejected(
    client, db_session, user
):
    approved = factories.create_video(db_session, user, status="approved")
    factories.create_video(db_session, user, status="pending")
    factories.create_video(db_session, user, status="rejected")

    response = await client.get("/videos/approved")
    assert response.status_code == 200

    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(approved.id)]


async def test_delete_video_of_other_user_is_forbidden(
    authenticated_client, db_session, second_user
):
    video = factories.create_video(db_session, second_user)

    response = await authenticated_client.delete(f"/videos/{video.id}")
    assert response.status_code == 403

    # O vídeo do outro usuário continua existindo.
    still_there = await authenticated_client.get(f"/videos/{video.id}")
    assert still_there.status_code in (200, 403)
