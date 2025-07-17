#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""AAI (perun) membership handling."""
from typing import cast

from flask import current_app
from invenio_access.permissions import Identity, system_identity
from invenio_accounts.models import User
from invenio_communities.communities.records.api import Community
from invenio_communities.members.records.api import Member
from invenio_communities.members.services.service import invite_expires_at
from invenio_db import db
from invenio_records_resources.services.records.components.base import ServiceComponent
from invenio_records_resources.services.uow import Operation, UnitOfWork
from invenio_requests.customizations.event_types import CommentEventType
from invenio_requests.proxies import current_events_service, current_requests_service
from invenio_requests.services.requests.results import RequestItem
from invenio_users_resources.proxies import current_users_service
from marshmallow.exceptions import ValidationError
from oarepo_runtime.i18n import lazy_gettext as _

from oarepo_oidc_einfra.proxies import current_einfra_oidc, synchronization_disabled
from oarepo_oidc_einfra.services.requests.invitation import AAICommunityInvitation


class CreateAAIInvitationOp(Operation):
    """Operation to create an invitation within AAI in a background process."""

    def __init__(self, membership_request_id: str):
        """Create a new operation.

        :param membership_request_id:    id of the membership request
        """
        self.membership_request_id = membership_request_id

    def on_post_commit(self, uow: UnitOfWork) -> None:
        """Create an invitation in AAI."""
        from oarepo_oidc_einfra.tasks import create_aai_invitation

        if current_einfra_oidc.invitation_synchronization_enabled:
            create_aai_invitation.delay(self.membership_request_id)


