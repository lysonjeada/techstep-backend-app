"""Segurança de upload: tamanho máximo, MIME real (magic bytes),
extensões permitidas, filenames gerados pelo servidor, proteção
contra path traversal e limpeza de arquivos temporários — para os
três tipos de upload que a API aceita (vídeo, áudio, PDF de
currículo).

app.uploads.validation concentra essa lógica; este arquivo prova que
ela está de fato aplicada em cada endpoint. Não duplica os testes de
review token (tests/security/test_authorization_audit.py) nem os de
rate limit/créditos (tests/security/test_rate_limiting_http.py,
tests/integration/test_ai_credit_gate.py).
"""

import os

import pytest

from tests import factories

pytestmark = pytest.mark.security


# --- vídeo: POST /videos/ ---


async def test_video_upload_rejects_content_that_does_not_match_mime(
    authenticated_client,
):
    files = {
        "file": (
            "clip.mp4",
            factories.FAKE_TEXT_BYTES,
            "video/mp4",
        )
    }

    response = await authenticated_client.post(
        "/videos/",
        data={"title": "Vídeo"},
        files=files,
    )

    assert response.status_code == 422


async def test_video_upload_rejects_empty_file(authenticated_client):
    files = {"file": ("clip.mp4", b"", "video/mp4")}

    response = await authenticated_client.post(
        "/videos/",
        data={"title": "Vídeo"},
        files=files,
    )

    assert response.status_code == 422


async def test_video_upload_rejects_oversized_file(
    authenticated_client, monkeypatch
):
    import app.videos.router as videos_router_module

    # MAX_VIDEO_SIZE é um global de módulo lido a cada chamada (não
    # capturado numa closure), então dá pra sobrescrever num teste sem
    # precisar gerar um payload de centenas de MB.
    monkeypatch.setattr(
        videos_router_module, "MAX_VIDEO_SIZE", 10
    )

    files = {
        "file": ("clip.mp4", factories.FAKE_MP4_BYTES, "video/mp4")
    }

    response = await authenticated_client.post(
        "/videos/",
        data={"title": "Vídeo"},
        files=files,
    )

    assert response.status_code == 413


async def test_video_upload_accepts_webm_signature(authenticated_client):
    files = {
        "file": ("clip.webm", factories.FAKE_WEBM_BYTES, "video/webm")
    }

    response = await authenticated_client.post(
        "/videos/",
        data={"title": "Vídeo"},
        files=files,
    )

    assert response.status_code == 201


async def test_video_upload_stored_filename_is_server_generated(
    authenticated_client, db_session, user
):
    malicious_filename = "../../../../etc/passwd.mp4"

    files = {
        "file": (
            malicious_filename,
            factories.FAKE_MP4_BYTES,
            "video/mp4",
        )
    }

    response = await authenticated_client.post(
        "/videos/",
        data={"title": "Vídeo"},
        files=files,
    )
    assert response.status_code == 201

    video_id = response.json()["id"]

    from app.videos import models as video_models

    stored = (
        db_session.query(video_models.Video)
        .filter(video_models.Video.id == video_id)
        .first()
    )

    # O nome salvo é <uuid>.mp4 — nunca contém o filename do cliente.
    assert stored.file_name == f"{video_id}.mp4"
    assert ".." not in stored.file_name
    assert "/" not in stored.file_name


async def test_video_upload_never_escapes_upload_dir(
    authenticated_client, db_session
):
    import app.videos.router as videos_router_module

    files = {
        "file": (
            "../../../../tmp/evil.mp4",
            factories.FAKE_MP4_BYTES,
            "video/mp4",
        )
    }

    response = await authenticated_client.post(
        "/videos/",
        data={"title": "Vídeo"},
        files=files,
    )
    assert response.status_code == 201

    video_id = response.json()["id"]
    saved_path = (
        videos_router_module.UPLOAD_DIR / f"{video_id}.mp4"
    )

    assert saved_path.exists()
    assert saved_path.resolve().parent == (
        videos_router_module.UPLOAD_DIR.resolve()
    )


# --- áudio: POST /interview-simulation/transcribe ---


async def test_transcribe_rejects_content_that_does_not_match_mime(
    authenticated_client,
):
    files = {
        "audio": (
            "answer.m4a",
            factories.FAKE_TEXT_BYTES,
            "audio/mp4",
        )
    }

    response = await authenticated_client.post(
        "/interview-simulation/transcribe", files=files
    )

    assert response.status_code == 422


async def test_transcribe_rejects_oversized_audio(
    authenticated_client, monkeypatch
):
    import app.interview_simulation.router as simulation_router_module

    monkeypatch.setattr(
        simulation_router_module, "MAX_AUDIO_SIZE_BYTES", 10
    )

    files = {
        "audio": (
            "answer.m4a",
            factories.FAKE_M4A_BYTES,
            "audio/mp4",
        )
    }

    response = await authenticated_client.post(
        "/interview-simulation/transcribe", files=files
    )

    assert response.status_code == 413


