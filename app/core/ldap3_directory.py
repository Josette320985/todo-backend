"""ldap3 search-then-bind client (F1).

The service account (LDAP_BIND_DN) only searches. The password is checked
with a second bind as the user. An empty password never reaches the server:
some directories treat it as a successful anonymous bind.
"""

import logging
from typing import Any

from app.core.config import Settings
from app.core.errors import DirectoryUnavailable, InvalidCredentials
from app.core.ldap_client import LdapIdentity, escape_ldap_filter
from app.core.logging import sanitize_for_log

logger = logging.getLogger("auth.ldap")


class Ldap3Directory:
    """Concrete directory. ldap3 is imported on the call, not at import time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authenticate(self, email: str, password: str) -> LdapIdentity | None:
        if not password:
            raise InvalidCredentials()

        from ldap3 import SUBTREE, Connection, Server
        from ldap3.core.exceptions import LDAPException

        settings = self._settings
        server = Server(
            settings.LDAP_URL,
            connect_timeout=settings.LDAP_TIMEOUT_SECONDS,
            use_ssl=settings.LDAP_URL.lower().startswith("ldaps://"),
        )
        user_filter = settings.LDAP_USER_FILTER.format(
            email=escape_ldap_filter(email)
        )
        search = self._bind(
            Connection, server, settings.LDAP_BIND_DN, settings.LDAP_BIND_PASSWORD
        )
        try:
            search.search(
                search_base=settings.LDAP_BASE_DN,
                search_filter=user_filter,
                search_scope=SUBTREE,
                attributes=["mail"],
                size_limit=2,
            )
            entries: list[Any] = list(search.entries)
        except LDAPException as exc:
            logger.warning("LDAP search failed: %s", type(exc).__name__)
            raise DirectoryUnavailable() from exc
        finally:
            search.unbind()

        if not entries:
            return None
        if len(entries) != 1:
            logger.warning(
                "LDAP filter matched %s entries for %s",
                len(entries),
                sanitize_for_log(email),
            )
            raise DirectoryUnavailable()

        distinguished_name: str = str(entries[0].entry_dn)
        mail = email
        mail_attr: Any = entries[0].mail if "mail" in entries[0] else None
        if mail_attr is not None and mail_attr.value:
            mail = str(mail_attr.value)
        self._bind(Connection, server, distinguished_name, password).unbind()
        return LdapIdentity(email=mail, distinguished_name=distinguished_name)

    def _bind(
        self, connection_cls: Any, server: Any, user: str, password: str
    ) -> Any:
        from ldap3.core.exceptions import LDAPException

        connection = connection_cls(
            server,
            user=user or None,
            password=password if user else None,
            auto_bind=False,
            receive_timeout=self._settings.LDAP_TIMEOUT_SECONDS,
        )
        try:
            accepted: bool = bool(connection.bind())
        except LDAPException as exc:
            logger.warning("LDAP connection failed: %s", type(exc).__name__)
            raise DirectoryUnavailable() from exc
        if accepted:
            return connection
        description = str(connection.result.get("description", ""))
        connection.unbind()
        if description == "invalidCredentials":
            raise InvalidCredentials()
        logger.warning("LDAP bind rejected: %s", sanitize_for_log(description))
        raise DirectoryUnavailable()
