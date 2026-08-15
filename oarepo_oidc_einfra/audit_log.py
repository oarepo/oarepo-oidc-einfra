# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Audit logging for e-infra/Perun security-relevant events.

This module provides two complementary things:

- ``audit_log``: a plain :py:class:`logging.Logger` (``"e_infra.audit"``) for
  security-relevant messages (e.g. rejected/ambiguous authentication attempts) that
  do not map to one of the structured events below. Route it to its own handler in
  the logging configuration to keep it separate from ordinary application logs.
- A set of :py:class:`~invenio_audit_logs.services.action.AuditLogAction` subclasses
  (:py:class:`CommunityMemberAddedAuditLog`, :py:class:`CommunityMemberRemovedAuditLog`,
  :py:class:`RoleMemberAddedAuditLog`, :py:class:`RoleMemberRemovedAuditLog`) for the
  persisted, searchable audit log provided by ``invenio-audit-logs``. Build an event
  with ``SomeAuditLog.build(user, resource_id, ...)`` and register it via
  ``uow.register(AuditLogOp(...))`` (see ``invenio_audit_logs.services.uow.AuditLogOp``).
  Persisting these events is subject to the ``AUDIT_LOGS_ENABLED`` feature flag
  (disabled by default) - ``build()`` returns ``None`` when the flag is off.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, override

from invenio_audit_logs.services import AuditLogAction
from invenio_drafts_resources.auditlog.context import RequestContext, UserContext
from invenio_records.dictutils import dict_set
from marshmallow import fields

if TYPE_CHECKING:
    from collections.abc import Mapping

audit_log = logging.getLogger("e_infra.audit")


class ContextProtocol(Protocol):
    """Protocol for context functions that update audit log data."""

    def __call__(self, data: dict, **kwargs: Any) -> None:
        """Update data with the resolved value."""
        ...


class CauseContext(ContextProtocol):
    """Copy the ``cause`` kwarg (why the change happened, e.g. "login") into the metadata."""

    @override
    def __call__(self, data: dict, cause: str | None = None, **kwargs: Any) -> None:
        """Update data with the resolved cause."""
        dict_set(data, "metadata.cause", cause)


class CommunityRoleContext(ContextProtocol):
    """Copy the ``community_slug`` and ``role`` kwargs into the metadata."""

    @override
    def __call__(self, data: dict, community_slug: str | None = None, role: str | None = None, **kwargs: Any) -> None:
        """Update data with the resolved community slug and role."""
        dict_set(data, "metadata.community_slug", community_slug)
        dict_set(data, "metadata.role", role)


class EInfraAuditLog(AuditLogAction):
    """Base class for e-infra/Perun audit log actions."""

    context = [UserContext(), RequestContext(), CauseContext()]  # noqa RUFF012

    metadata_schema: Mapping = {
        "cause": fields.Str(
            required=True,
            metadata={"description": "What triggered this change, e.g. 'login', 'perun-dump-sync'."},
        ),
    }


class CommunityMemberAddedAuditLog(EInfraAuditLog):
    """Audit log for a user being added to a community, or their role being changed."""

    id = "community.member_added"
    resource_type = "community"
    message_template = "User {user_id} was added to community {metadata[community_slug]} with role {metadata[role]}."

    context = [*EInfraAuditLog.context, CommunityRoleContext()]  # noqa RUFF012

    metadata_schema: Mapping = {
        **EInfraAuditLog.metadata_schema,
        "community_slug": fields.Str(required=True),
        "role": fields.Str(required=True),
    }


class CommunityMemberRemovedAuditLog(EInfraAuditLog):
    """Audit log for a user being removed from a community."""

    id = "community.member_removed"
    resource_type = "community"
    message_template = "User {user_id} was removed from community {metadata[community_slug]}."

    context = [*EInfraAuditLog.context, CommunityRoleContext()]  # noqa RUFF012

    metadata_schema: Mapping = {
        **EInfraAuditLog.metadata_schema,
        "community_slug": fields.Str(required=True),
    }


class RoleMemberAddedAuditLog(EInfraAuditLog):
    """Audit log for a global role being granted to a user."""

    id = "role.member_added"
    resource_type = "role"
    message_template = "User {user_id} was granted role {resource_id}."


class RoleMemberRemovedAuditLog(EInfraAuditLog):
    """Audit log for a global role being revoked from a user."""

    id = "role.member_removed"
    resource_type = "role"
    message_template = "User {user_id} was revoked role {resource_id}."
