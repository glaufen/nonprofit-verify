#!/usr/bin/env python3
"""Generate a new API key and insert it into the database."""

import asyncio
import hashlib
import secrets
import sys

import asyncpg


async def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "test-key"
    email = sys.argv[2] if len(sys.argv) > 2 else "test@example.com"

    raw_key = f"npv_{secrets.token_hex(24)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]

    conn = await asyncpg.connect(
        "postgresql://nonprofit:nonprofit@localhost:5432/nonprofit_verify"
    )
    await conn.execute(
        """INSERT INTO api_keys (key_hash, key_prefix, name, email, plan, monthly_limit)
           VALUES ($1, $2, $3, $4, 'free', 100)""",
        key_hash,
        key_prefix,
        name,
        email,
    )
    await conn.close()

    print(f"API Key created successfully!")
    print(f"  Key:    {raw_key}")
    print(f"  Prefix: {key_prefix}")
    print(f"  Name:   {name}")
    print(f"  Plan:   free (100 requests/month)")
    print()
    print(f"Test it:")
    print(f"  curl -H 'X-Api-Key: {raw_key}' http://localhost:8000/api/v1/verify/53-0196605")


if __name__ == "__main__":
    asyncio.run(main())
