; Habit Tracker installer (PLAN.md 13). Built by packaging/build.ps1, which passes:
;   /DAppVersion=X.Y.Z             from pyproject.toml
;   /DSourceDir=...                the PyInstaller output folder (HabitTracker\)
;   /DWebView2Bootstrapper=...     Microsoft's Evergreen bootstrapper, signature checked
;   /DOutputDir=... /DOutputName=...
;
; Per user, no administrator rights: %LOCALAPPDATA%\Programs\Habit Tracker.
; Uninstalling keeps %APPDATA%\HabitTracker and the Notion sign-in unless the user ticks the
; option to delete them (unticked by default), which runs HabitTracker.exe --uninstall-cleanup.
; A silent uninstall keeps them too, unless it is given /DELETEDATA=1 (for administrators, and
; for packaging/test-installer.ps1).

#ifndef AppVersion
  #error Pass /DAppVersion=X.Y.Z (packaging\build.ps1 does this).
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=<PyInstaller output folder> (packaging\build.ps1 does this).
#endif
#ifndef WebView2Bootstrapper
  #error Pass /DWebView2Bootstrapper=<MicrosoftEdgeWebview2Setup.exe> (packaging\build.ps1 does this).
#endif
#ifndef OutputDir
  #define OutputDir "..\build\installer"
#endif
#ifndef OutputName
  #define OutputName "HabitTracker-Setup-" + AppVersion
#endif

#define AppName "Habit Tracker"
#define AppExe "HabitTracker.exe"
#define Publisher "Mayank Rathour"
#define SiteUrl "https://habit-tracker.mrathour.workers.dev"
#define DataFolderName "HabitTracker"
#define WebView2Url "https://go.microsoft.com/fwlink/p/?LinkId=2124703"

