import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models as app_models
from app.auth.dependencies import get_current_user
from app.database import get_db
from app.observability import logger

from .apple_verification import (
    ApplePurchaseVerificationError,
    verify_signed_transaction,
)
from .config import AI_CREDIT_PRODUCTS, AI_CREDIT_PRODUCTS_GOOGLE
from .google_verification import (
    GooglePurchaseVerificationError,
    verify_purchase_token,
)
from .schemas import (
    AICreditBalanceResponse,
    ApplePurchaseRequest,
    ApplePurchaseResponse,
    GooglePurchaseRequest,
    GooglePurchaseResponse,
)
from .service import get_balance, record_apple_purchase, record_google_purchase


router = APIRouter(prefix="/ai-credits", tags=["AI Credits"])


# MARK: - Balance


@router.get("/balance", response_model=AICreditBalanceResponse)
def get_my_balance(
    db: Session = Depends(get_db),
    current_user: app_models.User = Depends(get_current_user),
) -> AICreditBalanceResponse:
    balance = get_balance(db, current_user.id)

    logger.info(
        "ai credit balance retrieved",
        extra={
            "event": "ai_credit_balance_retrieved",
            "userId": str(current_user.id),
            "balance": balance,
        },
    )

    return AICreditBalanceResponse(balance=balance)


# MARK: - Apple Purchases


@router.post(
    "/apple/purchases", response_model=ApplePurchaseResponse
)
async def register_apple_purchase(
    payload: ApplePurchaseRequest,
    db: Session = Depends(get_db),
    current_user: app_models.User = Depends(get_current_user),
) -> ApplePurchaseResponse:
    logger.info(
        "ai credit purchase received",
        extra={
            "event": "ai_credit_purchase_received",
            "userId": str(current_user.id),
            # productId do payload é só telemetria (não é usado para
            # decidir créditos), mas ainda assim seguro de logar.
            "clientProductId": payload.product_id,
        },
    )

    # A verificação faz checagens online contra a Apple e é síncrona —
    # roda em thread pool, igual às chamadas à OpenAI no resto do app.
    try:
        decoded_transaction = await asyncio.to_thread(
            verify_signed_transaction, payload.signed_transaction
        )
    except ApplePurchaseVerificationError as error:
        logger.warning(
            "ai credit purchase rejected: invalid apple transaction",
            extra={
                "event": "ai_credit_purchase_invalid_transaction",
                "userId": str(current_user.id),
            },
        )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_APPLE_TRANSACTION",
                "message": (
                    "Não foi possível validar a compra com a Apple."
                ),
            },
        ) from error

    # A fonte da verdade é sempre o payload decodificado e verificado —
    # nunca o product_id/quantidade que o cliente mandou no corpo.
    product_id = decoded_transaction.product_id
    apple_transaction_id = decoded_transaction.transaction_id

    if not product_id or not apple_transaction_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_APPLE_TRANSACTION",
                "message": (
                    "A transação da Apple não contém os dados "
                    "esperados."
                ),
            },
        )

    credits_granted = AI_CREDIT_PRODUCTS.get(product_id)

    if credits_granted is None:
        logger.warning(
            "ai credit purchase rejected: unknown product",
            extra={
                "event": "ai_credit_purchase_unknown_product",
                "userId": str(current_user.id),
                "productId": product_id,
            },
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNKNOWN_PRODUCT",
                "message": "Produto desconhecido.",
            },
        )

    environment = (
        decoded_transaction.environment.value
        if decoded_transaction.environment
        else (decoded_transaction.raw_environment or "Sandbox")
    )

    logger.info(
        "ai credit purchase verified",
        extra={
            "event": "ai_credit_purchase_verified",
            "userId": str(current_user.id),
            "productId": product_id,
            "appleTransactionId": apple_transaction_id,
            "environment": environment,
            "creditsGranted": credits_granted,
        },
    )

    balance, already_processed = record_apple_purchase(
        db,
        user_id=current_user.id,
        apple_transaction_id=apple_transaction_id,
        apple_original_transaction_id=(
            decoded_transaction.original_transaction_id
        ),
        product_id=product_id,
        credits_granted=credits_granted,
        environment=environment,
    )

    if already_processed:
        logger.info(
            "ai credit purchase duplicate",
            extra={
                "event": "ai_credit_purchase_duplicate",
                "userId": str(current_user.id),
                "appleTransactionId": apple_transaction_id,
            },
        )

        return ApplePurchaseResponse(
            credits_added=0,
            balance=balance,
            already_processed=True,
        )

    logger.info(
        "ai credit purchase granted",
        extra={
            "event": "ai_credit_purchase_granted",
            "userId": str(current_user.id),
            "appleTransactionId": apple_transaction_id,
            "creditsGranted": credits_granted,
            "balance": balance,
        },
    )

    return ApplePurchaseResponse(
        credits_added=credits_granted,
        balance=balance,
        already_processed=False,
    )


