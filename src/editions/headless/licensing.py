"""Offline Ed25519 license verification. Private signing keys never ship."""
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json


@dataclass(frozen=True)
class License:
    edition: str
    max_cameras: int
    expires_at: datetime

    def check(self):
        if datetime.now(timezone.utc) >= self.expires_at:
            raise ValueError('License expired')


def verify_license(path, public_key_path, edition='headless'):
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    try:
        envelope = json.loads(path.read_text(encoding='utf-8'))
        payload = base64.b64decode(envelope['payload'], validate=True)
        signature = base64.b64decode(envelope['signature'], validate=True)
        key = load_pem_public_key(public_key_path.read_bytes())
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError('Expected Ed25519 public key')
        key.verify(signature, payload)
        values = json.loads(payload)
        if values['edition'] != edition or values['api_enabled'] is not True:
            raise ValueError('Edition/API not licensed')
        if type(values['max_cameras']) is not int or not 1 <= values['max_cameras'] <= 256:
            raise ValueError('Invalid camera entitlement')
        expiry = datetime.fromisoformat(values['expires_at'].replace('Z', '+00:00'))
        if expiry.tzinfo is None:
            raise ValueError('License expiry must include timezone')
        license = License(edition, values['max_cameras'], expiry)
        license.check()
        return license
    except (InvalidSignature, KeyError, TypeError, ValueError) as error:
        raise ValueError('Invalid, expired, or incompatible signed license') from error
