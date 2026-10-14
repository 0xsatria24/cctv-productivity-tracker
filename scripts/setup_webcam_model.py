"""Download the pinned Apache-2.0 YOLOX model from official OpenCV Zoo."""
from pathlib import Path
import argparse
import hashlib
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REVISION = "47534e27c9851bb1128ccc0102f1145e27f23f98"
SHA256 = "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063"
URL = f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{REVISION}/models/object_detection_yolox/object_detection_yolox_2022nov.onnx"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['nanodet', 'yolox'], default='yolox')
    args = parser.parse_args()
    expected = SHA256 if args.model == 'yolox' else '4b82da9944b88577175ee23a459dce2e26e6e4be573def65b1055dc2d9720186'
    source = URL if args.model == 'yolox' else f'https://media.githubusercontent.com/media/opencv/opencv_zoo/{REVISION}/models/object_detection_nanodet/object_detection_nanodet_2022nov.onnx'
    destination = ROOT / "models" / f"webcam-{args.model}.onnx"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
        print("Model webcam sudah tersedia dan checksum valid.")
        return
    temporary = destination.with_suffix(".download")
    try:
        with urllib.request.urlopen(source, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Checksum model tidak cocok; unduhan tidak digunakan")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Model webcam siap: {destination}")


if __name__ == "__main__":
    main()
