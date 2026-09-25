"""Auditoria enxuta de autenticação e administração, sem credenciais ou LDAP bruto."""

from __future__ import annotations

import logging


logger = logging.getLogger("colaboradores.auth")

_ALLOWED_FIELDS = frozenset({
    "login", "source", "result", "remote_addr", "actor", "target",
    "from", "to", "groups", "object_guid", "registered_guid", "directory_guid",
    "transport", "tls_profile",
})


def _safe(value, *, limit: int = 256) -> str:
    """Evita injeção de linhas e limita valores controlados pelo usuário."""
    normalized = str(value if value is not None else "-")
    normalized = " ".join(normalized.replace("\r", " ").replace("\n", " ").split())
    return normalized[:limit] or "-"


def log_auth_event(event: str, **fields) -> None:
    parts = [f"event={_safe(event, limit=64)}"]
    for name, value in fields.items():
        if name not in _ALLOWED_FIELDS:
            continue
        parts.append(f"{name}={_safe(value)}")
    logger.info("%s", " ".join(parts))


def remote_addr_from_request(request) -> str | None:
    """Usa o peer TCP; não confia em X-Forwarded-For enviado pelo cliente."""
    if request is None:
        return None
    return getattr(request, "META", {}).get("REMOTE_ADDR")


def log_authentication_result(*, login: str, source: str, result, remote_addr=None) -> None:
    log_auth_event(
        "authentication_result",
        login=login,
        source=source,
        result=result.status,
        remote_addr=remote_addr,
    )


def log_guid_linked(*, login: str, object_guid, remote_addr=None) -> None:
    log_auth_event(
        "directory_guid_linked",
        login=login,
        source="DIRECTORY",
        result="GUID_LINKED",
        object_guid=object_guid,
        remote_addr=remote_addr,
    )


def log_guid_mismatch(*, login: str, registered_guid, directory_guid, remote_addr=None) -> None:
    log_auth_event(
        "directory_guid_mismatch",
        login=login,
        source="DIRECTORY",
        result="IDENTITY_MISMATCH",
        registered_guid=registered_guid,
        directory_guid=directory_guid,
        remote_addr=remote_addr,
    )


def log_admin_auth_change(*, event: str, actor: str, target: str, remote_addr=None, **fields) -> None:
    log_auth_event(
        event,
        actor=actor,
        target=target,
        remote_addr=remote_addr,
        **fields,
    )


def log_directory_transport(*, transport: str, tls_profile: str) -> None:
    log_auth_event(
        "directory_transport_configured",
        transport=transport,
        tls_profile=tls_profile,
    )
