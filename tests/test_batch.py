from unittest.mock import AsyncMock, patch

import pytest

from app.models.schemas import BatchVerifyRequest, VerifyResponse
from app.routes.verify import verify_batch

MOCK_API_KEY_INFO = {
    "id": 1,
    "monthly_limit": 100,
}


def _make_verify_response(ein: str, name: str) -> VerifyResponse:
    return VerifyResponse(ein=ein, legal_name=name, status="active")


def _patches():
    return (
        patch("app.routes.verify.check_rate_limit_batch", new_callable=AsyncMock),
        patch("app.routes.verify.verify_organization", new_callable=AsyncMock),
        patch("app.routes.verify.cache_get", new_callable=AsyncMock),
        patch("app.routes.verify.cache_set", new_callable=AsyncMock),
        patch("app.routes.verify._record_usage", new_callable=AsyncMock),
    )


@pytest.mark.asyncio
async def test_batch_basic():
    """Two EINs, both found — response has correct structure."""
    p_rl, p_vo, p_cg, p_cs, p_ru = _patches()
    with p_rl, p_vo as mock_vo, p_cg as mock_cg, p_cs, p_ru:
        mock_cg.return_value = None  # no cache
        mock_vo.side_effect = [
            _make_verify_response("53-0196605", "RED CROSS"),
            _make_verify_response("13-1837418", "DOCTORS WITHOUT BORDERS"),
        ]
        result = await verify_batch(
            BatchVerifyRequest(eins=["53-0196605", "13-1837418"]),
            api_key_info=MOCK_API_KEY_INFO,
        )

    assert result.total == 2
    assert result.succeeded == 2
    assert result.failed == 0
    assert len(result.results) == 2
    assert result.results[0].ein == "53-0196605"
    assert result.results[0].success is True
    assert result.results[0].data is not None
    assert result.results[0].data.legal_name == "RED CROSS"
    assert result.results[1].ein == "13-1837418"
    assert result.results[1].success is True


@pytest.mark.asyncio
async def test_batch_partial_failure():
    """One found, one not found — both present in results."""
    p_rl, p_vo, p_cg, p_cs, p_ru = _patches()
    with p_rl, p_vo as mock_vo, p_cg as mock_cg, p_cs, p_ru:
        mock_cg.return_value = None
        mock_vo.side_effect = [
            _make_verify_response("53-0196605", "RED CROSS"),
            None,  # not found
        ]
        result = await verify_batch(
            BatchVerifyRequest(eins=["53-0196605", "99-9999999"]),
            api_key_info=MOCK_API_KEY_INFO,
        )

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.results[0].success is True
    assert result.results[1].success is False
    assert result.results[1].error is not None


@pytest.mark.asyncio
async def test_batch_invalid_ein_rejected():
    """Request with malformed EIN returns 400."""
    from fastapi import HTTPException

    p_rl, p_vo, p_cg, p_cs, p_ru = _patches()
    with p_rl, p_vo, p_cg, p_cs, p_ru:
        with pytest.raises(HTTPException) as exc_info:
            await verify_batch(
                BatchVerifyRequest(eins=["bad-ein"]),
                api_key_info=MOCK_API_KEY_INFO,
            )
    assert exc_info.value.status_code == 400
    assert "Invalid EIN format" in exc_info.value.detail


@pytest.mark.asyncio
async def test_batch_empty_list_rejected():
    """Empty eins list fails Pydantic validation at request level."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BatchVerifyRequest(eins=[])


@pytest.mark.asyncio
async def test_batch_exceeds_max_size():
    """More than 50 EINs returns 400."""
    from fastapi import HTTPException

    eins = [f"{i:02d}-{i:07d}" for i in range(51)]
    p_rl, p_vo, p_cg, p_cs, p_ru = _patches()
    with p_rl, p_vo, p_cg, p_cs, p_ru:
        with pytest.raises(HTTPException) as exc_info:
            await verify_batch(
                BatchVerifyRequest(eins=eins),
                api_key_info=MOCK_API_KEY_INFO,
            )
    assert exc_info.value.status_code == 400
    assert "exceeds maximum" in exc_info.value.detail


@pytest.mark.asyncio
async def test_batch_deduplicates_eins():
    """Same EIN twice — enricher called only once."""
    p_rl, p_vo, p_cg, p_cs, p_ru = _patches()
    with p_rl, p_vo as mock_vo, p_cg as mock_cg, p_cs, p_ru:
        mock_cg.return_value = None
        mock_vo.return_value = _make_verify_response("53-0196605", "RED CROSS")
        result = await verify_batch(
            BatchVerifyRequest(eins=["53-0196605", "530196605"]),
            api_key_info=MOCK_API_KEY_INFO,
        )

    # Enricher should only be called once despite 2 EINs (they're the same)
    assert mock_vo.call_count == 1
    # But both results should be present
    assert result.total == 2
    assert result.succeeded == 2
    assert result.results[0].data.legal_name == "RED CROSS"
    assert result.results[1].data.legal_name == "RED CROSS"


@pytest.mark.asyncio
async def test_batch_rate_limit_per_ein():
    """Batch of 3 unique EINs increments rate limit by 3."""
    p_rl, p_vo, p_cg, p_cs, p_ru = _patches()
    with p_rl as mock_rl, p_vo as mock_vo, p_cg as mock_cg, p_cs, p_ru:
        mock_cg.return_value = None
        mock_vo.return_value = _make_verify_response("53-0196605", "ORG")
        await verify_batch(
            BatchVerifyRequest(eins=["53-0196605", "13-1837418", "04-2103594"]),
            api_key_info=MOCK_API_KEY_INFO,
        )

    # check_rate_limit_batch called with count=3
    mock_rl.assert_called_once()
    call_args = mock_rl.call_args
    assert call_args[0][1] == 3  # second positional arg is count
