import hashlib
import secrets

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel, field_validator

from app.config import settings
from app.database import get_pool
from app.utils.cache import get_redis

router = APIRouter()

PLAN_CONFIG = {
    "free": {"monthly_limit": 100},
    "pro": {"monthly_limit": 1_000},
    "enterprise": {"monthly_limit": 999_999_999},
}


class FreeKeyRequest(BaseModel):
    name: str
    email: str

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address")
        return v.strip().lower()


class FreeKeyResponse(BaseModel):
    api_key: str
    plan: str
    monthly_limit: int


@router.post("/keys/free", response_model=FreeKeyResponse)
async def create_free_key(body: FreeKeyRequest):
    """Create a free-tier API key. Max 3 per email address."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM api_keys WHERE email = $1 AND plan = 'free'",
            body.email,
        )
        if count >= 3:
            raise HTTPException(
                status_code=429,
                detail="Maximum of 3 free API keys per email address.",
            )

        raw_key = f"npv_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]

        await conn.execute(
            """INSERT INTO api_keys (key_hash, key_prefix, name, email, plan, monthly_limit)
               VALUES ($1, $2, $3, $4, 'free', 100)""",
            key_hash,
            key_prefix,
            body.name,
            body.email,
        )

    return FreeKeyResponse(api_key=raw_key, plan="free", monthly_limit=100)


@router.get("/checkout/{plan}")
async def checkout_redirect(plan: str):
    """Redirect to Stripe Checkout for a paid plan."""
    if plan not in ("pro", "enterprise"):
        raise HTTPException(status_code=400, detail=f"Invalid plan: {plan}. Must be 'pro' or 'enterprise'.")

    price_id = (
        settings.stripe_pro_price_id if plan == "pro"
        else settings.stripe_enterprise_price_id
    )

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.base_url}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=settings.base_url,
        metadata={"plan": plan},
    )

    return RedirectResponse(url=session.url, status_code=303)


@router.post("/webhook/stripe", include_in_schema=False)
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        await _handle_checkout_completed(session)

    return JSONResponse(content={"status": "ok"})


async def _handle_checkout_completed(session: dict):
    """Create API key for completed checkout and store in Redis for retrieval."""
    plan = session.get("metadata", {}).get("plan", "pro")
    config = PLAN_CONFIG.get(plan, PLAN_CONFIG["pro"])
    customer_id = session.get("customer", "")
    subscription_id = session.get("subscription", "")
    email = session.get("customer_details", {}).get("email", "")
    session_id = session.get("id", "")

    pool = await get_pool()

    # Idempotency: check if we already created a key for this subscription
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM api_keys WHERE stripe_customer_id = $1 AND stripe_subscription_id = $2",
            customer_id,
            subscription_id,
        )
        if existing:
            return

        raw_key = f"npv_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:8]

        await conn.execute(
            """INSERT INTO api_keys
               (key_hash, key_prefix, name, email, plan, monthly_limit, stripe_customer_id, stripe_subscription_id)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            key_hash,
            key_prefix,
            f"{plan}-key",
            email,
            plan,
            config["monthly_limit"],
            customer_id,
            subscription_id,
        )

    # Store raw key in Redis for the success page to retrieve (1h TTL)
    r = await get_redis()
    await r.set(f"checkout_key:{session_id}", raw_key, ex=3600)


@router.get("/keys/checkout/{session_id}")
async def get_checkout_key(session_id: str):
    """Retrieve API key created by Stripe checkout. One-time retrieval."""
    r = await get_redis()
    raw_key = await r.get(f"checkout_key:{session_id}")

    if not raw_key:
        raise HTTPException(status_code=404, detail="Key not ready yet or already retrieved.")

    # Delete after retrieval (one-time)
    await r.delete(f"checkout_key:{session_id}")

    return {"api_key": raw_key}
