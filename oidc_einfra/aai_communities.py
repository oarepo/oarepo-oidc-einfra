"""AAI (perun) communities mapping"""

from functools import cached_property

from invenio_accounts.models import UserIdentity
from invenio_communities.communities.records.models import CommunityMetadata
from invenio_communities.members.records.models import MemberModel
from invenio_db import db
from invenio_records_resources.proxies import current_service_registry
from invenio_records_resources.services.errors import PermissionDeniedError
from invenio_records_resources.services.records.components.base import ServiceComponent
from invenio_records_resources.services.uow import unit_of_work

from oidc_einfra.communities import remove_user_community_membership
from oidc_einfra.models import CommunityAAIMapping
from oidc_einfra.proxies import current_einfra_oidc
from oidc_einfra.utils import CommitOp, get_identity_einfra_id


class AAICommunities:
    def __init__(self, aai_api, identity, vo_uuid, communities_uuid):
        self.aai_api = aai_api
        self.identity = identity
        self.vo_uuid = vo_uuid
        self.communities_uuid = communities_uuid
        self.communities_service = current_service_registry.get("communities")

    def require_permission(self, modify=False):
        """
        Check that the user has permissions to read (modify=False)
        or create (modify=True) communities.
        :return: True if user has the permissions
        """
        # check if the user has permission on communities
        self.communities_service.require_permission(
            self.identity, "create" if modify else "read"
        )

        vo = self.aai_api.vos.get(uuid=self.vo_uuid)
        group = vo.groups.get(uuid=self.communities_uuid)

        # if not modify, reading the group is ok
        if not modify:
            return

        # if modify, get group admins and check, that the user is
        # among those
        admins = group.admins

        einfra_id = get_identity_einfra_id(self.identity)

        einfra_user = self.aai_api.users.get(einfra_id=einfra_id)
        if einfra_user not in admins:
            raise PermissionDeniedError("User is not an admin of the group")

    @unit_of_work()
    def create_community(
        self,
        community_slug,
        community_name,
        community_description=None,
        community_visibility="public",
        members_visibility="public",
        record_policy="open",
        uow=None,
        **metadata,
    ):
        self.require_permission(modify=True)

        community = CommunityMetadata.query.filter_by(slug=community_slug).one_or_none()

        # create the community
        if not community:
            self.communities_service.create(
                self.identity,
                {
                    "slug": community_slug,
                    "access": {
                        "visibility": community_visibility,
                        "members_visibility": members_visibility,
                        "record_policy": record_policy,
                    },
                    "metadata": {
                        "title": community_name,
                        "description": community_description or community_name,
                        **metadata,
                    },
                },
            )
            community = CommunityMetadata.query.filter_by(slug=community_slug).one()

        self.update_community_aai_groups(
            community.id, community_name, community_description, uow=uow
        )

    @unit_of_work()
    def update_community_aai_groups(
        self, community_id, community_name, community_description, uow=None
    ):

        mappings = {
            x.role: x
            for x in CommunityAAIMapping.query.filter_by(
                community_id=community_id
            ).all()
        }

        mappings["uuid"] = self._fix_group(
            community_id=community_id,
            role="community",
            mapping=mappings.get("uuid"),
            group_name=community_name,
            group_description=community_description,
            uow=uow,
        )
        self._fix_group_admins(mappings["uuid"].aai_group_uuid)

        community_aai_group = mappings["uuid"].aai_group_uuid

        mappings["members"] = self._fix_group(
            community_id=community_id,
            role="members",
            mapping=mappings.get("members"),
            group_name="members",
            group_description="Community members",
            parent=community_aai_group,
            uow=uow,
        )
        self._fix_group_admins(
            mappings["members"].aai_group_uuid, parent=community_aai_group
        )

        mappings["curators"] = self._fix_group(
            community_id=community_id,
            role="curators",
            mapping=mappings.get("curators"),
            group_name="curators",
            group_description="Community curators",
            parent=community_aai_group,
            uow=uow,
        )
        self._fix_group_admins(
            mappings["curators"].aai_group_uuid, parent=community_aai_group
        )

        mappings["reviewers"] = self._fix_group(
            community_id=community_id,
            role="reviewers",
            mapping=mappings.get("reviewers"),
            group_name="reviewers",
            group_description="Community reviewers (mark records as reviewed)",
            parent=community_aai_group,
            uow=uow,
        )
        self._fix_group_admins(
            mappings["reviewers"].aai_group_uuid, parent=community_aai_group
        )

        mappings["publishers"] = self._fix_group(
            community_id=community_id,
            role="publishers",
            mapping=mappings.get("publishers"),
            group_name="publishers",
            group_description="Community publishers (publishes the record)",
            parent=community_aai_group,
            uow=uow,
        )
        self._fix_group_admins(
            mappings["publishers"].aai_group_uuid, parent=community_aai_group
        )

    def synchronize_communities(self):
        for community in CommunityMetadata.query.all():
            self.synchronize_community(community.id)

    def synchronize_community(self, community_id):
        for mapping in CommunityAAIMapping.query.filter(
            CommunityAAIMapping.community_id == community_id,
            CommunityAAIMapping.role != "community",
        ):
            actual_users = self.get_community_members(community_id, mapping.role)
            aai_users = self.get_aai_users(
                mapping.aai_vo_uuid or self.vo_uuid, mapping.aai_group_uuid
            )

            for user in actual_users - aai_users:
                remove_user_community_membership(community_id, mapping.role, user)

    def get_community_members(self, community_id, role):
        return {
            member.user_id
            for member in MemberModel.query.filter_by(
                community_id=community_id, role=role
            )
        }

    def get_aai_users(self, vo_uuid, group_uuid):
        vo = self.aai_api.vos[vo_uuid]
        group = vo.groups[group_uuid]
        members = group.members
        einfra_ids = [user.einfra_id for user in members.values()]

        return {
            ui.id_user
            for ui in UserIdentity.query.filter(
                UserIdentity.method == "e-infra", UserIdentity.id.in_(einfra_ids)
            )
        }

    @cached_property
    def einfra_id(self):
        return get_identity_einfra_id(self.identity)

    def _fix_group(
        self,
        *,
        community_id,
        mapping: CommunityAAIMapping,
        role,
        group_name,
        group_description,
        parent=None,
        uow=None,
    ):
        if mapping and not mapping.managed:
            return

        group_id = mapping.aai_group_uuid if mapping else None

        # create aai group for the community
        vo = self.aai_api.vos[self.vo_uuid]

        group = None

        if group_id is not None:
            try:
                group = vo.groups[group_id]
            except KeyError:
                pass

        if group is None:
            if parent is None:
                parent_group = vo.groups[self.communities_uuid]
            else:
                parent_group = vo.groups[parent]

            # try to find the group by name
            group = None
            try:
                group = next(
                    x
                    for x in parent_group.subgroups.values()
                    if x.metadata["shortName"] == group_name
                )
            except StopIteration:
                pass

            if not group:
                group = parent_group.subgroups.create(
                    name=group_name, description=group_description
                )

        if mapping:
            if str(mapping.aai_group_uuid) != group.uuid:
                mapping.aai_group_uuid = group.uuid
                db.session.add(mapping)
        else:
            mapping = CommunityAAIMapping(
                community_id=community_id,
                role=role,
                aai_group_uuid=group.uuid,
                managed=True,
            )
            uow.register(CommitOp(mapping))
        return mapping

    def send_invitation(self, email, language):
        # TODO: does not approve the invitation, just sends generic link at the moment (you need to create the email
        # template in the perun and there is no option to put personalized register+approve link. The link present
        # there is a generic invitation link that just creates request which needs to be approved in perun)
        vo = self.aai_api.vos[self.vo_uuid]
        communities_group = vo.groups[self.communities_uuid]

        resp = self.aai_api.send_request(
            "POST",
            "registrarManager",
            "sendInvitation",
            voId=vo.id,
            groupId=communities_group.id,
            email=email,
            language=language,
        )
        print(resp)

    def _fix_group_admins(self, group_id, parent=None):
        vo = self.aai_api.vos[self.vo_uuid]
        communities_group = vo.groups[self.communities_uuid]
        grp = vo.groups[group_id]

        admins_to_create = [
            admin
            for admin in communities_group.admins.values()
            if admin.uuid not in grp.admins
        ]

        for admin in admins_to_create:
            grp.admins.add(user=admin)


class CommunityAAIComponent(ServiceComponent):

    def create(self, identity, record=None, data=None, **kwargs):
        """Create handler."""
        communities_aai_api = current_einfra_oidc.communities_aai_api(identity)
        communities_aai_api.update_community_aai_groups(
            record.id,
            data["metadata"]["title"],
            data["metadata"].get("description", ""),
            uow=self.uow,
        )

    def update(self, identity, record=None, data=None, **kwargs):
        """Update handler."""
        communities_aai_api = current_einfra_oidc.communities_aai_api(identity)
        communities_aai_api.update_community_aai_groups(
            record.id,
            data["metadata"]["title"],
            data["metadata"].get("description", ""),
            uow=self.uow,
        )

    def delete(self, identity, record=None, **kwargs):
        """Delete handler."""
        communities_aai_api = current_einfra_oidc.communities_aai_api(identity)
        communities_aai_api.delete_community_aai_groups(record.id, uow=self.uow)
