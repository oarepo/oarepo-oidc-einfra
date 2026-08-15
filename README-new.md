# E-infra authentication and authorization module for InvenioRDM

This remote backend adds support for Czech e-infra AAI solution - login.e-infra.cz
allowing all members of czech academic community can use their home institution
credentials to log in.

## Installation

Add the module to your repository's pyproject.toml:

``` toml

dependencies = [
    "oarepo-oidc-einfra>=4.0.0",
    # ...
]
```

## Principles

The module uses the e-infra AAI solution as the remote backend for authentication 
and part of authorization. The following principles apply:

1. A new authentication mechanism - e-infra AAI - is added to InvenioRDM.
2. Global Role management (invenio_accounts roles): Perun AAI may provide
   capabilities `urn:geant:cesnet.cz:res:roles:<rolename>#perun.cesnet.cz`.
   if provided, these are mapped to InvenioRDM roles and assigned to the user.
3. Community role management (invenio_communities membership):    
   Perun AAI may provide community membership capabilities
   `urn:geant:cesnet.cz:res:communities:imc-cas:role:owner#perun.cesnet.cz`.
   if provided, these are mapped to InvenioRDM community membership and assigned to the user.
4. Global and community roles are stored in the database with the user. If
   there is a change in them, the change is propagated during the login 
   on the user level. For example, if the user was a member of a community
   in perun and later removed from perun, he will be removed from the community.
5. Invenio does not propagate its communities/roles to Perun. If repository owner
   wants to use Perun to manage it, the repository owner needs to configure the
   Perun groups manually.
