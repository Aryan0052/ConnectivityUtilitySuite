# -*- mode: python ; coding: utf-8 -*-
# ONE file: dist\Nelumbo Connectivity Utility Suite.exe  (send only this file - it opens by double-click)
import os
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['serial.tools.list_ports']
hiddenimports += collect_submodules('views')
hiddenimports += collect_submodules('pymodbus')

# 13.ico is really a 969 x 733 JPEG picture with an .ico name. Windows needs a real, SQUARE .ico for the exe /
# taskbar icon, so at build time the same picture is put in the middle of a square with transparent bands
# above and below (nothing else changed) and saved as a real .ico in the build folder (not in git).
# Needs Pillow:  pip install pillow
def _square_ico(src='assets/13.ico', dst='build/app_icon.ico'):
    try:
        from PIL import Image
    except ImportError:
        print('*** pip install pillow  (needed for the exe icon) ***')
        return src
    picture = Image.open(src).convert('RGBA')
    side = max(picture.size)
    square = Image.new('RGBA', (side, side), (0, 0, 0, 0))
    square.paste(picture, ((side - picture.width) // 2, (side - picture.height) // 2))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    square.save(dst, format='ICO', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return dst


ICON = _square_ico()


a = Analysis(
    ['app.py'],
    pathex=['views'],
    binaries=[],
    datas=[('assets', 'assets')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Nelumbo Connectivity Utility Suite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[ICON],
)