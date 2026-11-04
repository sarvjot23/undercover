"""Sign-ins for the tests: tokens signed with a test key, never Supabase Auth."""

import json
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from backend import auth

KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
KID = "test-key"
DANA = "dana.whitfield@undercover.example"
MARCUS = "marcus.oyelaran@undercover.example"
PRIYA = "priya.raman@undercover.example"


class TestKeys(jwt.PyJWKClient):
    """The JWKS client, serving the test key in place of Supabase's address."""

    def __init__(self) -> None:
        super().__init__("http://supabase.test/auth/v1/.well-known/jwks.json")

    def fetch_data(self) -> Any:
        public = json.loads(ECAlgorithm.to_jwk(KEY.public_key()))
        return {"keys": [{**public, "kid": KID, "alg": "ES256", "use": "sig"}]}


def install(monkeypatch: Any) -> None:
    """Point the backend's JWKS client at the test key."""
    monkeypatch.setattr(auth, "keys", TestKeys)


def token(email: str = DANA, *, expires_in: int = 3600, key: Any = KEY) -> str:
    """A Supabase-style access token for this email."""
    claims = {
        "sub": email,
        "email": email,
        "aud": auth.AUDIENCE,
        "role": "authenticated",
        "exp": int(time.time()) + expires_in,
    }
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": KID})


def as_handler(email: str = DANA) -> dict[str, str]:
    """The headers of a request from a signed-in handler."""
    return {"Authorization": f"Bearer {token(email)}"}
