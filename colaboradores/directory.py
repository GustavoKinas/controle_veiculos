"""Cliente LDAP tipado para autenticação no Active Directory."""

from __future__ import annotations

import re
import ssl
import uuid
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

from ldap3 import SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars


class DirectoryStatus(StrEnum):
    OK = "OK"
    INVALID = "INVALID"
    DISABLED = "DISABLED"
    EXPIRED = "EXPIRED"
    LOCKED = "LOCKED"
    PASSWORD_EXPIRED = "PASSWORD_EXPIRED"
    MUST_CHANGE_PASSWORD = "MUST_CHANGE_PASSWORD"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class DirectoryEntry:
    dn: str
    object_guid: uuid.UUID


@dataclass(frozen=True)
class DirectoryLookup:
    status: DirectoryStatus
    entry: DirectoryEntry | None = None


_SUBCODE_STATUS = {
    "525": DirectoryStatus.INVALID,
    "52e": DirectoryStatus.INVALID,
    "530": DirectoryStatus.DISABLED,
    "531": DirectoryStatus.DISABLED,
    "532": DirectoryStatus.PASSWORD_EXPIRED,
    "533": DirectoryStatus.DISABLED,
    "701": DirectoryStatus.EXPIRED,
    "773": DirectoryStatus.MUST_CHANGE_PASSWORD,
    "775": DirectoryStatus.LOCKED,
}
_SUBCODE_RE = re.compile(r"\bdata\s+([0-9a-f]{3})\b", re.IGNORECASE)


class DirectoryClient:
    """Busca um usuário por sAMAccountName e valida sua senha via LDAPS."""

    def __init__(
        self,
        uri: str,
        base_dn: str,
        bind_user: str,
        bind_password: str,
        tls_profile: str,
        ca_cert_file: str,
        connect_timeout: int,
        operation_timeout: int,
    ) -> None:
        parsed = urlsplit(uri)
        if parsed.scheme.lower() != "ldaps" or not parsed.hostname:
            raise ValueError("DirectoryClient exige uma URI LDAPS com hostname.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("LDAP_URI não pode conter credenciais, query ou fragmento.")
        if tls_profile != "validated":
            raise ValueError("DirectoryClient exige LDAP_TLS_PROFILE=validated.")
        if not ca_cert_file:
            raise ValueError("CA é obrigatória para LDAPS validado.")
        if connect_timeout <= 0 or operation_timeout <= 0:
            raise ValueError("Timeouts LDAP devem ser positivos.")

        hostname = parsed.hostname
        tls = Tls(
            ca_certs_file=ca_cert_file,
            validate=ssl.CERT_REQUIRED,
            valid_names=[hostname],
        )
        self._server = Server(
            hostname,
            port=parsed.port or 636,
            use_ssl=True,
            tls=tls,
            connect_timeout=connect_timeout,
        )
        self._base_dn = base_dn
        self._bind_user = bind_user
        self._bind_password = bind_password
        self._operation_timeout = operation_timeout

    @staticmethod
    def _search_entries(response) -> list[dict]:
        return [
            item
            for item in response or []
            if item.get("type") == "searchResEntry"
        ]

    @staticmethod
    def _bind_status(result: dict | None) -> DirectoryStatus:
        result = result or {}
        if result.get("result") != 49 and result.get("description") != "invalidCredentials":
            return DirectoryStatus.UNAVAILABLE

        message = result.get("message") or ""
        match = _SUBCODE_RE.search(message)
        if match:
            return _SUBCODE_STATUS.get(match.group(1).lower(), DirectoryStatus.INVALID)
        return DirectoryStatus.INVALID

    @classmethod
    def _exception_status(cls, error: Exception) -> DirectoryStatus:
        result = getattr(error, "result", None)
        if isinstance(result, dict):
            status = cls._bind_status(result)
            if status is not DirectoryStatus.UNAVAILABLE:
                return status
        return DirectoryStatus.UNAVAILABLE

    def find_user(self, login: str) -> DirectoryLookup:
        if not login:
            return DirectoryLookup(DirectoryStatus.NOT_FOUND)

        escaped_login = escape_filter_chars(login)
        search_filter = (
            "(&(objectCategory=person)(objectClass=user)(sAMAccountName={}))"
        ).format(escaped_login)

        try:
            with Connection(
                self._server,
                user=self._bind_user,
                password=self._bind_password,
                auto_bind=False,
                auto_referrals=False,
                receive_timeout=self._operation_timeout,
                read_only=True,
            ) as connection:
                if not connection.bind():
                    return DirectoryLookup(DirectoryStatus.UNAVAILABLE)
                searched = connection.search(
                    search_base=self._base_dn,
                    search_filter=search_filter,
                    search_scope=SUBTREE,
                    attributes=["objectGUID"],
                    size_limit=2,
                )
                if not searched:
                    return DirectoryLookup(DirectoryStatus.UNAVAILABLE)
                entries = self._search_entries(connection.response)
        except (LDAPException, OSError, ssl.SSLError, TimeoutError) as error:
            return DirectoryLookup(self._exception_status(error))

        if not entries:
            return DirectoryLookup(DirectoryStatus.NOT_FOUND)
        if len(entries) > 1:
            return DirectoryLookup(DirectoryStatus.AMBIGUOUS)

        try:
            entry = entries[0]
            raw_guid = entry["raw_attributes"]["objectGUID"][0]
            guid = uuid.UUID(bytes_le=raw_guid)
            return DirectoryLookup(
                DirectoryStatus.OK,
                DirectoryEntry(dn=entry["dn"], object_guid=guid),
            )
        except (KeyError, IndexError, TypeError, ValueError):
            return DirectoryLookup(DirectoryStatus.UNAVAILABLE)

    def verify_password(self, dn: str, password: str) -> DirectoryStatus:
        if not password:
            return DirectoryStatus.INVALID

        try:
            with Connection(
                self._server,
                user=dn,
                password=password,
                auto_bind=False,
                auto_referrals=False,
                receive_timeout=self._operation_timeout,
                read_only=True,
            ) as connection:
                if connection.bind():
                    return DirectoryStatus.OK
                return self._bind_status(connection.result)
        except (LDAPException, OSError, ssl.SSLError, TimeoutError) as error:
            return self._exception_status(error)
