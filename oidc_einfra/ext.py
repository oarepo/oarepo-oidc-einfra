from .aai_communities import AAICommunities, CommunityAAIComponent
from .cli import perun as perun_cmd     # noqa

from invenio_oauthclient.models import RemoteToken

from .perun_api.api import PerunAPI
from .perun_api.conn import PerunConnection, PerunOIDCAuth
from .utils import get_identity_user

from invenio_records_resources.services.errors import PermissionDeniedError

class EInfraOIDCApp:
    def __init__(self, app=None):
        self.initial_api_cache = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        self.app.extensions['einfra-oidc'] = self
        self.init_config(app)

    def aai_api(self, identity):
        # get the user from identity
        user = get_identity_user(identity)
        remote_token = RemoteToken.get(
            user_id=user.id,
            client_id=self.app.config['EINFRA_CONSUMER_KEY'])
        if not remote_token:
            raise PermissionDeniedError()
        if remote_token.is_expired:
            remote_token.refresh_access_token()

        connection = PerunConnection(
            self.app.config['EINFRA_API_URL'],
            PerunOIDCAuth(remote_token.access_token))

        if not self.initial_api_cache:
            # pre-cache the API
            api = PerunAPI(connection)
            print(list(api.vos))
            vo = api.vos.get(uuid=self.app.config['EINFRA_REPOSITORY_VO'])
            vo.groups.get(uuid=self.app.config['EINFRA_COMMUNITIES_GROUP'])
            self.initial_api_cache = api._cache

        api = PerunAPI(connection)
        api._cache = self.initial_api_cache.clone()
        return api

    def communities_aai_api(self, identity):
        vo_uuid = self.app.config['EINFRA_REPOSITORY_VO']
        communities_uuid = self.app.config['EINFRA_COMMUNITIES_GROUP']

        aai_api = self.aai_api(identity)
        return AAICommunities(aai_api, identity,
                              vo_uuid, communities_uuid)

    def init_config(self, app):
        communities_components = app.config.get("COMMUNITIES_SERVICE_COMPONENTS", None)
        if isinstance(communities_components, list):
            communities_components.append(
                CommunityAAIComponent
            )
        elif not communities_components:
            app.config["COMMUNITIES_SERVICE_COMPONENTS"] = [CommunityAAIComponent]

