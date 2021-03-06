# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os
from urlparse import urlparse

from pyramid.response import Response
from pyramid.events import NewRequest, subscriber

import mozsvc.config


def includeme(config):
    """Install SyncServer application into the given Pyramid configurator."""
    # Set the umask so that files are created with secure permissions.
    # Necessary for e.g. created-on-demand sqlite database files.
    os.umask(0077)

    # Sanity-check the deployment settings and provide sensible defaults.
    settings = config.registry.settings
    public_url = settings.get("syncserver.public_url")
    if public_url is None:
        raise RuntimeError("you much configure syncserver.public_url")
    public_url = public_url.rstrip("/")
    settings["syncserver.public_url"] = public_url

    secret = settings.get("syncserver.secret")
    if secret is None:
        secret = os.urandom(32).encode("hex")
    sqluri = settings.get("syncserver.sqluri")
    if sqluri is None:
        rootdir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        sqluri = "sqlite:///" + os.path.join(rootdir, "syncserver.db")

    # Configure app-specific defaults based on top-level configuration.
    settings.pop("config", None)
    if "tokenserver.backend" not in settings:
        # Default to our simple static node-assignment backend
        settings["tokenserver.backend"] =\
            "syncserver.staticnode.StaticNodeAssignment"
        settings["tokenserver.sqluri"] = sqluri
        settings["tokenserver.node_url"] = public_url
        settings["endpoints.sync-1.5"] = "{node}/storage/1.5/{uid}"
    if "tokenserver.monkey_patch_gevent" not in settings:
        # Default to no gevent monkey-patching
        settings["tokenserver.monkey_patch_gevent"] = False
    if "tokenserver.applications" not in settings:
        # Default to just the sync-1.5 application
        settings["tokenserver.applications"] = "sync-1.5"
    if "tokenserver.secrets.backend" not in settings:
        # Default to a single fixed signing secret
        settings["tokenserver.secrets.backend"] = "mozsvc.secrets.FixedSecrets"
        settings["tokenserver.secrets.secrets"] = [secret]
    if "tokenserver.allow_new_users" not in settings:
        allow_new_users = settings.get("syncserver.allow_new_users")
        if allow_new_users is not None:
            settings["tokenserver.allow_new_users"] = allow_new_users
    if "hawkauth.secrets.backend" not in settings:
        # Default to the same secrets backend as the tokenserver
        for key in settings.keys():
            if key.startswith("tokenserver.secrets."):
                newkey = "hawkauth" + key[len("tokenserver"):]
                settings[newkey] = settings[key]
    if "storage.backend" not in settings:
        # Default to sql syncstorage backend
        settings["storage.backend"] = "syncstorage.storage.sql.SQLStorage"
        settings["storage.sqluri"] = sqluri
        settings["storage.create_tables"] = True
    if "browserid.backend" not in settings:
        # Default to remote verifier, with public_url as only audience
        settings["browserid.backend"] = "tokenserver.verifiers.RemoteVerifier"
        settings["browserid.audiences"] = public_url
    if "metlog.backend" not in settings:
        # Default to sending metlog output to stdout.
        settings["metlog.backend"] = "mozsvc.metrics.MetlogPlugin"
        settings["metlog.sender_class"] = "metlog.senders.StdOutSender"
        settings["metlog.enabled"] = True
    if "cef.use" not in settings:
        # Default to sensible CEF logging settings
        settings["cef.use"] = False
        settings["cef.file"] = "syslog"
        settings["cef.vendor"] = "mozilla"
        settings["cef.version"] = 0
        settings["cef.device_version"] = 0
        settings["cef.product"] = "syncserver"

    # Include the relevant sub-packages.
    config.scan("syncserver")
    config.include("syncstorage", route_prefix="/storage")
    config.include("tokenserver", route_prefix="/token")

    # Add a top-level "it works!" view.
    def itworks(request):
        return Response("it works!")

    config.add_route('itworks', '/')
    config.add_view(itworks, route_name='itworks')


@subscriber(NewRequest)
def fixup_script_name(event):
    """Event-listener to fix up SCRIPT_NAME based on public_url setting.

    This is a simple little trick to avoid futzing with configuration in
    multiple places.  The public_url setting tells us exactly what the root
    URL of the app should be, so we can use it to infer the proper value of
    SCRIPT_NAME without depending on it being configured in the WSGI server.
    """
    request = event.request
    public_url = request.registry.settings["syncserver.public_url"]
    if not request.script_name:
        request.script_name = urlparse(public_url).path.rstrip("/")


def get_configurator(global_config, **settings):
    """Load a SyncStorge configurator object from deployment settings."""
    config = mozsvc.config.get_configurator(global_config, **settings)
    config.begin()
    try:
        config.include(includeme)
    finally:
        config.end()
    return config


def main(global_config, **settings):
    """Load a SyncStorage WSGI app from deployment settings."""
    config = get_configurator(global_config, **settings)
    return config.make_wsgi_app()
