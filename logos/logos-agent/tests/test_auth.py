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

from dataclasses import replace

import pytest
from app import auth
from app.auth import Principal, _internal_roles, _roles_from_claims, require_agent_operator
from fastapi import HTTPException


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
