import requests

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from sqlalchemy.orm import Session

from app import models as app_models
from app.auth.dependencies import (
    get_current_user,
    get_current_user_optional,
)
from app.database import get_db

from . import models


router = APIRouter(
    prefix="/articles",
    tags=["Articles"],
)


DEV_TO_BASE_URL = "https://dev.to/api"


def _fetch_from_devto(path: str, params: dict | None = None) -> dict | list:
    """Centraliza toda chamada ao dev.to — o app nunca fala direto
    com a API externa, só com este backend, que atua como
    intermediário (permite, por exemplo, anotar `is_favorited` na
    resposta sem o cliente precisar saber de nada além do nosso
    próprio contrato)."""

    try:
        response = requests.get(
            f"{DEV_TO_BASE_URL}{path}",
            params=params,
            timeout=15,
        )

        response.raise_for_status()

    except requests.RequestException as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível buscar os artigos.",
        ) from error

    return response.json()


# MARK: List


@router.get("/")
def get_articles(
    tag: str | None = Query(
        default=None
    ),
):
    params = (
        {"tag": tag}
        if tag
        else None
    )

    return _fetch_from_devto(
        "/articles",
        params=params,
    )


# MARK: Favorites
#
# Precisa ficar antes de "/{article_id}" — senão "/favorites" seria
# interpretado como um article_id inválido (mesma pegadinha de rota
# já vista em app/videos/router.py).


@router.get("/favorites")
def get_favorite_articles(
    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    favorite_ids = [
        row.article_id
        for row in (
            db.query(models.ArticleFavorite)
            .filter(
                models.ArticleFavorite.user_id
                == current_user.id
            )
            .order_by(
                models.ArticleFavorite
                .created_at.desc()
            )
            .all()
        )
    ]

    articles = []

    for article_id in favorite_ids:
        try:
            data = _fetch_from_devto(
                f"/articles/{article_id}"
            )

        except HTTPException:
            # Artigo pode ter sido removido do dev.to desde que foi
            # favoritado — não derruba a lista inteira por isso.
            continue

        data["is_favorited"] = True
        articles.append(data)

    return {"items": articles}


@router.post(
    "/{article_id}/favorite"
)
def add_article_favorite(
    article_id: int,

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    existing = (
        db.query(models.ArticleFavorite)
        .filter(
            models.ArticleFavorite.article_id
            == article_id,
            models.ArticleFavorite.user_id
            == current_user.id,
        )
        .first()
    )

    if not existing:
        db.add(
            models.ArticleFavorite(
                article_id=article_id,
                user_id=current_user.id,
            )
        )

        db.commit()

    return {"is_favorited": True}


@router.delete(
    "/{article_id}/favorite"
)
def remove_article_favorite(
    article_id: int,

    db: Session = Depends(get_db),

    current_user: app_models.User =
        Depends(get_current_user),
):
    (
        db.query(models.ArticleFavorite)
        .filter(
            models.ArticleFavorite.article_id
            == article_id,
            models.ArticleFavorite.user_id
            == current_user.id,
        )
        .delete()
    )

    db.commit()

    return {"is_favorited": False}


# MARK: Detail


@router.get("/{article_id}")
def get_article(
    article_id: int,

    db: Session = Depends(get_db),

    current_user: app_models.User | None =
        Depends(get_current_user_optional),
):
    data = _fetch_from_devto(
        f"/articles/{article_id}"
    )

    is_favorited = False

    if current_user is not None:
        is_favorited = (
            db.query(models.ArticleFavorite)
            .filter(
                models.ArticleFavorite.article_id
                == article_id,
                models.ArticleFavorite.user_id
                == current_user.id,
            )
            .first()
            is not None
        )

    data["is_favorited"] = is_favorited

    return data
