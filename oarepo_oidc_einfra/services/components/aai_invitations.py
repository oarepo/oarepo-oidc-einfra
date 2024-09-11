#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""AAI (perun) membership handling"""

from flask import current_app
from invenio_access.permissions import system_identity
from invenio_accounts.models import User
from invenio_communities.communities.records.api import Community
from invenio_communities.members.records.api import Member
from invenio_communities.members.services.service import invite_expires_at
from invenio_records_resources.services.records.components.base import ServiceComponent
from invenio_records_resources.services.uow import Operation
from invenio_requests.customizations.event_types import CommentEventType
from invenio_requests.proxies import current_events_service, current_requests_service
from invenio_users_resources.proxies import current_users_service
from oarepo_runtime.i18n import lazy_gettext as _

from oarepo_oidc_einfra.services.requests.invitation import AAICommunityInvitation


class CreateAAIInvitationOp(Operation):
    """Operation to create an invitation within AAI in a background process."""

    def __init__(self, membership_request_id):
        self.membership_request_id = membership_request_id

    def on_post_commit(self, uow):
        from oarepo_oidc_einfra.tasks import create_aai_invitation

        if current_app.config["EINFRA_COMMUNITY_INVITATION_SYNCHRONIZATION"]:
            create_aai_invitation.delay(self.membership_request_id)


class AAIInvitationComponent(ServiceComponent):
    """Community AAI component that creates invitations within Perun AAI."""

    def members_invite(
        self, identity, *, record, community, errors, role, visible, message, **kwargs
    ):
        """Handler for member invitation."""

        member = record

        member_email = member.get("email")
        member_first_name = member.get("first_name")
        member_last_name = member.get("last_name")

        if not member_email:
            # can not be handled by this component
            return

        user_id = self._get_invitation_user(
            member_email, member_first_name, member_last_name
        )

        request_item = self._create_invitation_request(
            identity, community, user_id, role
        )

        # message was provided.
        if message:
            self._add_invitation_message_to_request(identity, request_item, message)

        # Create an inactive member entry linked to the request.
        self.service._add_factory(
            identity,
            community,
            role,
            visible,
            member,
            message,
            self.uow,
            active=False,
            request_id=request_item.id,
        )

        self.uow.register(CreateAAIInvitationOp(request_item["id"]))

    def members_update(
        self, identity, *, record: Member, community: Community, **kwargs
    ):
        from oarepo_oidc_einfra.tasks import change_aai_role

        if not record.user_id:
            # not a user => can not update in AAI
            return

        if current_app.config["EINFRA_COMMUNITY_MEMBER_SYNCHRONIZATION"]:
            # call it immediately. It might take a bit of time but calling
            # it later (after commit) would mean that we could end up with
            # a situation where the changes were performed locally but not
            # propagated to AAI. Then in the next login/sync the changes
            # would be reverted.
            change_aai_role(community.slug, record.user_id, record.role)

    def members_delete(
        self, identity, *, record: Member, community: Community, **kwargs
    ):
        from oarepo_oidc_einfra.tasks import remove_aai_user_from_community

        if not record.user_id:
            # not a user => can not update in AAI
            return

        if current_app.config["EINFRA_COMMUNITY_MEMBER_SYNCHRONIZATION"]:
            # call it immediately. It might take a bit of time but calling
            # it later (after commit) would mean that we could end up with
            # a situation where the changes were performed locally but not
            # propagated to AAI. Then in the next login/sync the changes
            # would be reverted.
            remove_aai_user_from_community(community.slug, record.user_id)

    def _add_invitation_message_to_request(self, identity, request_item, message):
        data = {"payload": {"content": message}}
        current_events_service.create(
            identity,
            request_item.id,
            data,
            CommentEventType,
            uow=self.uow,
            notify=False,
        )

    def _create_invitation_request(self, identity, community, user_id, role):
        title = _('Invitation to join "{community}"').format(
            community=community.metadata["title"],
        )
        description = _('You will join as "{role}".').format(role=role.title)
        request_item = current_requests_service.create(
            identity,
            {"title": title, "description": description, "user": user_id},
            AAICommunityInvitation,
            receiver=None,
            creator=community,
            topic=community,
            expires_at=invite_expires_at(),
            uow=self.uow,
        )
        return request_item

    def _get_invitation_user(self, member_email, member_first_name, member_last_name):
        u = User.query.filter_by(email=member_email.lower()).one_or_none()
        if u:
            return u.id

        user = current_users_service.create(
            system_identity,
            {
                "email": member_email,
                "profile": {
                    "full_name": f"{member_first_name} {member_last_name}",
                },
            },
        )
        return user["id"]
