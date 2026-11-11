"""Synapse module that turns on end-to-end encryption for each new room.

Synapse can encrypt new rooms by default with encryption_enabled_by_default_for_room_type, but that setting has
no exception per user. The meetings bot cannot read an encrypted room. This module adds the m.room.encryption
state event to each new room, except for rooms that an exempt user creates.

Configuration in the Synapse modules list:
  - module: hoover_e2ee.EncryptNewRooms
    config:
      exempt_users: ["@meetings-bot:example.org"]
"""
import logging

logger = logging.getLogger(__name__)
ENCRYPTION = {"type": "m.room.encryption", "state_key": "", "content": {"algorithm": "m.megolm.v1.aes-sha2"}}


class EncryptNewRooms:
    def __init__(self, config, api):
        self.exempt = set(config.get("exempt_users", []))
        api.register_third_party_rules_callbacks(on_create_room=self.on_create_room)

    @staticmethod
    def parse_config(config):
        return config or {}

    async def on_create_room(self, requester, request_content, is_requester_admin):
        user = requester.user.to_string()
        if user in self.exempt:
            return
        state = request_content.setdefault("initial_state", [])
        if any(event.get("type") == "m.room.encryption" for event in state):
            return
        # Synapse applies initial_state when it creates the room, so the room is encrypted from its first event.
        state.append(dict(ENCRYPTION))
        logger.debug("encryption added to a new room of %s", user)
