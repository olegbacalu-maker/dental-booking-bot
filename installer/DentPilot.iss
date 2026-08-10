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

; Один язык — румынский, как и сам продукт. Inno показывает окно выбора языка
; ТОЛЬКО когда языков больше одного, поэтому здесь оно исчезает само.
; Готового Romanian.isl в поставке Inno нет, поэтому берём английскую базу и
; переводим надписи, которые клиника реально видит.
[Languages]
Name: "ro"; MessagesFile: "compiler:Default.isl"

[Messages]
SetupAppTitle=Instalare
SetupWindowTitle=Instalare — %1
ExitSetupTitle=Ieșire din instalare
ExitSetupMessage=Instalarea nu este terminată. Dacă ieșiți acum, programul nu va fi instalat.%n%nSigur doriți să ieșiți?
ButtonBack=< Îna&poi
ButtonNext=&Înainte >
ButtonInstall=&Instalează
ButtonCancel=Anulează
ButtonFinish=&Gata
ButtonBrowse=&Răsfoiește...
ButtonWizardBrowse=Răs&foiește...
ButtonYes=&Da
ButtonNo=&Nu
ButtonOK=OK
ClickNext=Apăsați «Înainte» pentru a continua sau «Anulează» pentru a ieși.
WizardSelectDir=Alegeți folderul de instalare
SelectDirDesc=Unde să fie instalat DentPilot?
SelectDirLabel3=Programul va fi instalat în folderul de mai jos. Baza de date a clinicii se păstrează chiar lângă program, deci folderul trebuie să permită scrierea.
SelectDirBrowseLabel=Apăsați «Înainte» pentru a continua. Pentru alt folder apăsați «Răsfoiește».
DiskSpaceGBLabel=Este nevoie de cel puțin [gb] GB spațiu liber.
DiskSpaceMBLabel=Este nevoie de cel puțin [mb] MB spațiu liber.
WizardSelectTasks=Acțiuni suplimentare
SelectTasksDesc=Ce trebuie făcut în plus?
SelectTasksLabel2=Alegeți ce doriți, apoi apăsați «Înainte».
WizardReady=Totul este pregătit
ReadyLabel1=Instalarea poate începe.
ReadyLabel2a=Apăsați «Instalează» pentru a continua sau «Înapoi» pentru a schimba ceva.
ReadyLabel2b=Apăsați «Instalează» pentru a continua.
ReadyMemoDir=Folder:
ReadyMemoTasks=Acțiuni suplimentare:
WizardPreparing=Se pregătește
PreparingDesc=Se pregătește instalarea...
WizardInstalling=Se instalează
InstallingLabel=Vă rugăm să așteptați...
StatusExtractFiles=Se copiază fișierele...
StatusCreateIcons=Se creează scurtăturile...
StatusUninstalling=Se dezinstalează...
FinishedHeadingLabel=Instalare terminată
FinishedLabel=DentPilot a fost instalat. La prima pornire veți seta un PIN pentru registru.
FinishedLabelNoIcons=DentPilot a fost instalat.
ClickFinish=Apăsați «Gata» pentru a închide.
RunEntryExec=Pornește %1
ConfirmUninstall=Sigur doriți să ștergeți DentPilot?
UninstallStatusLabel=Vă rugăm să așteptați, se șterge programul...
UninstalledAll=DentPilot a fost șters.

