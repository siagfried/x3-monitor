"""Generate persistent VAPID identity without printing keys or credentials."""
import base64
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

path = Path(sys.argv[1])
cfg = json.loads(path.read_text())
origin = cfg['web'].get('public_origin', '')
if not origin.startswith('https://'):
    raise SystemExit('Set web.public_origin to the Tailnet HTTPS origin')
keypath = path.parent / 'vapid-private.pem'
if keypath.exists():
    key = serialization.load_pem_private_key(keypath.read_bytes(), password=None)
else:
    key = ec.generate_private_key(ec.SECP256R1())
    keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
keypath.chmod(0o640)
public = base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')
cfg['push'] = {'private_key': str(keypath), 'public_key': public, 'subject': 'https://' + urlsplit(origin).hostname}
path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
