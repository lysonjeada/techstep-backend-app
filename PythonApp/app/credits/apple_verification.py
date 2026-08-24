import os

from functools import lru_cache
from pathlib import Path

from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.models.JWSTransactionDecodedPayload import (
    JWSTransactionDecodedPayload,
)
from appstoreserverlibrary.signed_data_verifier import (
    SignedDataVerifier,
    VerificationException,
)

from app.observability import logger


APPLE_BUNDLE_ID = os.getenv(
    "APPLE_BUNDLE_ID", "lys.com.career-app"
)

# Só é exigido pela lib para verificações em ambiente Production.
_raw_apple_app_apple_id = os.getenv("APPLE_APP_APPLE_ID")
APPLE_APP_APPLE_ID = (
    int(_raw_apple_app_apple_id) if _raw_apple_app_apple_id else None
)

APPLE_ROOT_CERTIFICATES_DIR = os.getenv(
    "APPLE_ROOT_CERTIFICATES_DIR",
    str(Path(__file__).resolve().parent / "apple_root_certificates"),
)


class ApplePurchaseVerificationError(Exception):
    """A assinatura da transação Apple não pôde ser validada."""


def _load_root_certificates() -> list[bytes]:
    certificates_dir = Path(APPLE_ROOT_CERTIFICATES_DIR)

    certificates = [
        path.read_bytes()
        for path in sorted(certificates_dir.glob("*.cer"))
    ]

    if not certificates:
        raise RuntimeError(
            "Nenhum certificado raiz da Apple encontrado em "
            f"{certificates_dir}. Baixe os certificados em "
            "https://www.apple.com/certificateauthority/ e salve os "
            "arquivos .cer nesse diretório (ou aponte "
            "APPLE_ROOT_CERTIFICATES_DIR para onde eles estiverem)."
        )

    return certificates


@lru_cache(maxsize=1)
def _production_verifier() -> SignedDataVerifier:
    return SignedDataVerifier(
        root_certificates=_load_root_certificates(),
        enable_online_checks=True,
        environment=Environment.PRODUCTION,
        bundle_id=APPLE_BUNDLE_ID,
        app_apple_id=APPLE_APP_APPLE_ID,
    )


@lru_cache(maxsize=1)
def _sandbox_verifier() -> SignedDataVerifier:
    return SignedDataVerifier(
        root_certificates=_load_root_certificates(),
        enable_online_checks=True,
        environment=Environment.SANDBOX,
        bundle_id=APPLE_BUNDLE_ID,
        app_apple_id=None,
    )


def verify_signed_transaction(
    signed_transaction: str,
) -> JWSTransactionDecodedPayload:
    """Valida a assinatura JWS de uma transação StoreKit 2 (contra os
    certificados raiz da Apple) e devolve o payload decodificado —
    NUNCA usar product_id/transaction_id/quantidade vindos de outro
    lugar que não este retorno.

    Tenta o verifier de Production primeiro (caminho normal em
    produção); se a transação for de Sandbox (TestFlight ou build de
    desenvolvimento, que fala com o mesmo backend de produção), cai
    para o verifier de Sandbox. Nunca loga o JWS bruto.
    """

    try:
        return (
            _production_verifier()
            .verify_and_decode_signed_transaction(
                signed_transaction
            )
        )
    except VerificationException as production_error:
        try:
            return (
                _sandbox_verifier()
                .verify_and_decode_signed_transaction(
                    signed_transaction
                )
            )
        except VerificationException as sandbox_error:
            logger.warning(
                "apple purchase verification failed",
                extra={
                    "event": "apple_purchase_verification_failed",
                    "productionError": str(production_error),
                    "sandboxError": str(sandbox_error),
                },
            )

            raise ApplePurchaseVerificationError(
                "Não foi possível validar a transação com a Apple."
            ) from sandbox_error
