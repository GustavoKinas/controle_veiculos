"""Configuração validada do Active Directory, carregada do ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class DirectoryConfig:
    uri: str
    base_dn: str
    bind_user: str
    bind_password: str = field(repr=False)
    tls_profile: str
    ca_cert_file: str
    connect_timeout: int
    operation_timeout: int
    session_max_age: int

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "DirectoryConfig":
        values = os.environ if environ is None else environ
        required = (
            "LDAP_URI",
            "LDAP_BASE_DN",
            "LDAP_BIND_USER",
            "LDAP_BIND_PASSWORD",
            "LDAP_TLS_PROFILE",
            "LDAP_CA_CERT_FILE",
            "LDAP_NETWORK_TIMEOUT",
            "LDAP_OPERATION_TIMEOUT",
            "SESSION_MAX_AGE",
        )
        missing = [name for name in required if not (values.get(name) or "").strip()]
        if missing:
            raise ValueError("Configuração obrigatória ausente: " + ", ".join(missing))

        uri = values["LDAP_URI"].strip()
        base_dn = values["LDAP_BASE_DN"].strip()
        bind_user = values["LDAP_BIND_USER"].strip()
        bind_password = values["LDAP_BIND_PASSWORD"]
        tls_profile = values["LDAP_TLS_PROFILE"].strip().lower()
        ca_cert_file = values["LDAP_CA_CERT_FILE"].strip()

        try:
            parsed_uri = urlsplit(uri)
            hostname = parsed_uri.hostname
            port = parsed_uri.port
        except ValueError as error:
            raise ValueError("LDAP_URI inválida.") from error
        if (
            parsed_uri.scheme.lower() != "ldaps"
            or not hostname
            or parsed_uri.username
            or parsed_uri.password
            or parsed_uri.query
            or parsed_uri.fragment
            or parsed_uri.path not in ("", "/")
        ):
            raise ValueError("LDAP_URI deve ser LDAPS por FQDN, sem credenciais ou caminho.")
        try:
            ip_address(hostname)
        except ValueError:
            pass
        else:
            raise ValueError("LDAP_URI em perfil validated exige FQDN, não endereço IP.")
        if "." not in hostname.rstrip("."):
            raise ValueError("LDAP_URI deve usar o FQDN do Domain Controller.")
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Porta em LDAP_URI inválida.")
        if tls_profile != "validated":
            raise ValueError("LDAP_TLS_PROFILE deve ser validated.")

        ca_path = Path(ca_cert_file)
        if not ca_path.is_file() or not os.access(ca_path, os.R_OK):
            raise ValueError("LDAP_CA_CERT_FILE ausente ou ilegível.")

        connect_timeout = cls._positive_integer(values, "LDAP_NETWORK_TIMEOUT")
        operation_timeout = cls._positive_integer(values, "LDAP_OPERATION_TIMEOUT")
        session_max_age = cls._positive_integer(values, "SESSION_MAX_AGE")
        if session_max_age != 28800:
            raise ValueError("SESSION_MAX_AGE deve ser exatamente 28800 segundos.")

        return cls(
            uri=uri,
            base_dn=base_dn,
            bind_user=bind_user,
            bind_password=bind_password,
            tls_profile=tls_profile,
            ca_cert_file=ca_cert_file,
            connect_timeout=connect_timeout,
            operation_timeout=operation_timeout,
            session_max_age=session_max_age,
        )

    @staticmethod
    def _positive_integer(values: Mapping[str, str], name: str) -> int:
        try:
            value = int(values[name])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} deve ser um inteiro positivo.") from error
        if value <= 0:
            raise ValueError(f"{name} deve ser um inteiro positivo.")
        return value


@lru_cache(maxsize=1)
def get_directory_config() -> DirectoryConfig:
    """Carrega e valida uma única configuração imutável por processo."""
    return DirectoryConfig.from_env(os.environ)
