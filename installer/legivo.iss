; Instalador do Legivo (Inno Setup 6: https://jrsoftware.org/isinfo.php)
; Gere com:  python tools/release.py        (ele chama o ISCC com as opções abaixo)
; Manualmente: ISCC /DAppVersion=0.12.0 /DSourceDir=..\local\release\full /DEdition=completa installer\legivo.iss
;
; Instala só para o usuário atual (sem pedir administrador) em %LocalAppData%\Programs\Legivo. Isso importa: o
; Legivo grava as configurações ao lado do programa (modo portátil) e a pasta Program Files não permite isso.

#ifndef AppVersion
  #define AppVersion "0.12.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\local\release\full"
#endif
#ifndef Edition
  #define Edition "completa"
#endif

[Setup]
; GUID fixo: é o que faz uma versão nova instalar POR CIMA da anterior (não mude)
AppId={{6F3C2B7A-5D1E-4C9B-9A57-2E8B4F1D7C36}
AppName=Legivo
AppVersion={#AppVersion}
AppVerName=Legivo {#AppVersion}
AppPublisher=Igor Teuri
AppPublisherURL=https://igorteuri.github.io/legivo/
AppSupportURL=https://github.com/igorteuri/legivo/issues
AppUpdatesURL=https://github.com/igorteuri/legivo/releases
DefaultDirName={localappdata}\Programs\Legivo
DefaultGroupName=Legivo
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\local\release
#if Edition == "lite"
OutputBaseFilename=Legivo-Setup-{#AppVersion}-lite
#else
OutputBaseFilename=Legivo-Setup-{#AppVersion}
#endif
SetupIconFile=..\src\legivo\assets\legivo.ico
UninstallDisplayIcon={app}\Legivo.exe
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=no
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "legivo_config.json,legivo_projetos"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Legivo"; Filename: "{app}\Legivo.exe"
Name: "{autodesktop}\Legivo"; Filename: "{app}\Legivo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Legivo.exe"; Description: "Abrir o Legivo agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; as configurações ficam ao lado do programa; as edições de cada PDF (legivo_projetos) são suas e ficam
Type: files; Name: "{app}\legivo_config.json"
