from pydantic import BaseModel, ConfigDict


class AICreditBalanceResponse(BaseModel):
    balance: int

    model_config = ConfigDict(from_attributes=True)


class ApplePurchaseRequest(BaseModel):
    # JWS assinado pela Apple (StoreKit 2 `Transaction.jwsRepresentation`).
    # É a única fonte confiável do que foi comprado — nunca o payload solto.
    signed_transaction: str

    # Usado só para telemetria/log; o product_id que decide os créditos
    # concedidos é sempre o decodificado da assinatura, não este campo.
    product_id: str


class ApplePurchaseResponse(BaseModel):
    credits_added: int
    balance: int
    already_processed: bool = False


class GooglePurchaseRequest(BaseModel):
    # Purchase token do Play Billing (BillingClient). Enviado à Google
    # Play Developer API para verificação server-side — nunca confiado
    # diretamente.
    purchase_token: str

    # Usado para consultar a Developer API (Google exige o product_id
    # para resolver o token) e para telemetria; os créditos concedidos
    # vêm sempre de AI_CREDIT_PRODUCTS_GOOGLE, resolvidos só após a
    # verificação ter confirmado que o token é válido para este produto.
    product_id: str


class GooglePurchaseResponse(BaseModel):
    credits_added: int
    balance: int
    already_processed: bool = False
