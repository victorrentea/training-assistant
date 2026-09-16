"""The FX link's credential.

Same unambiguous alphabet as the join code (no `l`, `o`, `O` or `0`), because
this link gets read aloud and typed by hand too. Longer than a session id,
though: a join code is guessable by design and rate-limited to compensate,
while this one is the only thing standing between the internet and a noise in
the room.
"""
import secrets

# 33 symbols, none of them confusable in a projected or dictated URL.
FX_TOKEN_ALPHABET = "abcdefghijkmnpqrstuvwxyz123456789"
# 12 × log2(33) ≈ 60 bits.
FX_TOKEN_LEN = 12


def generate_fx_token() -> str:
    """A fresh link token from a CSPRNG."""
    return "".join(secrets.choice(FX_TOKEN_ALPHABET) for _ in range(FX_TOKEN_LEN))
