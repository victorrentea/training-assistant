"""Attention bell — participant → host (Direction B).

A participant taps the bell; the daemon resolves their display name, logs it,
and forwards a ``bell_ring`` to the macOS overlay via the addons bridge. Gated
behind ``attention_enabled`` on ``participant_state``.
"""