[CustomMessages]
; CreateDesktopIcon/AdditionalIcons — встроенные сообщения Inno, живут именно
; здесь (в [Messages] компилятор их не признаёт)
ro.CreateDesktopIcon=Scurtătură pe desktop
ro.AdditionalIcons=Scurtături:
ro.AutostartTask=Pornește DentPilot la pornirea calculatorului
ro.DemoDataTask=Umple registrul cu programări demonstrative (DOAR pentru prezentare, nu pentru lucru)
ro.InstallingWebView2=Se instalează componenta Microsoft pentru afișare (WebView2)…
ro.NoWriteTitle=În acest folder nu se poate scrie
ro.NoWriteText=Nu am putut scrie un fișier în «%1».%n%nDentPilot ține baza de date a clinicii lângă program, deci folderul trebuie să permită scrierea. Se poate să fi fost creat de alt utilizator Windows.%n%nAlegeți alt folder (de exemplu cel propus implicit).
ro.DataKeptTitle=Datele clinicii au rămas
ro.DataKeptText=Programul a fost șters, dar datele clinicii NU au fost șterse:%n%n%1%n%nAcolo au rămas baza de date (data\dental.db), setările (clinic.json) și tokenul botului (dental.env). Ștergeți folderul manual dacă datele nu mai sunt necesare.
ro.PfWarnTitle=Acest folder nu este potrivit
ro.PfWarnText=Folderul «%1» este în Program Files.%n%nDentPilot ține baza de date a clinicii lângă program, iar în Program Files un utilizator obișnuit nu poate scrie — programul nu ar putea crea baza de date.%n%nAlegeți alt folder (de exemplu cel propus implicit).

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
; Runtime, на котором рисуется окно программы. Кладём ТОЛЬКО если его нет:
; на обновляемой Windows он есть всегда, и лишние 1.6 МБ возить незачем.
Source: "MicrosoftEdgeWebView2Setup.exe"; DestDir: "{tmp}"; \
    Flags: deleteafterinstall; Check: WebView2Missing

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}";  Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}";  Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: autostart

[Run]
; ⛔ ДО запуска программы: без WebView2 окно не открывается, и до этой правки
; клиника видела ровно ничего — сборка --noconsole, исключение уходило в пустоту.
; Программа с 1.19.12 умеет уйти в браузер, но это утешение, а не решение;
; решение — поставить Runtime здесь. Молча и без перезагрузки.
; ⚠️ Отказ НЕ валит установку (`runasoriginaluser` не ставим, код возврата не
; проверяем): нет интернета — программа всё равно поставится и откроется в
; браузере. Установщик, падающий из-за необязательного компонента, хуже.
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; \
    StatusMsg: "{cm:InstallingWebView2}"; Check: WebView2Missing; Flags: waituntilterminated
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

{ Есть ли на машине WebView2 Runtime — тот движок, на котором рисуется окно.

  Спрашиваем реестр, а не ищем файлы: Microsoft ставит Runtime в трёх видах
  (per-machine x64, per-machine x86, per-user), и общий у них ровно один —
  запись Клиента обновлений с этим GUID. Пустое `pv` или «0.0.0.0» означают
  «запись есть, Runtime снесён» — это НЕ установленный Runtime.

  ⚠️ Проверка нужна и на новых машинах тоже: на Windows 11 и обновляемой
  Windows 10 Runtime есть всегда, и тогда мы просто ничего не делаем — 1.6 МБ
  бутстрэппера в этом случае даже не распаковываются (Check стоит и в [Files]).

  Зачем вообще: без Runtime окно программы не открывалось, а сборка --noconsole
  не показывала ни ошибки, ни окна — клиника кликала по ярлыку и не видела
  НИЧЕГО. С 1.19.12 программа в этом случае уходит в браузер, но это утешение;
  правильное место починки — здесь, до первого запуска. }
function WebView2Missing: Boolean;
var
  Version: String;
  Client: String;
begin
  Client := 'Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := True;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\' + Client, 'pv', Version) then
    if (Version <> '') and (Version <> '0.0.0.0') then
      Result := False;
  if Result then
    if RegQueryStringValue(HKLM, 'SOFTWARE\' + Client, 'pv', Version) then
      if (Version <> '') and (Version <> '0.0.0.0') then
        Result := False;
  if Result then
    if RegQueryStringValue(HKCU, 'SOFTWARE\' + Client, 'pv', Version) then
      if (Version <> '') and (Version <> '0.0.0.0') then
        Result := False;
end;

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
