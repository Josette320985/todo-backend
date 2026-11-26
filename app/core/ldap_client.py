"""Types for optional LDAP login (F1).

AuthService depends on LdapDirectory, not on ldap3, so tests pass a fake
and a deploy with LDAP_ENABLED=false never opens a socket.
"""

from dataclasses import dataclass
from typing import Protocol

_FILTER_ESCAPES = str.maketrans(
    {
        "\\": r"\5c",
        "*": r"\2a",
        "(": r"\28",
        ")": r"\29",
        "\x00": r"\00",
    }
)


def escape_ldap_filter(value: str) -> str:
    """Escape a value inserted into an LDAP filter (RFC 4515)."""
    return value.translate(_FILTER_ESCAPES)


@dataclass(frozen=True)
class LdapIdentity:
    """Account found in the directory."""

    email: str
    distinguished_name: str


class LdapDirectory(Protocol):
    """What AuthService needs from a directory. Tests pass a fake."""

    def authenticate(self, email: str, password: str) -> LdapIdentity | None:
        """Identity on success. None if the account is not in the directory."""
