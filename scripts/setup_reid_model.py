"""Download checksum-pinned Open Model Zoo retail-0287 FP32 artifacts."""
from pathlib import Path
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'person-reidentification-retail-0287'
SOURCE = f'https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1/{MODEL}/FP32/'
ARTIFACTS = {
    'xml': (451147, 'a8a6956dec193dfa0095319c5f0bfccd5b9eaaac4d30ddc12a79aa7a99f0dcf953aae7b76764239d383ff39f8f8a1477'),
    'bin': (2362128, '7e962ed07992edeff11eac8f6280ea5761d8ddfb699bcd3c79cfeac10773c5f4d4577ca4c048a7fa50977cdfc14a74ba'),
}


def main():
    destination = ROOT/'models'/'reid'/MODEL
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {'model_id': MODEL+'-omz-2023.0-FP32', 'source': SOURCE,
                'license': 'Apache-2.0', 'precision': 'FP32', 'preprocessing_revision': 'bgr-linear-raw-v1',
                'dimensions': 256, 'input': {'layout': 'NCHW', 'color': 'BGR', 'height': 256, 'width': 128,
                                            'mean': [0, 0, 0], 'scale': [1, 1, 1]}}
    for extension, (size, digest) in ARTIFACTS.items():
        path = destination/f'{MODEL}.{extension}'
        def valid(candidate):
            return candidate.is_file() and candidate.stat().st_size == size and hashlib.sha384(candidate.read_bytes()).hexdigest() == digest
        if not valid(path):
            temporary = path.with_suffix('.download')
            try:
                with urllib.request.urlopen(SOURCE+path.name, timeout=60) as response, temporary.open('wb') as output:
                    while chunk := response.read(1024*1024):
                        output.write(chunk)
                if not valid(temporary):
                    raise RuntimeError(f'ReID {extension} checksum mismatch')
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
        manifest[extension] = {'path': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'ReID model verified: {destination / "manifest.json"}')


if __name__ == '__main__':
    main()
