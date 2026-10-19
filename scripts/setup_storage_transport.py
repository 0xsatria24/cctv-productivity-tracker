"""Install the official rclone transport in this workspace, verifying its SHA256."""
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import zipfile
import requests


def main():
    if platform.system() != 'Windows' or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise SystemExit('Install rclone from https://rclone.org/downloads/ and put it on PATH for this platform.')
    root = Path(__file__).resolve().parents[1] / 'runtime/tools/rclone'
    root.mkdir(parents=True, exist_ok=True)
    def read(url):
        with requests.get(url, timeout=(10,90)) as response:
            response.raise_for_status()
            if len(response.content) > 64 * 1024 * 1024:
                raise ValueError('Official download exceeds expected size')
            return response.content
    version = read('https://downloads.rclone.org/version.txt').decode().strip()
    if not re.fullmatch(r'rclone v[0-9]+\.[0-9]+\.[0-9]+', version):
        raise SystemExit('Unexpected official version response')
    tag = version.split()[1]
    name = f'rclone-{tag}-windows-amd64.zip'
    base = f'https://downloads.rclone.org/{tag}/'
    sums = read(base + 'SHA256SUMS').decode()
    expected = next((parts[0] for line in sums.splitlines() if len(parts := line.split()) == 2 and parts[-1].lstrip('*') == name), None)
    if not expected:
        raise SystemExit('Official checksum not found')
    chunks, offset = [], 0
    while True:
        # Bounded HTTP ranges also work on connections that interrupt large downloads.
        response = requests.get(base + name, headers={'Range': f'bytes={offset}-{offset+4*1024*1024-1}'}, timeout=(10,90))
        response.raise_for_status()
        if response.status_code == 200 and offset == 0:
            payload = response.content
            break
        match = re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)', response.headers.get('Content-Range',''))
        if not match or int(match[1]) != offset or int(match[3]) > 64 * 1024 * 1024:
            raise SystemExit('Unexpected official archive byte range')
        chunks.append(response.content)
        offset += len(response.content)
        if offset == int(match[3]):
            payload = b''.join(chunks)
            break
    if hashlib.sha256(payload).hexdigest() != expected:
        raise SystemExit('Official archive checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        executable = next(n for n in archive.namelist() if n.endswith('/rclone.exe'))
        (root / 'rclone.exe').write_bytes(archive.read(executable))
        for member in archive.namelist():
            if member.endswith('/README.txt'):
                (root / 'README.txt').write_bytes(archive.read(member))
    (root / 'COPYING').write_bytes(read(f'https://raw.githubusercontent.com/rclone/rclone/{tag}/COPYING'))
    (root / 'installed.json').write_text(json.dumps({'version': version, 'url': base + name, 'archive_sha256': expected}, indent=2))
    print(json.dumps({'installed': str(root / 'rclone.exe'), 'version': version, 'sha256_verified': True}))


if __name__ == '__main__':
    main()
