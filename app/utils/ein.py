import re

_EIN_DIGITS = re.compile(r"^\d{9}$")


def validate_ein(ein: str) -> str | None:
    """Validate and normalize EIN to XX-XXXXXXX format. Returns None if invalid."""
    clean = ein.strip().replace("-", "")
    if not _EIN_DIGITS.match(clean):
        return None
    return f"{clean[:2]}-{clean[2:]}"


def ein_to_digits(ein: str) -> str:
    """Strip dashes from EIN."""
    return ein.replace("-", "")
