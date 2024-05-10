# E-infra authentication and authorization module for InvenioRDM

This remote backend adds support for Czech e-infra AAI solution - login.e-infra.cz
allowing all members of czech academic community can use their home institution
credentials to log in.

## Installation

Add the module to your repository's pyproject.toml:

``` toml

dependencies = [
    "oidc-einfra>=1.0.0",
    # ...
]

## Configuration

1. Register a new application with e-infra OIDC Provider at https://spadmin.e-infra.cz/.
When registering the application ensure that the *Redirect URI* points to:
```url
https://<my_invenio_site>:5000/oauth/authorized/e-infra/
```

![General parameters](docs/settings1.png)


![OIDC parameters](docs/settings2.png)


![Perun-specific parameters](docs/settings3.png)


2. Grab the *Client ID* and *Client Secret* after registering the application
   and add them to your ENVIRONMENT variables:
```python
INVENIO_EINFRA_CONSUMER_KEY=*Client ID*
INVENIO_EINFRA_CONSUMER_SECRET=*Client Secret*
```
3. Add the remote application to the site's `invenio.cfg`:

```python
from oidc_einfra import EINFRA_LOGIN_APP

OAUTHCLIENT_REMOTE_APPS = {
    "e-infra": EINFRA_LOGIN_APP
}
```

4. Add the e-infra public key to your invenio.cfg or environment variables:
```python
EINFRA_RSA_KEY=b'-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmho5h/lz6USUUazQaVT3\nPHloIk/Ljs2vZl/RAaitkXDx6aqpl1kGpS44eYJOaer4oWc6/QNaMtynvlSlnkuW\nrG765adNKT9sgAWSrPb81xkojsQabrSNv4nIOWUQi0Tjh0WxXQmbV+bMxkVaElhd\nHNFzUfHv+XqI8Hkc82mIGtyeMQn+VAuZbYkVXnjyCwwa9RmPOSH+O4N4epDXKk1V\nK9dUxf/rEYbjMNZGDva30do0mrBkU8W3O1mDVJSSgHn4ejKdGNYMm0JKPAgCWyPW\nJDoL092ctPCFlUMBBZ/OP3omvgnw0GaWZXxqSqaSvxFJkqCHqLMwpxmWTTAgEvAb\nnwIDAQAB\n-----END PUBLIC KEY-----\n'
```

5. Start the server and go to the login page https://127.0.0.1:5000/login/
