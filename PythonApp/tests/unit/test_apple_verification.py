"""Testes unitários de app.credits.apple_verification — mockando a
SignedDataVerifier da app-store-server-library. Nenhum teste desta
suíte faz uma chamada real à Apple nem depende dos certificados raiz
estarem presentes em disco.
"""

import pytest
from appstoreserverlibrary.signed_data_verifier import (
    VerificationException,
    VerificationStatus,
)

from app.credits import apple_verification

pytestmark = pytest.mark.unit


class _FakeVerifier:
    def __init__(self, *, result=None, error=None):
        self._result = result
        self._error = error

    def verify_and_decode_signed_transaction(self, signed_transaction):
        if self._error is not None:
            raise self._error

        return self._result


def test_verify_signed_transaction_returns_decoded_payload_when_valid(
    monkeypatch,
):
    fake_payload = object()

    monkeypatch.setattr(
        apple_verification,
        "_production_verifier",
        lambda: _FakeVerifier(result=fake_payload),
    )

    result = apple_verification.verify_signed_transaction("some-jws")

    assert result is fake_payload


def test_verify_signed_transaction_falls_back_to_sandbox_verifier(
    monkeypatch,
):
    """Uma transação de TestFlight/Sandbox chega no mesmo backend de
    produção — o verifier de Production rejeita (ambiente errado), e o
    de Sandbox deve validar com sucesso."""

    fake_payload = object()

    monkeypatch.setattr(
        apple_verification,
        "_production_verifier",
        lambda: _FakeVerifier(
            error=VerificationException(
                VerificationStatus.INVALID_ENVIRONMENT
            )
        ),
    )
    monkeypatch.setattr(
        apple_verification,
        "_sandbox_verifier",
        lambda: _FakeVerifier(result=fake_payload),
    )

    result = apple_verification.verify_signed_transaction("some-jws")

    assert result is fake_payload


def test_verify_signed_transaction_raises_when_both_environments_reject(
    monkeypatch,
):
    monkeypatch.setattr(
        apple_verification,
        "_production_verifier",
        lambda: _FakeVerifier(
            error=VerificationException(
                VerificationStatus.INVALID_ENVIRONMENT
            )
        ),
    )
    monkeypatch.setattr(
        apple_verification,
        "_sandbox_verifier",
        lambda: _FakeVerifier(
            error=VerificationException(
                VerificationStatus.VERIFICATION_FAILURE
            )
        ),
    )

    with pytest.raises(
        apple_verification.ApplePurchaseVerificationError
    ):
        apple_verification.verify_signed_transaction("some-jws")


def test_load_root_certificates_raises_a_clear_error_when_directory_is_empty(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        apple_verification,
        "APPLE_ROOT_CERTIFICATES_DIR",
        str(tmp_path),
    )

    with pytest.raises(RuntimeError):
        apple_verification._load_root_certificates()
