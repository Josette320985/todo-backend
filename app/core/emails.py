"""Shared email normalization for registration and login (SEG-H09).

The registration schema and the login use case must canonicalize the email in
exactly the same way. Otherwise a user registered with a Unicode or IDN email
can be stored in a form that the login cannot reproduce.

email-validator applies the Unicode normalization and converts an IDN/punycode
domain to its Unicode form. Lowercasing the local part preserves the API
contract that already treats emails as case-insensitive.
"""

from email_validator import EmailNotValidError, validate_email


def normalize_email(value: str) -> str:
    """
    Return the canonical email used by registration and login.

    The value is stripped, validated, normalized (Unicode/IDN) and lowercased.
    This is the same transformation applied to ``UserCreate.email``.

    Raises:
        ValueError: If the value is not a valid email address.
    """
    try:
        validated = validate_email(value.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(str(exc)) from exc
    return validated.normalized.lower()
