"""Build two isolated release ZIPs from one source tree; never copy model/license secrets."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(edition, output):
    with tempfile.TemporaryDirectory(prefix='cctv-build-') as temporary:
        stage = Path(temporary)
        source = stage / 'src'
        shutil.copytree(ROOT / 'src/cctv_tracker', source / 'cctv_tracker', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (source / 'editions').mkdir()
        shutil.copy2(ROOT / 'src/editions/__init__.py', source / 'editions/__init__.py')
        shutil.copytree(ROOT / 'src/editions' / edition, source / 'editions' / edition, ignore=shutil.ignore_patterns('__pycache__'))
        if edition == 'headless':
            for name in ('api.py', 'dashboard.py', 'cli.py', '__main__.py', 'camera_wall.py'):
                (source / 'cctv_tracker' / name).unlink()
        project = f'''[build-system]
requires = ["setuptools==80.9.0"]
build-backend = "setuptools.build_meta"
[project]
name = "cctv-{edition}-edition"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["tzdata==2025.2"]
[tool.setuptools.packages.find]
where = ["src"]
[tool.setuptools.package-data]
cctv_tracker = ["resources/*.sql", "resources/*.json"]
"editions.headless" = ["*.html"]
'''
        (stage / 'pyproject.toml').write_text(project)
        bundle = stage / 'release'
        bundle.mkdir()
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-cache-dir', '--no-deps', '--no-build-isolation', '--wheel-dir', str(bundle), str(stage)], check=True)
        if edition == 'headless':
            shutil.copy2(ROOT / 'requirements.headless.lock.txt', bundle / 'requirements.txt')
            shutil.copy2(ROOT / 'config/headless.example.json', bundle / 'config.json')
            shutil.copy2(ROOT / 'docs/runtime/HEADLESS.md', bundle / 'README.md')
            shutil.copytree(ROOT / 'sdk', bundle / 'sdk', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copy2(ROOT / 'docs/runtime/headless-openapi.json', bundle / 'openapi.json')
            launch = (ROOT / 'run-headless.ps1').read_text(encoding='utf-8')
            (bundle / 'Start Headless.cmd').write_text('@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"\npause\n')
        else:
            ui = ROOT / 'prototype/dist'
            if not (ui / 'index.html').exists():
                raise RuntimeError('Build the Enterprise frontend first: npm run build in prototype/')
            shutil.copytree(ui, bundle / 'ui')
            lines = (ROOT / 'requirements.windows-cpu.lock.txt').read_text().splitlines()
            (bundle / 'requirements.txt').write_text('\n'.join(line for line in lines if not line.startswith('-e ')) + '\n')
            launch = "$env:CCTV_MODEL_DIR = Join-Path $PSScriptRoot 'models'\n& $PSScriptRoot/.venv/Scripts/python.exe -m editions.enterprise --ui-dir $PSScriptRoot/ui @args\nexit $LASTEXITCODE\n"
            (bundle / 'README.md').write_text('CCTV Enterprise: jalankan install.ps1, letakkan model webcam-yolox.onnx di models/, lalu run.ps1. Frontend sudah disertakan. Default OpenVINO GPU; gunakan run.ps1 --detector yolox untuk ONNX CPU. Model tidak disertakan. Jalankan dalam environment terpisah dari Headless.\n')
        (bundle / 'run.ps1').write_text(launch)
        (bundle / 'install.ps1').write_text('''$ErrorActionPreference = 'Stop'
py -3.12 -m venv "$PSScriptRoot/.venv"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 venv creation failed' }
& "$PSScriptRoot/.venv/Scripts/python.exe" -m pip install --no-deps -r "$PSScriptRoot/requirements.txt"
if ($LASTEXITCODE -ne 0) { throw 'Runtime install failed' }
$wheel = (Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.whl').FullName
& "$PSScriptRoot/.venv/Scripts/python.exe" -m pip install --no-deps $wheel
if ($LASTEXITCODE -ne 0) { throw 'Edition install failed' }
''')
        destination = output / f'cctv-{edition}-0.1.0.zip'
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in bundle.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(bundle))
        print(destination)


if __name__ == '__main__':
    output = ROOT / 'dist/editions'
    output.mkdir(parents=True, exist_ok=True)
    for edition in ('enterprise', 'headless'):
        build(edition, output)
