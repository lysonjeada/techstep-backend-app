"""Testes unitários de app.articles.router.get_articles — garantindo
que uma resposta malformada do dev.to (200 OK com um corpo de erro em
formato de dicionário, em vez do array de artigos esperado) nunca é
encaminhada como se fosse dado válido.
"""

import pytest
from fastapi import HTTPException

from app.articles import router

pytestmark = pytest.mark.unit


def test_get_articles_returns_list_on_valid_response(monkeypatch):
    fake_articles = [{"id": 1}, {"id": 2}]

    monkeypatch.setattr(
        router,
        "_fetch_from_devto",
        lambda path, params=None: fake_articles,
    )

    result = router.get_articles(tag=None)

    assert result == fake_articles


def test_get_articles_raises_bad_gateway_when_devto_returns_dict(monkeypatch):
    """Reproduz o caso real observado em produção: o dev.to responde
    200 OK com {"error": ..., "status": 429} em vez de status HTTP de
    rate limit de verdade."""

    monkeypatch.setattr(
        router,
        "_fetch_from_devto",
        lambda path, params=None: {"error": "rate limit reached", "status": 429},
    )

    with pytest.raises(HTTPException) as exc_info:
        router.get_articles(tag=None)

    assert exc_info.value.status_code == 502
