"""Entry point of the installed program (BAMS.exe, built by tools/build_windows.py).

  BAMS.exe                 start the system and open it in the browser
  BAMS.exe --background    start the system without opening the browser (used when Windows starts)
  BAMS.exe tool <command>  maintenance tools of server/nodectl.py (status, verify, rebuild, reset-admin,
                           export-authority <file>, import-authority <file>) - run it from a command window

The installed program keeps its data outside the program folder, in %ProgramData%\\BAMS (config.json, data,
backups), so an update replaces only the program and never touches the data. The portable version (start.bat)
keeps working as before with everything inside its own folder.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def home_dir():
    """Where the installed program keeps config, data and backups."""
    base = os.environ.get('ProgramData') or os.environ.get('ALLUSERSPROFILE') or os.path.expanduser('~')
    return os.path.join(base, 'BAMS')


def main(argv):
    if sys.stdout is None:  # started without a console window
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = sys.stdout
    if not os.environ.get('BAMS_HOME'):
        os.environ['BAMS_HOME'] = home_dir()
    os.makedirs(os.environ['BAMS_HOME'], exist_ok=True)
    if argv[:1] == ['tool']:
        import nodectl
        return nodectl.main(argv[1:])
    import app
    app.main(background='--background' in argv)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