# MARK: - Google Play Purchases


@router.post(
    "/google/purchases", response_model=GooglePurchaseResponse
)
async def register_google_purchase(
    payload: GooglePurchaseRequest,
    db: Session = Depends(get_db),
    current_user: app_models.User = Depends(get_current_user),
) -> GooglePurchaseResponse:
    logger.info(
        "ai credit purchase received",
        extra={
            "event": "ai_credit_purchase_received",
            "userId": str(current_user.id),
            "clientProductId": payload.product_id,
            "provider": "google",
        },
    )

    # A verificação faz uma chamada síncrona à Google Play Developer
    # API — roda em thread pool, igual à verificação Apple acima.
    try:
        verified = await asyncio.to_thread(
            verify_purchase_token,
            payload.product_id,
            payload.purchase_token,
        )
    except GooglePurchaseVerificationError as error:
        logger.warning(
            "ai credit purchase rejected: invalid google transaction",
            extra={
                "event": "ai_credit_purchase_invalid_transaction",
                "userId": str(current_user.id),
                "provider": "google",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_GOOGLE_PURCHASE",
                "message": (
                    "Não foi possível validar a compra com o Google Play."
                ),
            },
        ) from error

    # A fonte da verdade é sempre o resultado verificado — nunca o
    # product_id/quantidade que o cliente mandou no corpo (mesmo que,
    # ao contrário da Apple, o product_id do payload também tenha sido
    # usado para consultar a API: um product_id incorreto simplesmente
    # faz a verificação acima falhar).
    product_id = verified.product_id
    google_order_id = verified.order_id

    credits_granted = AI_CREDIT_PRODUCTS_GOOGLE.get(product_id)

    if credits_granted is None:
        logger.warning(
            "ai credit purchase rejected: unknown product",
            extra={
                "event": "ai_credit_purchase_unknown_product",
                "userId": str(current_user.id),
                "productId": product_id,
                "provider": "google",
            },
        )

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNKNOWN_PRODUCT",
                "message": "Produto desconhecido.",
            },
        )

    logger.info(
        "ai credit purchase verified",
        extra={
            "event": "ai_credit_purchase_verified",
            "userId": str(current_user.id),
            "productId": product_id,
            "googleOrderId": google_order_id,
            "creditsGranted": credits_granted,
            "provider": "google",
        },
    )

    balance, already_processed = record_google_purchase(
        db,
        user_id=current_user.id,
        google_order_id=google_order_id,
        product_id=product_id,
        credits_granted=credits_granted,
    )

    if already_processed:
        logger.info(
            "ai credit purchase duplicate",
            extra={
                "event": "ai_credit_purchase_duplicate",
                "userId": str(current_user.id),
                "googleOrderId": google_order_id,
                "provider": "google",
            },
        )

        return GooglePurchaseResponse(
            credits_added=0,
            balance=balance,
            already_processed=True,
        )

    logger.info(
        "ai credit purchase granted",
        extra={
            "event": "ai_credit_purchase_granted",
            "userId": str(current_user.id),
            "googleOrderId": google_order_id,
            "creditsGranted": credits_granted,
            "balance": balance,
            "provider": "google",
        },
    )

    return GooglePurchaseResponse(
        credits_added=credits_granted,
        balance=balance,
        already_processed=False,
    )
