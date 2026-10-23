"""Install GG's dedicated KDE capture identity in this user's application set."""
from pathlib import Path
import os
import shutil
import subprocess

project = Path(__file__).resolve().parents[1]
target = Path.home()/'.local/lib/goldgoblins/gg-eyes-capture'
entry = Path.home()/'.local/share/applications/org.goldgoblins.gg-eyes-capture.desktop'
assert not target.is_symlink() and not entry.is_symlink()
target.parent.mkdir(parents=True,exist_ok=True)
entry.parent.mkdir(parents=True,exist_ok=True)
temporary = target.with_suffix('.new')
subprocess.run(['cc','-O2','-Wall','-Wextra',str(project/'tools/gg_eyes_capture.c'),
                '-ldl','-o',str(temporary)],check=True)
temporary.chmod(0o755)
os.replace(temporary,target)
entry.write_text('[Desktop Entry]\nType=Application\n'
                 'Name=GG screen connection\n'
                 f'Exec={target}\nNoDisplay=true\nTerminal=false\n'
                 'X-KDE-DBUS-Restricted-Interfaces=org.kde.KWin.ScreenShot2\n')
entry.chmod(0o644)
refresh = shutil.which('kbuildsycoca6')
if refresh:
    subprocess.run([refresh,'--noincremental'],check=True,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('GG:s egna skärmkomponent registrerad för KDE; ingen generell Python-behörighet tillagd.')
