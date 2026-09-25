"""Backend único do Django para contas locais e do Active Directory."""

from django.contrib.auth.backends import ModelBackend

from .authentication import AuthenticationService
from .auth_logging import remote_addr_from_request


class HybridAuthBackend(ModelBackend):
    """Preserva autorização Django e evita fallback entre fontes de login."""

    def __init__(self, directory_client_factory=None):
        self._directory_client_factory = directory_client_factory

    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is not None:
            request.hybrid_auth_result = None

        service = AuthenticationService(directory_client_factory=self._directory_client_factory)
        result = service.authenticate(
            username,
            password,
            remote_addr=remote_addr_from_request(request),
        )
        if request is not None:
            request.hybrid_auth_result = result
        if result.user is None:
            return None
        return result.user
