from app.utils.ein import ein_to_digits, validate_ein


def test_valid_ein_with_dash():
    assert validate_ein("53-0196605") == "53-0196605"


def test_valid_ein_without_dash():
    assert validate_ein("530196605") == "53-0196605"


def test_valid_ein_with_whitespace():
    assert validate_ein(" 53-0196605 ") == "53-0196605"


def test_invalid_ein_too_short():
    assert validate_ein("12345") is None


def test_invalid_ein_too_long():
    assert validate_ein("1234567890") is None


def test_invalid_ein_letters():
    assert validate_ein("AB-CDEFGHI") is None


def test_empty_ein():
    assert validate_ein("") is None


def test_ein_to_digits():
    assert ein_to_digits("53-0196605") == "530196605"


def test_ein_to_digits_already_clean():
    assert ein_to_digits("530196605") == "530196605"
