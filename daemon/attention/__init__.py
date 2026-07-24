"""Attention capability — host master switch + host→participant notifications.

The participant→host bell lives in ``daemon.bell``. Both directions are gated
behind the single ``attention_enabled`` flag on ``participant_state``.
"""
