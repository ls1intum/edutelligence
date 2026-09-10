"""The Keycloak role check on the operator endpoints.

The browser JWT carries the *external* role name the deployment configured
for its administrators (itg-admin by default), not the internal value the
service authorizes on. The webservice maps the external name onto the
internal role (KeycloakRoleMapper / logos.auth.roles.logos-admin); these
tests pin the same mapping here, and the client scoping that comes with it:
a role granted by an unrelated client in the realm must not open the agent
endpoints, which are the only authorisation boundary on driving agents.
"""

from __future__ import annotations

import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from app import auth
from app.auth import Principal, _internal_roles, _roles_from_claims, require_agent_operator
from fastapi import HTTPException, Request


def _settings(monkeypatch, **overrides):
    patched = replace(auth.settings, **overrides)
    monkeypatch.setattr(auth, "settings", patched)
    return patched


def _principal(claims: dict) -> Principal:
    return Principal(subject="u-1", username="alice", roles=_internal_roles(_roles_from_claims(claims)))


async def _forbidden(principal: Principal) -> HTTPException:
    with pytest.raises(HTTPException) as excinfo:
        await require_agent_operator(principal)
    assert excinfo.value.status_code == 403
    return excinfo.value


class TestExternalRoleMapping:
    async def test_the_configured_external_admin_role_grants_the_required_role(self, monkeypatch):
        # The default deployment: the JWT carries itg-admin in the realm,
        # the service authorizes on the internal logos_admin value.
        settings = _settings(monkeypatch)
        principal = _principal({"realm_access": {"roles": ["itg-admin"]}})
        assert settings.required_role in principal.roles
        assert (await require_agent_operator(principal)).username == "alice"

    async def test_a_custom_configured_external_role_name_is_accepted(self, monkeypatch):
        # A deployment that grants its administrators a differently named
        # role sets KEYCLOAK_ROLES_LOGOS_ADMIN; that name, and only that
        # name, then grants access.
        _settings(monkeypatch, keycloak_roles_logos_admin=("deployer-admin",))
        accepted = _principal({"realm_access": {"roles": ["deployer-admin"]}})
        assert (await require_agent_operator(accepted)).username == "alice"

        rejected = _principal({"realm_access": {"roles": ["itg-admin"]}})
        await _forbidden(rejected)

    async def test_client_roles_of_the_configured_logos_client_count(self, monkeypatch):
        # The admin role may be a client role of the Logos client instead of
        # a realm role; the webservice reads it the same way.
        settings = _settings(monkeypatch, keycloak_client_id="logos")
        principal = _principal({"resource_access": {"logos": {"roles": ["itg-admin"]}}})
        assert settings.required_role in principal.roles

    async def test_client_scoping_follows_the_configured_client(self, monkeypatch):
        _settings(monkeypatch, keycloak_client_id="logos-prod")
        principal = _principal({"resource_access": {"logos-prod": {"roles": ["itg-admin"]}}})
        assert (await require_agent_operator(principal)).username == "alice"

    async def test_groups_are_normalized_before_mapping(self, monkeypatch):
        # Groups arrive with a leading "/"; role names never have one.
        _settings(monkeypatch)
        principal = _principal({"groups": ["/itg-admin"]})
        assert (await require_agent_operator(principal)).username == "alice"


class TestRoleRejection:
    async def test_roles_of_other_clients_do_not_grant_access(self, monkeypatch):
        # itg-admin on an unrelated client in the same realm is not the
        # deployment's admin role for this service.
        _settings(monkeypatch, keycloak_client_id="logos")
        principal = _principal(
            {
                "realm_access": {"roles": []},
                "resource_access": {
                    "logos": {"roles": []},
                    "other-client": {"roles": ["itg-admin"]},
                },
            }
        )
        await _forbidden(principal)

    async def test_unrelated_realm_roles_do_not_grant_access(self, monkeypatch):
        _settings(monkeypatch)
        principal = _principal({"realm_access": {"roles": ["chair-member", "user"]}})
        await _forbidden(principal)

    async def test_a_token_with_no_roles_at_all_is_rejected(self, monkeypatch):
        _settings(monkeypatch)
        await _forbidden(_principal({}))

    async def test_the_error_names_the_external_roles_an_operator_can_grant(self, monkeypatch):
        # The internal value is not something an operator can set in
        # Keycloak; the 403 must name the external role(s) that work.
        _settings(monkeypatch, keycloak_roles_logos_admin=("itg-admin",))
        principal = _principal({"realm_access": {"roles": ["user"]}})
        error = await _forbidden(principal)
        assert "itg-admin" in error.detail
        assert auth.settings.required_role in error.detail


