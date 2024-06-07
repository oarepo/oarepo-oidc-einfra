from .api import PerunAPI
from .conn import PerunConnection
from .objects.base import AAIContainer, AAIObject
from .objects.group import AAIGroup
from .objects.user import AAIUser
from .objects.vo import AAIVO

__all__ = [
    "PerunAPI",
    "PerunConnection",
    "AAIObject",
    "AAIContainer",
    "AAIVO",
    "AAIUser",
    "AAIGroup",
]


#
# class AAIContainer:
#     def __init__(self, aai_api: "AAIApi", item_class, manager, method, method_kwargs=None,
#                  create_method=None, create_method_kwargs=None,
#                  eq=None):
#         self.aai_api = aai_api
#         self.item_class = item_class
#         self.manager = manager
#         self.method = method
#         self.method_kwargs = method_kwargs or {}
#         self.create_method = create_method
#         self.create_method_kwargs = create_method_kwargs or {}
#         self.eq = eq
#
#     @cached_property
#     def _items(self):
#         json_data = self.aai_api.send_request('GET', self.manager, self.method, **self.method_kwargs)
#         return {item['uuid']: self.item_class(self.aai_api, item) for item in json_data}
#
#     def values(self):
#         return self._items.values()
#
#     def keys(self):
#         return self._items.keys()
#
#     def items(self):
#         return self._items.items()
#
#     def invalidate(self):
#         del self._items
#
#     def __iter__(self):
#         return iter(self._items)
#
#     def __getitem__(self, item_uuid):
#         return self._items[str(item_uuid)]
#
#     def create(self, exists=False, **kwargs):
#         if not self.create_method:
#             raise NotImplementedError("Create method not defined for this container")
#
#         if exists:
#             if not self.eq:
#                 raise ValueError("eq function not defined for this container")
#             for item in self.values():
#                 if self.eq(item, kwargs):
#                     return item
#
#         json_data = self.aai_api.send_request('POST', self.manager, self.create_method,
#                                               **kwargs, **self.create_method_kwargs)
#         if not json_data:
#             del self._items
#             return None
#
#         ret = self.item_class(self.aai_api, json_data)
#         # if cached add to cache
#         if '_items' in self.__dict__:
#             self._items[ret.uuid] = ret
#
#         return ret
#
#
# class AAIVO(AAIObject):
#     @cached_property
#     def groups(self):
#         return AAIContainer(self.api, AAIGroup,
#                             'groupsManager', 'getAllGroups', {'vo': self.id})
#
#     @property
#     def deep_groups(self) -> Dict[str, "AAIGroup"]:
#         ret = {}
#         for group in self.groups.values():
#             ret[group.uuid] = group
#             ret.update(group.deep_groups)
#         return ret
#
#     def user_groups(self, user: "AAIUser"):
#         return AAIContainer(self.api, AAIGroup,
#                             'groupsManager', 'getGroupsWhereUserIsActiveMember',
#                             {'user': user.id, 'vo': self.id})
#
#
# class AAIUser(AAIObject):
#
#     @property
#     def einfra_id(self):
#         for user_attr in self.metadata.get('userAttributes', []):
#             if user_attr["friendlyNameParameter"] == "einfraid-persistent":
#                 return user_attr['value']
#         raise KeyError("einfra_id not found in user parameters, was make_rich called on the user collection?")
#
#
# class AAIGroup(AAIObject):
#     @cached_property
#     def admins(self):
#         return AAIUsers(self.api, AAIUser, 'groupsManager', 'getAdmins',
#                         method_kwargs={"group": self.id, "onlyDirectAdmins": True},
#                         create_method='addAdmin', create_method_kwargs={'group': self.id})
#
#     @cached_property
#     def rich_admins(self):
#         ret = AAIUsers(self.api, AAIUser, 'groupsManager', 'getAdmins',
#                        method_kwargs={"group": self.id, "onlyDirectAdmins": True})
#         ret.make_rich()
#         return ret
#
#     @cached_property
#     def subgroups(self) -> AAIContainer:
#         return AAIContainer(self.api, AAIGroup,
#                             'groupsManager', 'getSubGroups', {'parentGroup': self.id},
#                             create_method='createGroup', create_method_kwargs={'parentGroup': self.id},
#                             eq=lambda a, b: a.metadata['name'] == b['name'])
#
#     @property
#     def deep_groups(self) -> Dict[str, "AAIGroup"]:
#         ret = {}
#         for group in self.subgroups.values():
#             ret[group.uuid] = group
#             ret.update(group.deep_groups)
#         return ret
#
#
# class AAIUsers(AAIContainer):
#
#     def make_rich(self):
#         user_ids = [v.id for v in self.values()]
#         json_data = self.aai_api.send_request('GET', 'usersManager',
#                                               'getRichUsersWithAttributesByIds', ids=user_ids)
#         for user in json_data:
#             user_uuid = user['uuid']
#             self[user_uuid].metadata = user
#
#
#     def by_einfra_id(self, einfra_id):
#         if '_items' in self.__dict__:
#             for user in self.values():
#                 for user_attr in user.metadata.get('userAttributes', []):
#                     if user_attr["friendlyNameParameter"] =="einfraid-persistent" and user_attr['value'] == einfra_id:
#                         return user
#             raise KeyError(f"User with einfra_id={einfra_id} not found")
#
#         return AAIUser(
#             self.aai_api,
#             self.aai_api.send_request("GET", "usersManager", "getUsersByAttributeValue",
#                                   attributeName="urn:perun:user:attribute-def:def:login-namespace:einfraid-persistent-shadow",
#                                   attributeValue=einfra_id)[0])
#
# class AAIApi:
#     def __init__(self, api_url, access_token):
#         self.api_url = api_url
#         self.access_token = access_token
#
#     def send_request(self, http_method, manager, method, **params):
#         # http(s)://[server]/[authentication]/rpc/[format]/[manager]/[method]?[params]
#         url = self.api_url + f'/oauth/rpc/json/{manager}/{method}'
#         body=None
#         if http_method == 'GET':
#             separator = '?'
#             for key, value in params.items():
#                 if isinstance(value, list):
#                     for v in value:
#                         url += separator + urlencode(((key + "[]", str(v)),))
#                 else:
#                     url += separator + urlencode(((key, str(value)), ))
#                 separator = '&'
#         else:
#             body=params
#
#         t1 = time.time()
#         resp = requests.request(http_method, url,
#                                 headers={'Authorization': f'Bearer {self.access_token}'},
#                                 json=body)
#         t2 = time.time()
#         print(f"{http_method} {url} {resp.status_code} took {t2-t1} seconds")
#         if resp.status_code != 200:
#             raise Exception(f'Error {resp.status_code}: {resp.text}')
#         try:
#             return resp.json()
#         except:
#             raise Exception(f'Not a JSON: {resp.text}')
#
#     @cached_property
#     def vos(self):
#         return AAIContainer(self, item_class=AAIVO, manager='vosManager', method='getVos')
#
#     @cached_property
#     def users(self):
#         return AAIUsers(self, AAIUser, 'usersManager', 'getRichUsersWithAttributes')