[Setup]
; Never change AppId: it ties upgrades and the uninstaller to this app.
AppId={{6994A669-BBC0-4C31-915E-B0EDA46AEDCC}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL={#SiteUrl}/
AppSupportURL={#SiteUrl}/support
AppCopyright=© 2026 {#Publisher}
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} installer
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
UsePreviousAppDir=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile=icon\app-icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 version 1809 or later.
MinVersion=10.0.17763
; The running app holds this mutex (app/single_instance.py): Setup and the uninstaller ask the
; user to close it first, so files are never replaced or removed under it.
AppMutex=Local\HabitTracker
SetupMutex=HabitTrackerSetup
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppRunningError=Habit Tracker is running.%n%nClose it (its window, or the icon on the taskbar), then click OK to continue, or Cancel to stop.
UninstallAppRunningError=Habit Tracker is running.%n%nClose it (its window, or the icon on the taskbar), then click OK to continue, or Cancel to stop.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; An upgrade replaces the whole program, so files from the previous version never linger.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebView2Bootstrapper}"; DestName: "MicrosoftEdgeWebview2Setup.exe"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: WebView2Ready

[Code]
const
  WebView2ClientKey = 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  { --uninstall-cleanup exit code flags (app/uninstall.py, Outcome). }
  CleanupFailed = 1;
  CleanupNotRevoked = 2;
  CleanupPastedInternal = 4;
  CleanupPastedPat = 8;
  CleanupCredentialKept = 16;
  CleanupDataKept = 32;

var
  WebView2Failed: Boolean;
  DeleteData: Boolean;
  CleanupMessages: String;

{ --- WebView2 (mirrors app/webview2.py) ------------------------------------------------- }

function UsableVersion(Version: String): Boolean;
var
  Major: Integer;
  Dot: Integer;
begin
  Result := False;
  Version := Trim(Version);
  if (Version = '') or (Version = '0.0.0.0') then
    Exit;
  Dot := Pos('.', Version);
  if Dot > 0 then
    Major := StrToIntDef(Copy(Version, 1, Dot - 1), 0)
  else
    Major := StrToIntDef(Version, 0);
  Result := Major >= 86;
end;

function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    (RegQueryStringValue(HKCU, 'Software\' + WebView2ClientKey, 'pv', Version) and UsableVersion(Version)) or
    (RegQueryStringValue(HKLM32, 'SOFTWARE\' + WebView2ClientKey, 'pv', Version) and UsableVersion(Version)) or
    (RegQueryStringValue(HKLM64, 'SOFTWARE\' + WebView2ClientKey, 'pv', Version) and UsableVersion(Version));
end;

function WebView2Ready(): Boolean;
begin
  Result := not WebView2Failed;
end;

procedure InstallWebView2();
var
  ResultCode: Integer;
  Started: Boolean;
begin
  WizardForm.StatusLabel.Caption := 'Installing Microsoft Edge WebView2 Runtime, which Habit Tracker uses to show its window...';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  try
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    { Run without administrator rights, the bootstrapper installs the runtime for this user. }
    Started := Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '',
      SW_HIDE, ewWaitUntilTerminated, ResultCode);
  finally
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
  if WebView2Installed() then
  begin
    Log('WebView2 Runtime installed');
    Exit;
  end;
  WebView2Failed := True;
  if not Started then
    Log('The WebView2 bootstrapper could not start: ' + SysErrorMessage(ResultCode))
  else
    Log(Format('The WebView2 bootstrapper finished with code %d (0x%.8x)', [ResultCode, ResultCode]));
  if not WizardSilent() then
    MsgBox('Habit Tracker is installed, but Microsoft Edge WebView2 Runtime, which it needs to show its window, could not be installed'
      + Format(' (code 0x%.8x).', [ResultCode]) + #13#10#13#10
      + 'This usually means this PC is offline, or the download was blocked. Connect to the internet and run this installer again, '
      + 'or install the runtime from Microsoft:' + #13#10 + '{#WebView2Url}' + #13#10#13#10
      + 'Habit Tracker explains this too if you open it before the runtime is installed.',
      mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and not WebView2Installed() then
    InstallWebView2();
end;

{ --- Uninstall: keep or delete the data and the Notion sign-in ----------------------------- }

function AskAboutData(): Boolean;
var
  Form: TSetupForm;
  Intro, Detail: TNewStaticText;
  DeleteBox: TNewCheckBox;
  ContinueButton, CancelButton: TNewButton;
begin
  Form := CreateCustomForm(ScaleX(460), ScaleY(230), False, True);
  try
    Form.Caption := 'Uninstall Habit Tracker';

    Intro := TNewStaticText.Create(Form);
    Intro.Parent := Form;
    Intro.Left := ScaleX(16);
    Intro.Top := ScaleY(16);
    Intro.Width := Form.ClientWidth - ScaleX(32);
    Intro.WordWrap := True;
    Intro.AutoSize := True;
    Intro.Caption := 'Habit Tracker will be removed from this PC. Your synced entries, settings and Notion sign-in are kept, '
      + 'so reinstalling picks up where you left off.';

    DeleteBox := TNewCheckBox.Create(Form);
    DeleteBox.Parent := Form;
    DeleteBox.Left := ScaleX(16);
    DeleteBox.Top := Intro.Top + Intro.Height + ScaleY(16);
    DeleteBox.Width := Form.ClientWidth - ScaleX(32);
    DeleteBox.Height := ScaleY(20);
    DeleteBox.Caption := 'Also delete my Habit Tracker data and Notion sign-in';
    DeleteBox.Checked := False;

    Detail := TNewStaticText.Create(Form);
    Detail.Parent := Form;
    Detail.Left := ScaleX(34);
    Detail.Top := DeleteBox.Top + DeleteBox.Height + ScaleY(4);
    Detail.Width := Form.ClientWidth - ScaleX(50);
    Detail.WordWrap := True;
    Detail.AutoSize := True;
    Detail.Caption := 'Deletes the copy of your work log, settings and logs in ' + ExpandConstant('{userappdata}\{#DataFolderName}')
      + ', and the Notion sign-in saved in Windows Credential Manager. If you connected with Notion sign-in, '
      + 'Habit Tracker''s access is also cancelled with Notion. Nothing in Notion itself is changed.';

    ContinueButton := TNewButton.Create(Form);
    ContinueButton.Parent := Form;
    ContinueButton.Caption := 'Uninstall';
    ContinueButton.ModalResult := mrOk;
    ContinueButton.Default := True;
    ContinueButton.Width := ScaleX(90);
    ContinueButton.Height := ScaleY(26);

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    CancelButton.Width := ScaleX(90);
    CancelButton.Height := ScaleY(26);

    Form.ClientHeight := Detail.Top + Detail.Height + ScaleY(56);
    CancelButton.Top := Form.ClientHeight - CancelButton.Height - ScaleY(14);
    CancelButton.Left := Form.ClientWidth - CancelButton.Width - ScaleX(16);
    ContinueButton.Top := CancelButton.Top;
    ContinueButton.Left := CancelButton.Left - ContinueButton.Width - ScaleX(8);
    Form.ActiveControl := ContinueButton;

    Result := Form.ShowModal() = mrOk;
    DeleteData := Result and DeleteBox.Checked;
  finally
    Form.Free();
  end;
end;

function InitializeUninstall(): Boolean;
begin
  DeleteData := False;
  CleanupMessages := '';
  if UninstallSilent() then
  begin
    { A silent uninstall keeps the data unless told otherwise on the command line. }
    DeleteData := ExpandConstant('{param:DELETEDATA|0}') = '1';
    Result := True;
  end
  else
    Result := AskAboutData();
  Log(Format('Delete data and sign-in: %d', [Ord(DeleteData)]));
end;

procedure AddMessage(Text: String);
begin
  if CleanupMessages <> '' then
    CleanupMessages := CleanupMessages + #13#10#13#10;
  CleanupMessages := CleanupMessages + Text;
end;

procedure DeleteDataAndSignIn();
var
  Code: Integer;
  DataDir: String;
begin
  { The program is still in place here: it cancels and deletes the sign-in, then deletes its own
    files in the data folder. }
  if not Exec(ExpandConstant('{app}\{#AppExe}'), '--uninstall-cleanup', '', SW_HIDE,
    ewWaitUntilTerminated, Code) then
  begin
    Log('Could not run the cleanup: ' + SysErrorMessage(Code));
    Code := CleanupFailed;
  end;
  Log(Format('Cleanup finished with code %d', [Code]));

  if (Code and CleanupNotRevoked) <> 0 then
    AddMessage('Your Notion sign-in was deleted from this PC, but Notion''s access could not be cancelled, '
      + 'probably because this PC is offline. To cancel it, open Notion, go to Settings, then Connections, and remove Habit Tracker.');
  if (Code and CleanupPastedInternal) <> 0 then
    AddMessage('Your token was deleted from this PC. It still works until you delete the internal connection in Notion''s developer portal.');
  if (Code and CleanupPastedPat) <> 0 then
    AddMessage('Your token was deleted from this PC. It still works until it expires or you revoke it under Personal access tokens in Notion''s developer portal.');
  if ((Code and CleanupFailed) <> 0) or ((Code and CleanupCredentialKept) <> 0) then
    AddMessage('Your Notion sign-in could not be deleted. To delete it yourself, open Credential Manager from the Start menu, '
      + 'choose Windows Credentials, and remove the entry named HabitTracker.');

  { The default data folder is Habit Tracker's own, so anything left in it goes too. }
  DataDir := ExpandConstant('{userappdata}\{#DataFolderName}');
  if DirExists(DataDir) then
    DelTree(DataDir, True, True, True);
  if DirExists(DataDir) or ((Code and CleanupDataKept) <> 0) then
    AddMessage('Some of Habit Tracker''s data could not be deleted, perhaps because a file is open in another program. '
      + 'You can delete this folder yourself:' + #13#10 + DataDir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usUninstall) and DeleteData then
    DeleteDataAndSignIn();
  if (CurUninstallStep = usPostUninstall) and (CleanupMessages <> '') then
  begin
    Log(CleanupMessages);
    SuppressibleMsgBox(CleanupMessages, mbInformation, MB_OK, IDOK);
  end;
end;