class TestTokenAudience:
    """Signed-token validation across the claim shapes Keycloak emits.

    The standard browser flow (authorization code) puts the authorized
    party in ``azp`` and leaves ``aud`` absent; other flows carry it in
    ``aud``. The webservice's resource server accepts the configured
    client ID in either place, and this service must too — otherwise
    every administrator who can use the rest of Logos gets a 401 from
    the agent endpoints. These tests run the full verification path:
    signature against a JWKS stand-in, issuer, and the audience check.
    """

    ISSUER = "https://keycloak.example/realms/logos"

    @pytest.fixture
    def signer(self, monkeypatch):
        from cryptography.hazmat.primitives.asymmetric import rsa

        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)

        class _JwksStandIn:
            def get_signing_key_from_jwt(self, _token):
                return SimpleNamespace(key=private.public_key())

        _settings(
            monkeypatch,
            keycloak_audience="logos",
            keycloak_issuer_uri=self.ISSUER,
            keycloak_jwks_uri=f"{self.ISSUER}/protocol/openid-connect/certs",
        )
        monkeypatch.setattr(auth, "_jwk_client", _JwksStandIn())
        monkeypatch.setattr(auth, "_jwk_client_created_at", time.monotonic())
        return private

    def _token(self, signer, **claims) -> str:
        import jwt as pyjwt

        now = int(time.time())
        payload = {
            "iss": self.ISSUER,
            "sub": "u-1",
            "preferred_username": "alice",
            "realm_access": {"roles": ["itg-admin"]},
            "iat": now,
            "exp": now + 3600,
            **claims,
        }
        return pyjwt.encode(payload, signer, algorithm="RS256")

    @staticmethod
    def _request(token: str) -> Request:
        return Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})

    async def test_a_token_with_the_client_id_in_aud_is_accepted(self, monkeypatch, signer):
        token = self._token(signer, aud="logos")
        principal = await auth.current_principal(self._request(token))
        assert auth.settings.required_role in principal.roles

    async def test_a_token_with_the_client_id_in_azp_is_accepted(self, monkeypatch, signer):
        # The standard Keycloak browser shape: azp carries the client,
        # aud is absent. Signature and issuer still verified.
        token = self._token(signer, azp="logos")
        principal = await auth.current_principal(self._request(token))
        assert auth.settings.required_role in principal.roles

    async def test_a_token_with_the_client_id_in_an_aud_list_is_accepted(self, monkeypatch, signer):
        token = self._token(signer, aud=["some-tenant", "logos"])
        principal = await auth.current_principal(self._request(token))
        assert auth.settings.required_role in principal.roles

    async def test_a_token_without_the_client_id_in_aud_or_azp_is_rejected(self, monkeypatch, signer):
        token = self._token(signer, aud="other-client", azp="other-client")
        with pytest.raises(HTTPException) as excinfo:
            await auth.current_principal(self._request(token))
        assert excinfo.value.status_code == 401
        assert "audience" in excinfo.value.detail

    async def test_a_token_with_no_audience_claims_at_all_is_rejected(self, monkeypatch, signer):
        token = self._token(signer)
        with pytest.raises(HTTPException) as excinfo:
            await auth.current_principal(self._request(token))
        assert excinfo.value.status_code == 401

    async def test_a_token_for_a_different_issuer_is_still_rejected(self, monkeypatch, signer):
        # The audience work must not have loosened the rest of the
        # verification: a correctly signed token from another issuer is
        # still no good.
        import jwt as pyjwt

        now = int(time.time())
        token = pyjwt.encode(
            {"iss": "https://other.example/realms/other", "sub": "u-1", "azp": "logos", "exp": now + 3600},
            signer,
            algorithm="RS256",
        )
        with pytest.raises(HTTPException) as excinfo:
            await auth.current_principal(self._request(token))
        assert excinfo.value.status_code == 401
