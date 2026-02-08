import hashlib

from fastapi import HTTPException, Header

from app.database import get_pool


async def verify_api_key(
    x_api_key: str | None = Header(default=None, description="API key for authentication"),
) -> dict:
    """Validate API key from X-Api-Key header. Returns key metadata dict."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key. Pass it via the X-Api-Key header.")
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, plan, monthly_limit, is_active FROM api_keys WHERE key_hash = $1",
            key_hash,
        )

    if not row:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="API key is deactivated")

    # Fire-and-forget: update last_used_at
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE api_keys SET last_used_at = NOW() WHERE id = $1",
                row["id"],
            )
    except Exception:
        pass

    return dict(row)
