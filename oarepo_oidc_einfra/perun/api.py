#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Low-level API for Perun targeted at the operations needed by E-INFRA OIDC extension."""

import logging
from functools import cached_property
from typing import Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth

log = logging.getLogger("perun")


class DoesNotExist(Exception):
    """Exception raised when a resource does not exist."""


class PerunLowLevelAPI:
    """Low-level API for Perun targeted at the operations needed by E-INFRA OIDC extension.

    Note: Perun does not follow RESTful principles and the API is thus not resource-oriented,
    but rather manager-oriented and spills out implementation details. This class provides
    a thin wrapper around the Perun API.

    Note: All ids are internal Perun ids, not UUIDs or other external identifiers.
    """

    def __init__(
        self,
        base_url: str,
        service_username: str,
        service_password: str,
    ):
        """Initialize the API with the base URL and the service credentials.

        :param base_url:            URL of Perun server
        :param service_id:          the id of the service that manages stuff
        :param service_username:    the username of the service that manages stuff
        :param service_password:    the password of the service that manages stuff
        """
        self._base_url = base_url
        self._auth = HTTPBasicAuth(service_username, service_password)
        self._session = requests.Session()

    @cached_property
    def _service_id(self) -> int:
        """Get the id of the service that manages VO/groups.

        :return the id of the service
        """
        return self._perun_call_dict(
            "authzResolver",
            "getLoggedUser",
            {},
        )["id"]

    def _perun_call_dict(self, manager: str, method: str, payload: dict) -> dict:
        """Low-level call to Perun API with error handling, call returns a dict.

        :param manager:     the manager to call
        :param method:      the method to call
        :param payload:     the json payload to send
        """
        ret = self._perun_call(manager, method, payload)
        assert isinstance(ret, dict)
        return ret

    def _perun_call_list(self, manager: str, method: str, payload: dict) -> list:
        """Low-level call to Perun API with error handling, call returns a list of objects.

        :param manager:     the manager to call
        :param method:      the method to call
        :param payload:     the json payload to send
        """
        ret = self._perun_call(manager, method, payload)
        assert isinstance(ret, list)
        return ret

    def _perun_call(self, manager: str, method: str, payload: dict) -> dict | list:
        """Low-level call to Perun API with error handling.

        :param manager:     the manager to call
        :param method:      the method to call
        :param payload:     the json payload to send
        """
        log.info(
            "Perun call %s.%s with payload %s",
            manager,
            method,
            payload,
        )
        resp = self._session.post(
            f"{self._base_url}/krb/rpc/json/{manager}/{method}",
            auth=self._auth,
            json=payload,
        )
        log.info(
            "Perun call %s.%s returned status code %s",
            manager,
            method,
            resp.status_code,
        )

        if resp.status_code == 404:
            raise DoesNotExist(f"Not found returned for method {method} and {payload}")

        if (
            resp.status_code == 400
            and resp.json().get("name") == "ResourceNotExistsException"
        ):
            raise DoesNotExist(f"Not found returned for method {method} and {payload}")

        if resp.status_code < 200 or resp.status_code >= 300:
            raise Exception(f"Perun call failed: {resp.text}")
        response = resp.json()
        log.info(
            "Perun call %s.%s response %s",
            manager,
            method,
            response,
        )
        return response

    def create_group(
        self,
        *,
        name: str,
        description: str,
        parent_group_id: int,
        parent_vo: int,
        check_existing: bool = True,
    ) -> tuple[dict, bool, bool]:
        """Create a new group in Perun and set the service as its admin.

        :param name: Name of the group
        :param description: Description of the group
        :param parent_group_id: ID of the parent group
        :param parent_vo: ID of the VO the parent group belongs to
        :param check_existing: If True, check if the group already exists and do not create it
        :return: (group: json, group_created: bool, admin_created: bool)
        """
        # check if the group already exists and if not, create it

        group_created = False
        admin_created = False

        group: dict | None
        if check_existing:
            group = self.get_group_by_name(name, parent_group_id)
        else:
            group = None

        if not group:
            log.info("Creating group %s within parent %s", name, parent_group_id)

            # Create a new group in Perun
            group = self._perun_call_dict(
                "groupsManager",
                "createGroup",
                {
                    "name": name,
                    "description": description,
                    "parentGroup": parent_group_id,
                },
            )

            group_created = True
            log.info(
                "Group %s within parent %s created, id %s",
                name,
                parent_group_id,
                group["id"],
            )
            # copy form to the group
            self._perun_call(
                "registrarManager",
                "copyForm",
                {
                    "fromGroup": parent_group_id,
                    "toGroup": group["id"],
                    "idempotent": True,
                },
            )
            # copy mails from the parent to the group
            self._perun_call(
                "registrarManager",
                "copyMails",
                {
                    "fromGroup": parent_group_id,
                    "toGroup": group["id"],
                },
            )

        # check if the group has the service as an admin and if not, add it
        # if inheritance works, do not duplicate the admin here
        admins = self._perun_call(
            "groupsManager", "getAdmins", {"group": group["id"], "onlyDirectAdmins": 0}
        )
        for admin in admins:
            if str(admin["id"]) == str(self._service_id):
                break
        else:
            log.info(
                "Adding service %s as admin to group %s", self._service_id, group["id"]
            )
            self._perun_call(
                "groupsManager",
                "addAdmin",
                {"group": group["id"], "user": self._service_id},
            )
            admin_created = True

        return (group, group_created, admin_created)

    def get_group_by_name(self, name: str, parent_group_id: int) -> Optional[dict]:
        """Get a group by name within a parent group.

        :param name:                name of the group
        :param parent_group_id:     ID of the parent group
        :return:                    group or None if not found
        """
        groups = self._perun_call(
            "groupsManager", "getAllSubGroups", {"group": parent_group_id}
        )
        for group in groups:
            if group["shortName"] == name:
                return group
        return None

    def create_resource_with_group_and_capabilities(
        self,
        *,
        vo_id: int,
        facility_id: int,
        group_id: int,
        name: str,
        description: str,
        capability_attr_id: int,
        capabilities: list[str],
        perun_sync_service_id: int,
        check_existing: bool = True,
    ) -> Tuple[dict, bool]:
        """Create a new resource in Perun and assign the group to it.

        :param vo_id:           id of the virtual organization in within the resource is created
        :param facility_id:     id of the facility for which the resource is created. The service have facility manager rights
        :param group_id:        id of the group to be assigned to the resource
        :param name:            name of the resource
        :param description:             description of the resource
        :param capability_attr_id:      id of the attribute that holds the capabilities
        :param capabilities:            a list of capabilities to be set
        :param perun_sync_service_id:   id of the service that is used to export the e-infra dump
        :param check_existing:          if True, check if the resource already exists and do not create it

        :return: (resource: json, resource_created: bool)
        """
        assert isinstance(capabilities, list), "Capabilities must be a list"

        resource, resource_created = self.create_resource(
            vo_id, facility_id, name, description, check_existing
        )

        resource_id = resource["id"]

        self.assign_group_to_resource(resource_id, group_id)

        self.set_resource_capabilities(resource_id, capability_attr_id, capabilities)

        self.attach_service_to_resource(resource_id, perun_sync_service_id)

        return resource, resource_created

    def create_resource(
        self,
        vo_id: int,
        facility_id: int,
        name: str,
        description: str,
        check_existing: bool = True,
    ) -> Tuple[dict, bool]:
        """Create a new resource in Perun, optionally checking if a resource with the same name already exists.

        :param vo_id:           id of the virtual organization in within the resource is created
        :param facility_id:     id of the facility for which the resource is created
        :param name:            name of the resource
        :param description:     description of the resource
        :param check_existing:  if True, check if the resource already exists and do not create it

        :return:            (resource: json, resource_created: bool)
        """
        if check_existing:
            resource = self.get_resource_by_name(vo_id, facility_id, name)
        else:
            resource = None
        resource_created = False
        if not resource:
            log.info(
                "Creating resource %s in facility %s and vo %s",
                name,
                facility_id,
                vo_id,
            )
            resource = self._perun_call_dict(
                "resourcesManager",
                "createResource",
                {
                    "vo": vo_id,
                    "facility": facility_id,
                    "name": name,
                    "description": description,
                },
            )
            resource_created = True
            log.info(
                "Resource %s created in facility %s and vo %s, id %s",
                name,
                facility_id,
                vo_id,
                resource["id"],
            )
        return resource, resource_created

    def assign_group_to_resource(self, resource_id: int, group_id: int) -> None:
        """Assign a group to a resource.

        :param resource_id:         id of the resource
        :param group_id:            id of the group to be assigned
        """
        groups = self._perun_call(
            "resourcesManager",
            "getAssignedGroups",
            {
                "resource": resource_id,
            },
        )
        for grp in groups:
            if str(grp["id"]) == str(group_id):
                break
        else:
            log.info("Assigning group %s to resource %s", group_id, resource_id)
            self._perun_call(
                "resourcesManager",
                "assignGroupToResource",
                {"resource": resource_id, "group": group_id},
            )
            log.info("Group %s assigned to resource %s", group_id, resource_id)

    def set_resource_capabilities(
        self, resource_id: int, capability_attr_id: int, capabilities: list[str]
    ) -> None:
        """Set capabilities to a resource.

        :param resource_id:             id of the resource
        :param capability_attr_id:      internal id of the attribute that holds the capabilities
        :param capabilities:            list of capabilities to be set
        """
        # check if the resource has the capability and if not, add it
        attr = self._perun_call_dict(
            "attributesManager",
            "getAttribute",
            {"resource": resource_id, "attributeId": capability_attr_id},
        )
        value = attr["value"] or []
        if not (set(value) >= set(capabilities)):
            log.info(
                "Setting capabilities %s to resource %s", capabilities, resource_id
            )
            attr["value"] = list(set(value) | set(capabilities))
            self._perun_call(
                "attributesManager",
                "setAttribute",
                {"resource": resource_id, "attribute": attr},
            )
            log.info("Capabilities %s set to resource %s", capabilities, resource_id)

    def attach_service_to_resource(self, resource_id: int, service_id: int) -> None:
        """Attach a service to a resource.

        :param resource_id:                 id of the resource
        :param service_id:                  id of the service to be attached
        :return:
        """
        # assign sync service to the resource
        services = self._perun_call(
            "resourcesManager", "getAssignedServices", {"resource": resource_id}
        )
        for service in services:
            if str(service["id"]) == str(service_id):
                break
        else:
            log.info(
                "Assigning service %s to resource %s",
                service_id,
                resource_id,
            )
            self._perun_call(
                "resourcesManager",
                "assignService",
                {"resource": resource_id, "service": service_id},
            )
            log.info(
                "Service %s assigned to resource %s",
                service_id,
                resource_id,
            )

    def get_resource_by_name(
        self, vo_id: int, facility_id: int, name: str
    ) -> Optional[dict]:
        """Get a resource by name.

        :param vo_id:               id of the virtual organization
        :param facility_id:         id of the facility for which a resource is created
        :param name:                name of the resource
        :return:                    resource or None if not found
        """
        try:
            return self._perun_call_dict(
                "resourcesManager",
                "getResourceByName",
                {"vo": vo_id, "facility": facility_id, "name": name},
            )
        except DoesNotExist:
            return None

    def get_resource_by_capability(
        self, *, vo_id: int, facility_id: int, capability: str
    ) -> Optional[dict]:
        """Get a resource by capability.

        :param vo_id:               id of the virtual organization
        :param facility_id:         id of the facility where we search for resource
        :param capability:          capability to search for

        :return:                    resource or None if not found
        """
        # Implementation 2: iterate all resources and filter
        resources = self._perun_call(
            "resourcesManager",
            "getEnrichedResourcesForFacility",
            {"facility": facility_id},
        )
        matching_resources = [
            resource["resource"]
            for resource in resources
            if self._has_capability(resource, capability)
        ]

        # Implementation 1: searcher
        # resources = self._perun_call(
        #     "searcher",
        #     "getResources",
        #     {"attributesWithSearchingValues": {"capabilities": capability}},
        # )
        # matching_resources = [
        #     resource
        #     for resource in resources
        #     if resource["voId"] == vo_id and resource["facilityId"] == facility_id
        # ]
        if not matching_resources:
            return None
        if len(matching_resources) > 1:
            raise ValueError(
                f"More than one resource found for {capability}: {matching_resources}"
            )
        return matching_resources[0]

    def _has_capability(self, resource: dict, capability: str) -> bool:
        attributes = resource.get("attributes", [])
        for attr in attributes:
            if (
                attr["namespace"] == "urn:perun:resource:attribute-def:def"
                and attr["friendlyName"] == "capabilities"
            ):
                return capability in attr["value"]
        return False

    def get_resource_groups(self, *, resource_id: int) -> list[dict]:
        """Get groups assigned to a resource.

        :param resource_id:         id of the resource
        :return:                    list of groups
        """
        return [
            x
            for x in self._perun_call(
                "resourcesManager",
                "getAssignedGroups",
                {
                    "resource": resource_id,
                },
            )
        ]

    def get_user_by_attribute(
        self, *, attribute_name: str, attribute_value: str
    ) -> Optional[dict]:
        """Get a user by attribute.

        :param attribute_name:          name of the attribute
        :param attribute_value:         value of the attribute
        """
        users = self._perun_call(
            "usersManager",
            "getUsersByAttributeValue",
            {"attributeName": attribute_name, "attributeValue": attribute_value},
        )
        if len(users) > 1:
            raise ValueError(
                f"More than one user found for {attribute_name}={attribute_value}: {users}"
            )

        if not users:
            return None
        return users[0]

    def get_service_by_name(self, name: str) -> dict:
        """Get a service by name.

        :param name:        name of the service
        """
        return self._perun_call_dict(
            "servicesManager",
            "getServiceByName",
            {"name": name},
        )

    def get_attribute_by_name(self, name: str) -> dict:
        """Get an attribute by name.

        :param name:        name of the attribute
        """
        return self._perun_call_dict(
            "attributesManager", "getAttributeDefinition", {"attributeName": name}
        )

    def remove_user_from_group(
        self, *, vo_id: int, user_id: int, group_id: int
    ) -> None:
        """Remove a user from a group.

        :param vo_id:           id of the virtual organization
        :param user_id:           internal perun id of the user
        :param group_id:            id of the group
        """
        member = self._get_or_create_member_in_vo(vo_id, user_id)

        self._perun_call(
            "groupsManager",
            "removeMember",
            {"group": group_id, "member": member["id"]},
        )

    def add_user_to_group(self, *, vo_id: int, user_id: int, group_id: int) -> None:
        """Add a user to a group.

        :param vo_id:           id of the virtual organization
        :param user_id:           internal perun id of the user
        :param group_id:            id of the group
        """
        member = self._get_or_create_member_in_vo(vo_id, user_id)

        self._perun_call(
            "groupsManager",
            "addMember",
            {"group": group_id, "member": member["id"]},
        )

    def _get_or_create_member_in_vo(self, vo_id: int, user_id: int) -> dict:
        # TODO: create part here (but we might not need it if everything goes through invitations)
        member = self._perun_call_dict(
            "membersManager", "getMemberByUser", {"vo": vo_id, "user": user_id}
        )
        return member

    def send_invitation(
        self,
        *,
        vo_id: int,
        group_id: int,
        email: str,
        fullName: str,
        language: str,
        expiration: str,
        redirect_url: str,
    ) -> dict:
        """Send an invitation to a user to join a group.

        :param vo_id:           id of the virtual organization
        :param group_id:        id of the group
        :param email:           email of the user
        :param fullName:        username
        :param language:        language of the invitation
        :param expiration:      expiration date of the invitation, format YYYY-MM-DD
        :param redirect_url:    URL to redirect to after accepting the invitation
        """
        return self._perun_call_dict(
            "invitationsManager",
            "inviteToGroup",
            {
                "vo": vo_id,
                "group": group_id,
                "receiverName": fullName,
                "receiverEmail": email,
                "language": language,
                "expiration": expiration,
                "redirectUrl": redirect_url,
            },
        )
