"""Orquestra a autenticação local e no Active Directory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from .directory import DirectoryClient, DirectoryStatus
from .auth_logging import log_authentication_result, log_guid_linked, log_guid_mismatch
from .models import Funcionario


class AuthenticationStatus(StrEnum):
    OK = "OK"
    INVALID = "INVALID"
    DIRECTORY_UNAVAILABLE = "DIRECTORY_UNAVAILABLE"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    ACCOUNT_EXPIRED = "ACCOUNT_EXPIRED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    PASSWORD_EXPIRED = "PASSWORD_EXPIRED"
    MUST_CHANGE_PASSWORD = "MUST_CHANGE_PASSWORD"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


@dataclass(frozen=True)
class AuthenticationResult:
    user: Funcionario | None
    status: AuthenticationStatus


_DIRECTORY_STATUS_MAP = {
    DirectoryStatus.OK: AuthenticationStatus.OK,
    DirectoryStatus.INVALID: AuthenticationStatus.INVALID,
    DirectoryStatus.NOT_FOUND: AuthenticationStatus.INVALID,
    DirectoryStatus.AMBIGUOUS: AuthenticationStatus.INVALID,
    DirectoryStatus.UNAVAILABLE: AuthenticationStatus.DIRECTORY_UNAVAILABLE,
    DirectoryStatus.DISABLED: AuthenticationStatus.ACCOUNT_DISABLED,
    DirectoryStatus.EXPIRED: AuthenticationStatus.ACCOUNT_EXPIRED,
    DirectoryStatus.LOCKED: AuthenticationStatus.ACCOUNT_LOCKED,
    DirectoryStatus.PASSWORD_EXPIRED: AuthenticationStatus.PASSWORD_EXPIRED,
    DirectoryStatus.MUST_CHANGE_PASSWORD: AuthenticationStatus.MUST_CHANGE_PASSWORD,
}


def map_directory_status(status: DirectoryStatus) -> AuthenticationStatus:
    return _DIRECTORY_STATUS_MAP.get(status, AuthenticationStatus.DIRECTORY_UNAVAILABLE)


def _configured_directory_client() -> DirectoryClient:
    # Importa e valida configuração somente se um login DIRECTORY chegar aqui.
    from controle_veiculos.directory_config import get_directory_config

    config = get_directory_config()
    return DirectoryClient(
        uri=config.uri,
        base_dn=config.base_dn,
        bind_user=config.bind_user,
        bind_password=config.bind_password,
        tls_profile=config.tls_profile,
        ca_cert_file=config.ca_cert_file,
        connect_timeout=config.connect_timeout,
        operation_timeout=config.operation_timeout,
    )


class AuthenticationService:
    """Roteia a autenticação pela origem local antes de qualquer chamada LDAP."""

    def __init__(self, directory_client_factory: Callable[[], DirectoryClient] | None = None):
        self._directory_client_factory = directory_client_factory or _configured_directory_client

    def authenticate(
        self,
        username: str | None,
        password: str | None,
        *,
        remote_addr: str | None = None,
    ) -> AuthenticationResult:
        login = (username or "").strip()
        source = "UNKNOWN"
        if not login or not password:
            return self._finish(login, source, None, AuthenticationStatus.INVALID, remote_addr)

        users = get_user_model().objects.filter(username__iexact=login)
        if users.count() != 1:
            return self._finish(login, source, None, AuthenticationStatus.INVALID, remote_addr)
        user = users.first()
        if user is None:
            return self._finish(login, source, None, AuthenticationStatus.INVALID, remote_addr)
        source = user.auth_source
        if not user.is_active:
            return self._finish(login, source, None, AuthenticationStatus.INVALID, remote_addr)

        if user.auth_source == Funcionario.AuthSource.LOCAL:
            if user.check_password(password):
                return self._finish(login, source, user, AuthenticationStatus.OK, remote_addr)
            return self._finish(login, source, None, AuthenticationStatus.INVALID, remote_addr)

        client = self._directory_client_factory()
        lookup = client.find_user(user.username)
        if lookup.status is not DirectoryStatus.OK or lookup.entry is None:
            return self._finish(
                login, source, None, map_directory_status(lookup.status), remote_addr
            )

        if user.directory_guid is not None and user.directory_guid != lookup.entry.object_guid:
            log_guid_mismatch(
                login=login,
                registered_guid=user.directory_guid,
                directory_guid=lookup.entry.object_guid,
                remote_addr=remote_addr,
            )
            return self._finish(
                login, source, None, AuthenticationStatus.IDENTITY_MISMATCH, remote_addr
            )

        status = client.verify_password(lookup.entry.dn, password)
        auth_status = map_directory_status(status)
        if status is not DirectoryStatus.OK:
            return self._finish(login, source, None, auth_status, remote_addr)

        if user.directory_guid is None:
            user.directory_guid = lookup.entry.object_guid
            try:
                with transaction.atomic():
                    user.save(update_fields=["directory_guid"])
            except IntegrityError:
                # GUID já vinculado a outra conta local: negar sem propagar detalhe.
                log_guid_mismatch(
                    login=login,
                    registered_guid=None,
                    directory_guid=lookup.entry.object_guid,
                    remote_addr=remote_addr,
                )
                return self._finish(
                    login, source, None, AuthenticationStatus.IDENTITY_MISMATCH, remote_addr
                )
            log_guid_linked(
                login=login,
                object_guid=lookup.entry.object_guid,
                remote_addr=remote_addr,
            )

        return self._finish(login, source, user, AuthenticationStatus.OK, remote_addr)

    @staticmethod
    def _finish(login, source, user, status, remote_addr):
        result = AuthenticationResult(user, status)
        log_authentication_result(
            login=login,
            source=source,
            result=result,
            remote_addr=remote_addr,
        )
        return result
