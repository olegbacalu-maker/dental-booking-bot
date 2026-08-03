; DentPilot.iss — сборка DentPilot-Setup-<версия>.exe (Inno Setup 6).
; Один файл для клиники: мастер установки, выбор папки, ярлыки, автозапуск,
; запись в «Программы и компоненты» + деинсталлятор.
;
; ВАЖНО (архитектурное ограничение): DentPilot хранит рабочие данные РЯДОМ с exe
; (clinic.json, dental.env, data\dental.db). Поэтому установка только
; per-user (PrivilegesRequired=lowest) в папку, куда пользователь может писать.
; Program Files не подходит — там обычному пользователю запись запрещена,
; программа не создаст базу. На странице выбора папки стоит предупреждение.
;
; Сборка: .\Build-Installer.ps1  (или ISCC.exe /DAppVersion=1.10.0 installer\DentPilot.iss)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName    "DentPilot"
#define AppExeName "DentPilot.exe"
#define AppPublisher "DentPilot"
#define AppEmail   "dentpilotpro@gmail.com"

[Setup]
; AppId менять НЕЛЬЗЯ — по нему Windows опознаёт обновление поверх старой версии.
AppId={{B8836ACC-EA41-4B1C-9FEB-DC61ADD35754}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppSupportURL=mailto:{#AppEmail}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} — registrul clinicii (setup)

DefaultDirName={code:DefaultInstallDir}
UsePreviousAppDir=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no

PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\dist
OutputBaseFilename=DentPilot-Setup-{#AppVersion}
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}

Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; exe уже занят запущенной программой? Restart Manager попросит закрыть, а не упадёт.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
russian.AutostartTask=Запускать DentPilot при включении компьютера
russian.DemoDataTask=Заполнить журнал демонстрационными записями (для показа, не для работы)
russian.NoWriteTitle=В эту папку нельзя писать
russian.NoWriteText=В папку «%1» не удалось записать файл.%n%nDentPilot хранит базу клиники рядом с программой, поэтому папка должна быть доступна для записи. Возможно, она создана другим пользователем Windows.%n%nВыберите другую папку (например, предложенную по умолчанию).
russian.DataKeptTitle=Данные клиники сохранены
russian.DataKeptText=Программа удалена, но данные клиники НЕ удалены:%n%n%1%n%nТам остались база (data\dental.db), настройки (clinic.json) и токен бота (dental.env). Удалите папку вручную, если данные больше не нужны.
russian.PfWarnTitle=Эта папка не подойдёт
russian.PfWarnText=Папка «%1» находится внутри Program Files.%n%nDentPilot хранит базу клиники рядом с программой, а в Program Files обычному пользователю запись запрещена — программа не сможет создать базу.%n%nВыберите другую папку (например, предложенную по умолчанию).
english.AutostartTask=Start DentPilot when the computer turns on
english.DemoDataTask=Fill the journal with demo appointments (for a demo, not for real work)
english.NoWriteTitle=This folder is not writable
english.NoWriteText=Could not write a file into "%1".%n%nDentPilot keeps the clinic database next to the program, so the folder must be writable. It may have been created by another Windows user.%n%nPlease choose another folder (for example, the suggested default).
english.DataKeptTitle=Clinic data kept
english.DataKeptText=The program was removed, but the clinic data was NOT deleted:%n%n%1%n%nThe database (data\dental.db), settings (clinic.json) and bot token (dental.env) are still there. Delete the folder manually if you no longer need the data.
english.PfWarnTitle=This folder will not work
english.PfWarnText=The folder "%1" is inside Program Files.%n%nDentPilot keeps the clinic database next to the program, and Program Files is not writable for a regular user — the program would fail to create its database.%n%nPlease choose another folder (for example, the suggested default).

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart";   Description: "{cm:AutostartTask}"
; По умолчанию СНЯТА: установщик получает реальная клиника, и демо-пациенты
; в её журнале — это чужие фамилии, которые придётся удалять по одной.
Name: "demodata";    Description: "{cm:DemoDataTask}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Метка для программы: заполнять ли журнал демо-записями при первом запуске.
; Файла нет = чистый старт у реальной клиники.
Source: "demo.flag"; DestDir: "{app}"; Tasks: demodata; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}";  Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent

; Данные клиники деинсталлятор НЕ трогает: clinic.json, dental.env и data\
; (база + бэкапы) остаются. А вот обломки самообновления — это файлы программы,
; и по 30 МБ каждый; их убираем поимённо, чтобы случайно не задеть данные.
[UninstallDelete]
Type: files; Name: "{app}\*.new.exe"
Type: files; Name: "{app}\*.old.exe"
Type: files; Name: "{app}\DentPilot.exe.bak"
Type: files; Name: "{app}\dentpilot_update.bat"
Type: files; Name: "{app}\dentpilot_restart.bat"
Type: files; Name: "{app}\demo.flag"

[Code]

{ Папка по умолчанию.

  ⚠️ Главное соображение: база лежит РЯДОМ с exe, значит папка обязана быть
  общей для всех учётных записей Windows на этом компьютере. В клинике две
  смены — это две учётки; при установке в профиль пользователя вторая смена
  не увидит ни ярлыка, ни программы, поставит её заново и получит ПУСТУЮ базу.
  Обнаружилось бы это фразой «а куда делись сегодняшние записи».

  C:\Users\Public подходит: там на «ИНТЕРАКТИВНЫЕ» (любой вошедший за этот
  компьютер) наследуется Modify — писать может каждый, права администратора не
  нужны. Профиль пользователя оставлен запасным вариантом на случай, если
  Public почему-то недоступен.

  Порядок: старая установка (чтобы не потерять базу) → общая папка → профиль. }
function DefaultInstallDir(Param: String): String;
begin
  if FileExists('C:\DentPilot\DentPilot.exe') then
    Result := 'C:\DentPilot'
  else if DirExists(ExpandConstant('{commondocs}\..')) then
    Result := ExpandConstant('{commondocs}\..\DentPilot')
  else
    Result := ExpandConstant('{localappdata}\Programs\DentPilot');
end;

function StartsWithDir(Path, Base: String): Boolean;
begin
  Result := (Base <> '') and (Pos(Lowercase(AddBackslash(Base)),
                                 Lowercase(AddBackslash(Path))) = 1);
end;

function IsUnderProgramFiles(Path: String): Boolean;
begin
  Result := StartsWithDir(Path, ExpandConstant('{commonpf}')) or
            StartsWithDir(Path, ExpandConstant('{commonpf32}')) or
            StartsWithDir(Path, ExpandConstant('{commonpf64}'));
end;

{ Проба записи сильнее правила про путь: Program Files — лишь один из
  неподходящих вариантов. Папка, созданная ДРУГИМ пользователем (например
  C:\DentPilot от установки под админом), проходит проверку по имени, но
  программа упадёт уже при создании базы — когда объяснять будет некому. }
function CanWriteTo(Dir: String): Boolean;
var
  Probe: String;
begin
  Probe := AddBackslash(Dir) + 'dp_write_test.tmp';
  Result := ForceDirectories(Dir) and SaveStringToFile(Probe, 'x', False);
  if Result then
    DeleteFile(Probe);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    if IsUnderProgramFiles(WizardDirValue) then
    begin
      MsgBox(FmtMessage(CustomMessage('PfWarnText'), [WizardDirValue]),
             mbError, MB_OK);
      Result := False;
      Exit;
    end;
    if not CanWriteTo(WizardDirValue) then
    begin
      MsgBox(FmtMessage(CustomMessage('NoWriteText'), [WizardDirValue]),
             mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dir := ExpandConstant('{app}');
    if DirExists(Dir) and (FileExists(Dir + '\clinic.json') or
                           DirExists(Dir + '\data')) then
      MsgBox(FmtMessage(CustomMessage('DataKeptText'), [Dir]), mbInformation, MB_OK);
  end;
end;
