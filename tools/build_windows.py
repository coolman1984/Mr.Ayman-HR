"""Builds the Windows installer BAMS-Setup-<version>.exe (run on Windows; GitHub does it automatically, see
.github/workflows/build.yml and docs/BUILD_AND_RELEASE.md).

Steps: pack the web pages into server/_assets.py, draw the icon, compile the program into BAMS.exe with Nuitka
(Python translated to C, no readable source files), then wrap it in the Inno Setup installer.

    python tools/build_windows.py            needs: pip install nuitka ordered-set zstandard, and Inno Setup 6
"""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'build')
sys.path.insert(0, os.path.join(ROOT, 'server'))
from version import COPYRIGHT, DEVELOPER, PRODUCT, VERSION  # noqa: E402


def run(cmd):
    print('>', ' '.join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=ROOT)


def iscc():
    for p in [shutil.which('iscc'), r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe', r'C:\Program Files\Inno Setup 6\ISCC.exe']:
        if p and os.path.exists(p):
            return p
    sys.exit('Inno Setup 6 (ISCC.exe) was not found.')


def main():
    os.makedirs(BUILD, exist_ok=True)
    run([sys.executable, 'tools/make_assets.py', os.path.join('server', '_assets.py')])
    run([sys.executable, 'tools/make_icon.py', os.path.join(BUILD, 'bams.ico')])
    v4 = '.'.join((VERSION.split('.') + ['0', '0', '0'])[:4])
    run([sys.executable, '-m', 'nuitka', '--standalone', '--assume-yes-for-downloads', '--windows-console-mode=attach',
         f'--output-dir={BUILD}', '--output-filename=BAMS.exe', f'--windows-icon-from-ico={os.path.join(BUILD, "bams.ico")}',
         f'--company-name={DEVELOPER}', f'--product-name={PRODUCT}', f'--file-description={PRODUCT}', f'--file-version={v4}',
         f'--product-version={v4}', f'--copyright={COPYRIGHT}', '--include-module=nodectl', '--include-module=_assets',
         '--nofollow-import-to=tkinter,unittest,pydoc,test', os.path.join('server', 'bams_main.py')])
    dist = os.path.join(BUILD, 'bams_main.dist')
    assert os.path.exists(os.path.join(dist, 'BAMS.exe')), 'BAMS.exe was not built'
    leaks = [p for p in glob.glob(os.path.join(dist, '**', '*.py'), recursive=True)]
    assert not leaks, f'source files in the program folder: {leaks}'
    run([iscc(), f'/DAppVersion={VERSION}', f'/DAppPublisher={DEVELOPER}', f'/DAppCopyright={COPYRIGHT}', os.path.join('installer', 'bams.iss')])
    print('Done:', glob.glob(os.path.join(ROOT, 'dist', f'BAMS-Setup-{VERSION}.exe')))


if __name__ == '__main__':
    main()