class AAIInvitationComponent(ServiceComponent):
    """Community AAI component that creates invitations within Perun AAI."""

    def members_invite(
        self,
        identity: Identity,
        *,
        record: Member,
        community: Community,
        errors: dict,
        role: str,
        visible: bool,
        message: str,
        **kwargs: dict,
    ) -> None:
        """Invite a new member to a community.

        Will create an invitation in AAI as well.

        :param identity:        identity of the user performing the operation
        :param record:          member record
        :param community:       community record in which the member is being invited
        :param errors:          errors that occurred during the pre-invitation operation
        :param role:            role of the member in the community
        :param visible:         visibility of the member in the community
        :param message:         message to be sent to the member
        :param kwargs:          additional arguments (not used)
        """
        if synchronization_disabled.get():
            # synchronization is disabled, do not create an invitation
            return

        member = record

        if member.get("type") != "email":
            return

        member_email = member.get("id")
        member_first_name = member.get("first_name")
        member_last_name = member.get("last_name")

        if member_email and "<" in member_email:
            # email is in the format "John Doe <john.doe@test.com>"
            # extract the email address and names
            before_email, email_part = member_email.split("<", maxsplit=1)
            email_parts = email_part.split(">")
            if not email_parts or not email_parts[0].strip():
                raise ValidationError(
                    "Invalid email format - missing closing '>' or no email found"
                )
            member_email = email_parts[0].strip()

            names = before_email.strip().split()
            names.reverse()

            if names and not member_last_name:
                member_last_name = names.pop(0)
            if names and not member_first_name:
                member_first_name = names.pop(0)

        if not member_email or "@" not in member_email:
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
            {"type": "user", "id": user_id},
            message,
            self.uow,
            active=False,
            request_id=request_item.id,
        )

        self.uow.register(CreateAAIInvitationOp(request_item["id"]))

    def members_update(
        self,
        identity: Identity,
        *,
        record: Member,
        community: Community,
        **kwargs: dict,
    ) -> None:
        """Update a member in AAI.

        This callback will, if enabled in the configuration, update the member in the AAI.

        :param identity:        identity of the user performing the operation
        :param record:          member record
        :param community:       community record in which the member is being updated
        :param kwargs:          additional arguments (not used)
        """
        if synchronization_disabled.get():
            # synchronization is disabled, do not create an invitation
            return

        from oarepo_oidc_einfra.tasks import change_aai_role

        if not record.user_id:
            # not a user => can not update in AAI
            return

        if current_einfra_oidc.members_synchronization_enabled:
            # call it immediately. It might take a bit of time but calling
            # it later (after commit) would mean that we could end up with
            # a situation where the changes were performed locally but not
            # propagated to AAI. Then in the next login/sync the changes
            # would be reverted.
            change_aai_role(
                cast("str", community.slug),
                cast("int", record.user_id),
                cast("str", record.role),
            )

    def members_delete(
        self,
        identity: Identity,
        *,
        record: Member,
        community: Community,
        **kwargs: dict,
    ) -> None:
        """Remove a member from AAI.

        This callback will, if enabled in the configuration, remove the member from the AAI.

        :param identity:        identity of the user performing the operation
        :param record:          member record
        :param community:       community record from which the member is being removed
        :param kwargs:          additional arguments (not used)
        """
        if synchronization_disabled.get():
            # synchronization is disabled, do not create an invitation
            return

        from oarepo_oidc_einfra.tasks import remove_aai_user_from_community

        if not record.user_id:
            # not a user => can not update in AAI
            return

        if current_app.config.get("EINFRA_COMMUNITY_MEMBER_SYNCHRONIZATION"):
            # call it immediately. It might take a bit of time but calling
            # it later (after commit) would mean that we could end up with
            # a situation where the changes were performed locally but not
            # propagated to AAI. Then in the next login/sync the changes
            # would be reverted.
            remove_aai_user_from_community(
                cast("str", community.slug), cast("int", record.user_id)
            )

    def _add_invitation_message_to_request(
        self, identity: Identity, request_item: RequestItem, message: str
    ) -> None:
        """Add a message to the invitation request.

        :param identity:        identity of the user adding message to the request
        :param request_item:    request item, result of the _create_invitation_request
        :param message:         message to be added to the request
        """
        data = {"payload": {"content": message}}
        current_events_service.create(
            identity,
            request_item.id,
            data,
            CommentEventType,
            uow=self.uow,
            notify=False,
        )

    def _create_invitation_request(
        self, identity: Identity, community: Community, user_id: int, role: str
    ) -> RequestItem:
        """Create an invitation request in the repository.

        :param identity:        identity of the user creating the request
        :param community:       community record
        :param user_id:         user id
        :param role:            role of the user in the community
        """
        metadata: dict = cast("dict", community.metadata)
        title = _('Invitation to join "{community}"').format(
            community=metadata["title"],
        )
        description = _("You have been invited as {role} of {community}.").format(
            role=role.title, community=metadata["title"]
        )

        request_item = current_requests_service.create(
            system_identity,
            {"title": title, "description": description, "user": user_id},
            AAICommunityInvitation,
            receiver=None,
            creator=community,
            topic=community,
            expires_at=invite_expires_at(),
            uow=self.uow,
        )
        return request_item

    def _get_invitation_user(
        self,
        member_email: str,
        member_first_name: str | None,
        member_last_name: str | None,
    ) -> User:
        """Get user id for the invitation.

        If the user with the email already exists, return its id. If not, create a new user.

        :param member_email:        email of the member
        :param member_first_name:   first name of the member
        :param member_last_name:    last name of the member
        """
        u = User.query.filter_by(email=member_email.lower()).one_or_none()
        if u:
            return u.id

        if member_last_name:
            if member_first_name:
                member_full_name = f"{member_first_name} {member_last_name}"
            else:
                member_full_name = member_last_name
        elif member_first_name:
            member_full_name = member_first_name
        else:
            member_full_name = member_email.split("@")[0]

        user = current_users_service.create(
            system_identity,
            {"email": member_email},
        )

        u = db.session.query(User).get(user["id"])
        if not u.user_profile or "full_name" not in u.user_profile:
            u.user_profile = {"full_name": member_full_name}
            db.session.add(u)
            db.session.commit()
            # indexing is done in the post_commit hook

        return user["id"]
