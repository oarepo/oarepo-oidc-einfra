import requests
from requests.auth import AuthBase


class PerunOIDCAuth(AuthBase):
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        r.url = r.url.replace("/auth/", "/oauth/")
        r.headers["Authorization"] = f"Bearer {self.token}"
        return r


class PerunConnection:
    def __init__(self, url, auth):
        self.url = url
        self.session = requests.Session()
        self.session.auth = auth

    def get(self, manager, method, **params):
        url = f"{self.url}/auth/rpc/json/{manager}/{method}"
        query_params = []
        for key, value in list(params.items()):
            if isinstance(value, list):
                for v in value:
                    query_params.append((key + "[]", str(v)))
            else:
                query_params.append((key, str(value)))

        return self.session.get(url, params=query_params)

    def post(self, manager, method, **params):
        url = f"{self.url}/auth/rpc/json/{manager}/{method}"
        return self.session.post(url, json=params)
