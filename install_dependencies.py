"""Install pinned push dependencies inside the isolated venv only."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

if sys.prefix == sys.base_prefix:
    raise SystemExit('Refusing installation outside a venv')
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    with urllib.request.urlopen('https://pypi.org/pypi/pip/json', timeout=30) as r:
        metadata = json.load(r)
    wheel = next(x for x in metadata['urls'] if x['filename'].endswith('.whl'))
    with urllib.request.urlopen(wheel['url'], timeout=30) as r:
        content = r.read()
    if hashlib.sha256(content).hexdigest() != wheel['digests']['sha256']:
        raise SystemExit('pip wheel integrity check failed')
    archive = root / 'pip.whl'
    archive.write_bytes(content)
    with zipfile.ZipFile(archive) as z:
        if any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts for n in z.namelist()):
            raise SystemExit('Unsafe wheel')
        z.extractall(root)
    env = dict(os.environ, PYTHONPATH=str(root), PIP_DISABLE_PIP_VERSION_CHECK='1')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', '-r',
                    str(Path(__file__).with_name('requirements.txt'))], env=env, check=True)
