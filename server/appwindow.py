"""Opens the program in its own window, like a separate app: no tabs, no address bar, its own entry in the taskbar with the
program icon. It uses the app mode of Microsoft Edge (on every Windows 10/11 PC) or Google Chrome, with an own window profile
(%LOCALAPPDATA%\\BAMS\\AppWindow) so it never mixes with the person's normal browser tabs. Without one of them - or with
"app_window": false in config.json - the normal browser opens, as before.
"""
import os
import shutil
import subprocess
import webbrowser

FIRST_SIZE = '1440,900'  # only for the very first window; afterwards the browser remembers the size the person chose
POLICY_KEYS = {'msedge.exe': r'SOFTWARE\Policies\Microsoft\Edge', 'chrome.exe': r'SOFTWARE\Policies\Google\Chrome'}


def enabled(value):
    """the config value app_window: anything but an explicit "off" means on"""
    return not (value is False or value == 0 or str(value).strip().lower() in ('false', 'no', 'off', '0'))


def forced_signin(exe):
    """True when a company policy forces a sign-in in that browser: a new window profile would show the sign-in page first"""
    if os.name != 'nt':
        return False
    key = POLICY_KEYS.get(os.path.basename(exe).lower())
    if not key:
        return False
    try:
        import winreg
    except ImportError:
        return False
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, key) as k:
                if winreg.QueryValueEx(k, 'BrowserSignin')[0] == 2:
                    return True
        except OSError:
            continue
    return False


def browsers():
    """paths of browsers that have an app mode, best first"""
    if os.name == 'nt':
        roots = [os.environ.get(k) for k in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA')]
        for rel in (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe'):
            for root in roots:
                if root:
                    yield os.path.join(root, rel)
    else:
        for name in ('microsoft-edge', 'google-chrome', 'chromium', 'chromium-browser'):
            path = shutil.which(name)
            if path:
                yield path


def profile_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), '.cache')
    return os.path.join(base, 'BAMS', 'AppWindow')


def command(exe, url):
    cmd = [exe, f'--app={url}', f'--user-data-dir={profile_dir()}', '--no-first-run', '--no-default-browser-check']
    if not os.path.isdir(profile_dir()):
        cmd.append(f'--window-size={FIRST_SIZE}')
    return cmd


def open_window(url, app_window=True):
    """True when the program opened in its own window, False when the normal browser was used"""
    if enabled(app_window):
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else 0
        for exe in browsers():
            if not os.path.isfile(exe) or forced_signin(exe):
                continue
            try:
                subprocess.Popen(command(exe, url), close_fds=True, creationflags=flags,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
    webbrowser.open(url)
    return False
