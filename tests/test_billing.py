from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest

from app.routes.billing import (
    create_free_key,
    checkout_redirect,
    stripe_webhook,
    get_checkout_key,
    _handle_checkout_completed,
    FreeKeyRequest,
)


def _mock_pool(fetchval_result=None, fetchrow_result=None):
    """Create a mock asyncpg pool with working async context manager."""
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=fetchval_result)
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = acquire
    return pool, conn


@pytest.mark.asyncio
async def test_create_free_key_success():
    pool, conn = _mock_pool(fetchval_result=0)
    with patch("app.routes.billing.get_pool", AsyncMock(return_value=pool)):
        result = await create_free_key(FreeKeyRequest(name="Test", email="test@example.com"))

    assert result.api_key.startswith("npv_")
    assert result.plan == "free"
    assert result.monthly_limit == 100
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_create_free_key_missing_email():
    """Missing email triggers Pydantic validation error."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FreeKeyRequest(name="Test")


@pytest.mark.asyncio
async def test_create_free_key_rate_limit():
    """Max 3 free keys per email returns 429."""
    from fastapi import HTTPException

    pool, _ = _mock_pool(fetchval_result=3)
    with patch("app.routes.billing.get_pool", AsyncMock(return_value=pool)):
        with pytest.raises(HTTPException) as exc_info:
            await create_free_key(FreeKeyRequest(name="Test", email="test@example.com"))
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_checkout_redirect_pro():
    mock_session = MagicMock()
    mock_session.url = "https://checkout.stripe.com/test123"

    with (
        patch("app.routes.billing.stripe") as mock_stripe,
        patch("app.routes.billing.settings") as mock_settings,
    ):
        mock_settings.stripe_secret_key = "sk_test_xxx"
        mock_settings.stripe_pro_price_id = "price_pro"
        mock_settings.stripe_enterprise_price_id = "price_ent"
        mock_settings.base_url = "http://localhost:8000"
        mock_stripe.checkout.Session.create.return_value = mock_session

        result = await checkout_redirect("pro")

    assert result.status_code == 303
    assert result.headers["location"] == "https://checkout.stripe.com/test123"


@pytest.mark.asyncio
async def test_checkout_invalid_plan():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await checkout_redirect("invalid")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_webhook_checkout_completed():
    pool, conn = _mock_pool(fetchval_result=None)  # No existing key
    mock_redis = AsyncMock()

    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "customer": "cus_123",
                "subscription": "sub_123",
                "customer_details": {"email": "buyer@example.com"},
                "metadata": {"plan": "pro"},
            }
        },
    }

    mock_request = AsyncMock()
    mock_request.body = AsyncMock(return_value=json.dumps(event).encode())
    mock_request.headers = {"stripe-signature": "sig_test"}

    with (
        patch("app.routes.billing.stripe") as mock_stripe,
        patch("app.routes.billing.get_pool", AsyncMock(return_value=pool)),
        patch("app.routes.billing.get_redis", AsyncMock(return_value=mock_redis)),
        patch("app.routes.billing.settings") as mock_settings,
    ):
        mock_settings.stripe_webhook_secret = "whsec_test"
        mock_stripe.Webhook.construct_event.return_value = event

        result = await stripe_webhook(mock_request)

    assert result.status_code == 200
    conn.execute.assert_called_once()
    # Verify key was stored in Redis
    mock_redis.set.assert_called_once()
    redis_call_args = mock_redis.set.call_args
    assert redis_call_args[0][0] == "checkout_key:cs_test_123"
    assert redis_call_args[0][1].startswith("npv_")


@pytest.mark.asyncio
async def test_webhook_invalid_signature():
    from fastapi import HTTPException
    import stripe as stripe_lib

    mock_request = AsyncMock()
    mock_request.body = AsyncMock(return_value=b"payload")
    mock_request.headers = {"stripe-signature": "bad"}

    with (
        patch("app.routes.billing.stripe") as mock_stripe,
        patch("app.routes.billing.settings") as mock_settings,
    ):
        mock_settings.stripe_webhook_secret = "whsec_test"
        mock_stripe.Webhook.construct_event.side_effect = stripe_lib.SignatureVerificationError(
            "bad sig", "sig_header"
        )
        mock_stripe.SignatureVerificationError = stripe_lib.SignatureVerificationError

        with pytest.raises(HTTPException) as exc_info:
            await stripe_webhook(mock_request)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_get_checkout_key_found():
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value="npv_abc123")

    with patch("app.routes.billing.get_redis", AsyncMock(return_value=mock_redis)):
        result = await get_checkout_key("cs_test_123")

    assert result["api_key"] == "npv_abc123"
    mock_redis.delete.assert_called_once_with("checkout_key:cs_test_123")


@pytest.mark.asyncio
async def test_get_checkout_key_not_found():
    from fastapi import HTTPException

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    with patch("app.routes.billing.get_redis", AsyncMock(return_value=mock_redis)):
        with pytest.raises(HTTPException) as exc_info:
            await get_checkout_key("cs_nonexistent")
    assert exc_info.value.status_code == 404
