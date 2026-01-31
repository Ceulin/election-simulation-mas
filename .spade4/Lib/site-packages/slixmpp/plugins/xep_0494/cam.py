# Slixmpp: The Slick XMPP Library
# Copyright (C) 2025 Mathieu Pasquet
# This file is part of Slixmpp.
# See the file LICENSE for copying permission.

from asyncio import Future
from typing import Optional
from slixmpp.plugins import BasePlugin
from slixmpp.exceptions import IqError
from . import stanza


class XEP_0494(BasePlugin):
    """
    XEP-0494: Client Access Management
    """

    name = "xep_0494"
    description = "XEP-0494: Client Access Management"
    dependencies = {}

    def plugin_init(self):
        stanza.register_plugins()

    async def get_clients(self, *, timeout=None, **iqargs) -> list[stanza.Client]:
        """
        Return a list of clients who have accessed the account.

        :raises IqTimeout: If the request times out.
        :raises IqError: If the server answers with an error.
        """
        iq = self.xmpp.make_iq_get(**iqargs)
        iq.enable('list')
        iq_result = await iq.send(timeout=timeout)
        return list(iq_result['clients'])

    async def revoke(self, client_id: str, *, timeout=None, **iqargs) -> Future:
        """
        Revoke a specific client access by id.
        Revoking clients who have password access requires to change the
        password and will raise an error.

        :param client_id: id of the client to revoke.
        :raises IqTimeout: If the request times out.
        :raises IqError: If the server answers with an error.
        """
        iq = self.xmpp.make_iq_get(**iqargs)
        iq['revoke']['id'] = client_id
        return await iq.send(timeout=timeout)