async def test_transcribe_malicious_filename_never_escapes_temp_dir(
    authenticated_client, monkeypatch
):
    """Regressão: o suffix do arquivo temporário costumava vir de
    `os.path.splitext(audio.filename)`, que (ao contrário de
    pathlib.Path.suffix) não trata "/" como separador de diretório.
    Um filename como "a.mp4/../../etc/cron.d/x" podia produzir um
    suffix com "/" dentro e escapar do diretório temporário. Hoje o
    suffix é sempre fixo (".m4a"), então isso nunca mais acontece —
    aqui provamos que o arquivo sempre é criado dentro do diretório
    temporário do sistema, mesmo com esse filename malicioso."""

    import app.interview_simulation.router as simulation_router_module
    import tempfile
    from pathlib import Path

    created_paths = []
    original_named_temp_file = tempfile.NamedTemporaryFile

    def _capture(*args, **kwargs):
        handle = original_named_temp_file(*args, **kwargs)
        created_paths.append(handle.name)
        return handle

    monkeypatch.setattr(
        simulation_router_module.tempfile,
        "NamedTemporaryFile",
        _capture,
    )

    fake_transcription = type(
        "FakeTranscription", (), {"text": "resposta transcrita"}
    )()

    monkeypatch.setattr(
        simulation_router_module.client.audio.transcriptions,
        "create",
        lambda **kwargs: fake_transcription,
    )

    malicious_filename = "a.mp4/../../../../etc/cron.d/evil"

    files = {
        "audio": (
            malicious_filename,
            factories.FAKE_M4A_BYTES,
            "audio/mp4",
        )
    }

    response = await authenticated_client.post(
        "/interview-simulation/transcribe", files=files
    )

    assert response.status_code == 200
    assert len(created_paths) == 1

    temp_path = Path(created_paths[0])
    assert temp_path.parent.resolve() == Path(
        tempfile.gettempdir()
    ).resolve()
    assert "cron.d" not in str(temp_path)

    # E o arquivo temporário foi removido depois de processado.
    assert not temp_path.exists()


async def test_transcribe_temp_file_removed_after_openai_error(
    authenticated_client, monkeypatch
):
    import app.interview_simulation.router as simulation_router_module
    import tempfile
    from pathlib import Path

    created_paths = []
    original_named_temp_file = tempfile.NamedTemporaryFile

    def _capture(*args, **kwargs):
        handle = original_named_temp_file(*args, **kwargs)
        created_paths.append(handle.name)
        return handle

    monkeypatch.setattr(
        simulation_router_module.tempfile,
        "NamedTemporaryFile",
        _capture,
    )

    def _boom(**kwargs):
        raise RuntimeError("openai indisponível")

    monkeypatch.setattr(
        simulation_router_module.client.audio.transcriptions,
        "create",
        _boom,
    )

    files = {
        "audio": (
            "answer.m4a",
            factories.FAKE_M4A_BYTES,
            "audio/mp4",
        )
    }

    response = await authenticated_client.post(
        "/interview-simulation/transcribe", files=files
    )

    assert response.status_code == 500
    assert len(created_paths) == 1
    assert not Path(created_paths[0]).exists()


# --- PDF de currículo: 4 endpoints que recebem `resume` ---


async def test_resume_feedback_rejects_content_that_does_not_match_mime(
    authenticated_client,
):
    files = {
        "resume": (
            "curriculo.pdf",
            factories.FAKE_TEXT_BYTES,
            "application/pdf",
        )
    }

    response = await authenticated_client.post(
        "/resume-feedback/", files=files
    )

    assert response.status_code == 422


async def test_resume_feedback_rejects_oversized_pdf(
    authenticated_client, monkeypatch
):
    import app.llm_generation.router as llm_router_module

    monkeypatch.setattr(
        llm_router_module, "MAX_PDF_SIZE_BYTES", 10
    )

    files = {
        "resume": (
            "curriculo.pdf",
            factories.FAKE_PDF_BYTES,
            "application/pdf",
        )
    }

    response = await authenticated_client.post(
        "/resume-feedback/", files=files
    )

    assert response.status_code == 413


async def test_study_plan_generate_rejects_content_that_does_not_match_mime(
    authenticated_client,
):
    files = {
        "resume": (
            "curriculo.pdf",
            factories.FAKE_TEXT_BYTES,
            "application/pdf",
        )
    }

    response = await authenticated_client.post(
        "/study-plan/generate",
        data={"job_title": "Engenheiro", "seniority": "Pleno"},
        files=files,
    )

    assert response.status_code == 422


async def test_study_plan_generate_rejects_oversized_pdf(
    authenticated_client, monkeypatch
):
    import app.study_plan.router as study_plan_router_module

    monkeypatch.setattr(
        study_plan_router_module, "MAX_PDF_SIZE_BYTES", 10
    )

    files = {
        "resume": (
            "curriculo.pdf",
            factories.FAKE_PDF_BYTES,
            "application/pdf",
        )
    }

    response = await authenticated_client.post(
        "/study-plan/generate",
        data={"job_title": "Engenheiro", "seniority": "Pleno"},
        files=files,
    )

    assert response.status_code == 413


async def test_generate_interview_questions_rejects_content_mismatch(
    authenticated_client,
):
    files = {
        "resume": (
            "curriculo.pdf",
            factories.FAKE_TEXT_BYTES,
            "application/pdf",
        )
    }

    response = await authenticated_client.post(
        "/generate-interview-questions/",
        data={"job_title": "Engenheiro", "seniority": "Pleno"},
        files=files,
    )

    assert response.status_code == 422


async def test_submit_feedback_rejects_content_that_does_not_match_mime(
    authenticated_client, monkeypatch
):
    import app.llm_generation.router as llm_router_module

    def _delay_should_not_be_called(*args, **kwargs):
        raise AssertionError(
            "process_resume_feedback.delay não deveria ser chamado "
            "para um upload rejeitado na validação de conteúdo."
        )

    monkeypatch.setattr(
        llm_router_module.process_resume_feedback,
        "delay",
        _delay_should_not_be_called,
    )

    files = {
        "resume": (
            "curriculo.pdf",
            factories.FAKE_TEXT_BYTES,
            "application/pdf",
        )
    }

    response = await authenticated_client.post(
        "/submit-feedback/", files=files
    )

    assert response.status_code == 422
