import os

from dataclasses import dataclass
from functools import lru_cache

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.observability import logger


GOOGLE_PLAY_PACKAGE_NAME = os.getenv(
    "GOOGLE_PLAY_PACKAGE_NAME", "com.techstep.careerapp"
)

# Caminho para o arquivo de credenciais de service account do Google Play
# Console (Setup > API access > Service accounts). Ainda não configurado
# em nenhum ambiente — precisa ser criado no Play Console e o arquivo
# .json apontado por esta env var antes que este fluxo funcione de
# verdade.
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"
)

_SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]

# Estados possíveis de purchases.products.get().purchaseState:
# 0 = comprado, 1 = cancelado, 2 = pendente.
_PURCHASE_STATE_PURCHASED = 0


class GooglePurchaseVerificationError(Exception):
    """O token de compra não pôde ser validado com o Google Play."""


@dataclass
class VerifiedGooglePurchase:
    product_id: str
    order_id: str


@lru_cache(maxsize=1)
def _androidpublisher_client():
    if not GOOGLE_PLAY_SERVICE_ACCOUNT_JSON:
        raise RuntimeError(
            "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON não configurada — aponte "
            "para o arquivo de credenciais de service account do Google "
            "Play Console (Setup > API access) para habilitar a "
            "verificação de compras Android."
        )

    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_PLAY_SERVICE_ACCOUNT_JSON, scopes=_SCOPES
    )

    return build(
        "androidpublisher",
        "v3",
        credentials=credentials,
        cache_discovery=False,
    )


def verify_purchase_token(
    product_id: str, purchase_token: str
) -> VerifiedGooglePurchase:
    """Valida um purchase token do Play Billing contra a Google Play
    Developer API e devolve o produto/pedido confirmados.

    Ao contrário da Apple (cujo JWS assinado já contém o product_id), o
    Google exige que o product_id seja informado para consultar o token
    — mas isso não é "confiar no cliente": o token é emitido pelo Google
    atrelado a um produto específico, então um product_id incorreto ou
    adulterado simplesmente faz esta chamada falhar (a resposta da API,
    não o que o cliente afirma, é sempre a fonte da verdade). Créditos
    concedidos vêm de AI_CREDIT_PRODUCTS_GOOGLE, nunca do cliente.
    """

    try:
        client = _androidpublisher_client()

        result = (
            client.purchases()
            .products()
            .get(
                packageName=GOOGLE_PLAY_PACKAGE_NAME,
                productId=product_id,
                token=purchase_token,
            )
            .execute()
        )
    except HttpError as error:
        logger.warning(
            "google purchase verification failed",
            extra={
                "event": "google_purchase_verification_failed",
                "error": str(error),
            },
        )

        raise GooglePurchaseVerificationError(
            "Não foi possível validar a compra com o Google Play."
        ) from error

    if result.get("purchaseState") != _PURCHASE_STATE_PURCHASED:
        raise GooglePurchaseVerificationError(
            "A compra não está no estado 'comprado'."
        )

    order_id = result.get("orderId")

    if not order_id:
        raise GooglePurchaseVerificationError(
            "A compra não contém um orderId."
        )

    return VerifiedGooglePurchase(product_id=product_id, order_id=order_id)
