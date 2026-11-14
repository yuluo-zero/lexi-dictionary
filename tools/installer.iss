#define AppName "划词词典"
#define AppNameEn "Lexi Dictionary"
#define AppVersion "1.2.4"
#define AppPublisher "雨落降零度"
#define AppURL "https://github.com/yuluo-zero/lexi-dictionary"
#define Launcher "LexiDictionary.exe"
#define SourceDir "..\portable\lexi-dictionary-portable"
#define OutputDir "..\installer\output"

[Setup]
AppId={{7C5E2E4A-6B1F-4C3A-9B7E-2D6F1A8C4E91}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
DefaultDirName={localappdata}\Programs\LexiDictionary
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=LexiDictionary-Setup-v{#AppVersion}
SetupIconFile=..\..\app\assets\app.ico
UninstallDisplayIcon={app}\{#Launcher}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\portable\lexi-dictionary-portable\LICENSE
InfoBeforeFile=before_install.txt
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
VersionInfoVersion=1.2.4.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "data\user.db,data\user.db.bak,data\settings.json"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#Launcher}"; WorkingDir: "{app}"; IconFilename: "{app}\app\assets\app.ico"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#Launcher}"; WorkingDir: "{app}"; IconFilename: "{app}\app\assets\app.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#Launcher}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只删除安装目录里的运行时/程序文件；data 目录保留给用户手动处理。
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\LICENSES"
Type: files; Name: "{app}\main.py"
Type: files; Name: "{app}\LexiDictionary.exe"
Type: files; Name: "{app}\start.cmd"
Type: files; Name: "{app}\start.vbs"
Type: files; Name: "{app}\README.txt"
Type: files; Name: "{app}\LICENSE"
Type: files; Name: "{app}\THIRD_PARTY_LICENSES.md"
