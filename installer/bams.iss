; Inno Setup script of the Break Area Management System (built by tools/build_windows.py).
; The same BAMS-Setup.exe installs the program on a new PC and updates it on a PC that already has it:
; only the program in Program Files is replaced, the data in %ProgramData%\BAMS is never touched.

#define MyAppName "Break Area Management System"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "Mohamed Fawzy"
#endif
#ifndef AppCopyright
  #define AppCopyright "(c) 2026 Mohamed Fawzy"
#endif

[Setup]
AppId={{7B4E2C1A-5D3F-4E8B-9A61-2F0C8D4B3E77}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright={#AppCopyright}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\BAMS
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
DisableDirPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=BAMS-Setup-{#AppVersion}
SetupIconFile=..\build\bams.ico
UninstallDisplayIcon={app}\BAMS.exe
UninstallDisplayName={#MyAppName}
LicenseFile=..\LICENSE.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put an icon on the desktop"
Name: "autostart"; Description: "Start with Windows (recommended - keeps this PC in sync with the others)"

[Dirs]
; data, backups and settings: writable for everybody who uses this PC, kept when the program is updated or removed
Name: "{commonappdata}\BAMS"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "..\build\bams_main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\BAMS.exe"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\BAMS.exe"; Tasks: desktopicon
Name: "{commonstartup}\{#MyAppName}"; Filename: "{app}\BAMS.exe"; Parameters: "--background"; Tasks: autostart

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#MyAppName}"""; Flags: runhidden; StatusMsg: "Allowing the other PCs to connect..."
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""{#MyAppName}"" dir=in action=allow program=""{app}\BAMS.exe"" enable=yes profile=any"; Flags: runhidden
Filename: "{app}\BAMS.exe"; Description: "Open the {#MyAppName} now"; Flags: nowait postinstall skipifsilent runasoriginaluser
Filename: "{app}\BAMS.exe"; Parameters: "--background"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM BAMS.exe"; Flags: runhidden; RunOnceId: "StopBAMS"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#MyAppName}"""; Flags: runhidden; RunOnceId: "FirewallRule"

[Messages]
FinishedLabel=The program is installed. Your data is kept in %ProgramData%\BAMS (also after updates).

[Code]
var
  OldPage: TInputOptionWizardPage;
  OldDirPage: TInputDirWizardPage;

function DataHome(): String;
begin
  Result := ExpandConstant('{commonappdata}\BAMS');
end;

function HasData(): Boolean;
begin
  Result := FileExists(DataHome() + '\data\auth.db') or FileExists(DataHome() + '\data\bams.db');
end;

procedure InitializeWizard();
begin
  OldPage := CreateInputOptionPage(wpSelectTasks, 'Data of the old version',
    'Was the old version (the folder with start.bat) used on this PC?',
    'If yes, the installer brings its data (break areas, users, history, photos and backups) into the new version.',
    True, False);
  OldPage.Add('No - this is a new PC, or it never had the old version');
  OldPage.Add('Yes - bring the data of the old version');
  OldPage.SelectedValueIndex := 0;
  OldDirPage := CreateInputDirPage(OldPage.ID, 'Data of the old version', 'Where is the folder of the old version?',
    'Choose the folder that contains start.bat. First close the black window of the old version.', False, '');
  OldDirPage.Add('');
  OldDirPage.Values[0] := 'C:\BAMS';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = OldPage.ID) and HasData() then
    Result := True;   { already installed with data: an update, nothing to bring }
  if (PageID = OldDirPage.ID) and (HasData() or (OldPage.SelectedValueIndex <> 1)) then
    Result := True;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Old: String;
begin
  Result := True;
  if CurPageID = OldDirPage.ID then
  begin
    Old := RemoveBackslashUnlessRoot(OldDirPage.Values[0]);
    if not (FileExists(Old + '\data\auth.db') or FileExists(Old + '\data\bams.db')) then
    begin
      MsgBox('This folder has no data of the old version (no "data" folder with the database was found).' + #13#10 +
             'Choose the folder that contains start.bat.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  { stop the running program (it is safe to stop at any moment), so its files can be replaced }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM BAMS.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(1000);
  Result := '';
end;

procedure BringOldData();
var
  Old, Moved: String;
  Code: Integer;
begin
  Old := RemoveBackslashUnlessRoot(OldDirPage.Values[0]);
  Moved := Old + '\data-moved-to-installed-version';
  { renaming first proves the old version is closed, and makes sure it can never run with the same data again }
  while not RenameFile(Old + '\data', Moved) do
  begin
    if MsgBox('The old version still seems to be running.' + #13#10 +
              'Close its black window (or restart the PC) and click Retry.', mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      MsgBox('The data of the old version was NOT brought over. Ask the developer for help.', mbError, MB_OK);
      Exit;
    end;
  end;
  Exec(ExpandConstant('{sys}\robocopy.exe'), '"' + Moved + '" "' + DataHome() + '\data" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP',
       '', SW_HIDE, ewWaitUntilTerminated, Code);
  if Code >= 8 then
  begin
    DelTree(DataHome() + '\data', True, True, True);   { never start with half of the data }
    RenameFile(Moved, Old + '\data');
    MsgBox('Copying the data failed (code ' + IntToStr(Code) + '). The old version was left as it was. Ask the developer for help.', mbError, MB_OK);
    Exit;
  end;
  if DirExists(Old + '\backups') then
    Exec(ExpandConstant('{sys}\robocopy.exe'), '"' + Old + '\backups" "' + DataHome() + '\backups" /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP',
         '', SW_HIDE, ewWaitUntilTerminated, Code);
  if FileExists(Old + '\config.json') and not FileExists(DataHome() + '\config.json') then
    FileCopy(Old + '\config.json', DataHome() + '\config.json', True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not HasData()) and (OldPage.SelectedValueIndex = 1) then
    BringOldData();
end;
