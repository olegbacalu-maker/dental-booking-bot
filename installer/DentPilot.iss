; DentPilot.iss — сборка DentPilot-Setup-<версия>.exe (Inno Setup 6).
; Один файл для клиники: мастер установки, выбор папки, ярлыки, автозапуск,
; запись в «Программы и компоненты» + деинсталлятор.
;
; РАСКЛАДКА (P3-min, 20.09): программа и данные РАЗВЕДЕНЫ.
;   {commonpf}\DentPilot       — программа, только чтение в работе
;   {commonappdata}\DentPilot  — данные клиники, общие для всех учёток машины
; Поэтому установка per-machine (PrivilegesRequired=admin). Прежнее «данные
; рядом с exe» отменено: разбор — docs/dentpilot-2/storage.md.
; ⛔ Папке программы права на запись НЕ выдаются: с приходом привилегированного
; обновлятора (P4) это означало бы, что любой пользователь машины подменяет
; бинарник, который исполняется от LocalSystem.
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

DefaultDirName={commonpf}\{#AppName}
UsePreviousAppDir=yes
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no

PrivilegesRequired=admin
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
ro.DemoDataTask=Umple registrul cu programări demonstrative (DOAR pentru prezentare, nu pentru lucru)
ro.InstallingWebView2=Se instalează componenta Microsoft pentru afișare (WebView2)…
ro.NoWriteTitle=Nu se poate pregăti dosarul cu date
ro.NoWriteText=Nu am putut scrie în «%1».%n%nAcolo DentPilot ține baza de date a clinicii. Instalarea nu poate continua.
ro.DataKeptTitle=Datele clinicii au rămas
ro.DataKeptText=Programul a fost șters, dar datele clinicii NU au fost șterse:%n%n%1%n%nAcolo au rămas baza de date (data\dental.db), setările (clinic.json) și tokenul botului (dental.env). Ștergeți folderul manual dacă datele nu mai sunt necesare.
ro.LegacyTitle=Există deja o instalare mai veche
ro.LegacyText=Pe acest calculator există o instalare mai veche a DentPilot, cu datele clinicii lângă program:%n%n%1%n%nMutarea datelor în noua așezare nu este încă disponibilă în această versiune. Instalarea a fost oprită ca să nu rămână două evidențe separate.
ro.AclTitle=Drepturile pe dosarul cu date
ro.AclText=Nu am putut acorda drepturi de scriere pe «%1».%n%nFără ele, a doua tură nu va putea lucra. Instalarea a fost oprită.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; По умолчанию СНЯТА: установщик получает реальная клиника, и демо-пациенты
; в её журнале — это чужие фамилии, которые придётся удалять по одной.
Name: "demodata";    Description: "{cm:DemoDataTask}"; Flags: unchecked

[Dirs]
; Данные клиники. ⛔ Право на запись нужно на КАТАЛОГ, а не только на файлы:
; SQLite в режиме WAL создаёт рядом с базой -wal и -shm.
; ⛔ У {app} параметра Permissions НЕТ ни на одной строке и быть не должно —
; см. шапку файла.
Name: "{commonappdata}\{#AppName}";               Permissions: users-modify
Name: "{commonappdata}\{#AppName}\data";          Permissions: users-modify
Name: "{commonappdata}\{#AppName}\data\backups";  Permissions: users-modify
Name: "{commonappdata}\{#AppName}\data\files";    Permissions: users-modify

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

[Run]
; ⛔ ДО запуска программы: без WebView2 окно не открывается, и до этой правки
; клиника видела ровно ничего — сборка --noconsole, исключение уходило в пустоту.
; Программа с 1.19.12 умеет уйти в браузер, но это утешение, а не решение;
; решение — поставить Runtime здесь. Молча и без перезагрузки.
; ⚠️ Отказ НЕ валит установку (`runasoriginaluser` не ставим, код возврата не
; проверяем): нет интернета — программа всё равно поставится и откроется в
; браузере. Установщик, падающий из-за необязательного компонента, хуже.
; Сначала автономный установщик с флешки, если он там лежит (OfflineWv2Ready) —
; он работает без интернета. Разбор и почему условие бутстрэппера ниже НЕ
; тронуто — в комментарии к OfflineWv2Ready.
Filename: "{src}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/silent /install"; \
    StatusMsg: "{cm:InstallingWebView2}"; Check: OfflineWv2Ready; Flags: waituntilterminated
Filename: "{tmp}\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; \
    StatusMsg: "{cm:InstallingWebView2}"; Check: WebView2Missing; Flags: waituntilterminated
; ⛔ runasoriginaluser обязателен. Без него [Run] наследует ПОВЫШЕННЫЙ токен,
; и первый запуск идёт от администратора: файлы в папке данных создаются не той
; учёткой, а на клинике с шифрованием db.key заворачивается под DPAPI админа —
; и собственная учётка клиники встречает экран восстановления.
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runasoriginaluser

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
; install.json пишем мы — значит и убираем мы
Type: files; Name: "{app}\install.json"

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

{ Автономный установщик Runtime, положенный РЯДОМ с мастером — выездной кит на
  флешке (`usb\`, 200 МБ). Нужен ровно для одного случая: на машине нет WebView2
  И нет интернета. Вшитый в мастер бутстрэппер там бессилен — он не несёт
  Runtime, а скачивает его.

  ⚠️ Константа src — папка, из которой ЗАПУЩЕН мастер. Скопировали на рабочий
  стол один мастер, а флешку вынули — файла рядом нет, и всё честно откатывается
  на бутстрэппер. Это не ошибка, а нормальный путь для клиники с интернетом.

  ⛔ Фигурных скобок в этом комментарии быть НЕ МОЖЕТ: в Pascal Script скобка
  открывает и закрывает комментарий, поэтому написанное здесь как константа в
  скобках обрывает комментарий на середине, и остаток текста уезжает в код —
  ISCC падает «Syntax error» на строке, где ничего не написано. Наступил при
  первой версии этой функции.

  ⭐ В git этот файл не попадает и попасть не может: GitHub отклоняет push с
  файлом больше 100 МБ. Он живёт только в `usb\` и в релиз не уезжает — иначе
  каждый пре-релиз возил бы 200 МБ ради случая, который бывает раз в жизни на
  одну машину. Обновление у клиники качает DentPilot.exe, а не мастер.

  ⚠️ Порядок в [Run] важен, и подстраховка получается сама: этот шаг идёт
  ПЕРВЫМ, после него реестр уже содержит Runtime, и `Check: WebView2Missing` у
  бутстрэппера возвращает False — он не запускается. А если автономный
  установщик СЛОМАЛСЯ, реестр остался пустым, и бутстрэппер отработает вторым
  как запасной путь. Поэтому у него условие не тронуто. }
function OfflineWv2Ready: Boolean;
begin
  Result := WebView2Missing and FileExists(
    ExpandConstant('{src}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'));
end;

// ⛔ Здесь была DefaultInstallDir: она предлагала C:\DentPilot или
// C:\Users\Public\DentPilot, потому что база лежала рядом с exe. С P3-min
// папка программы — константа commonpf\DentPilot, и функция удалена целиком,
// а не оставлена «на всякий случай»: её ветка localappdata — пользовательская
// область, а в режиме административной установки Inno помечает такие области
// предупреждением на каждой сборке.
// ⚠️ Комментарии здесь намеренно на //, а не на фигурных скобках: внутри
// текста стоят константы Inno, и первая же закрывающая скобка закрыла бы
// комментарий, превратив остаток пояснения в код. Наступлено 20.09.

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

// Проба записи — теперь про папку ДАННЫХ, а не про папку программы.
//
// ⛔ Прежняя проба стояла на папке программы и с приходом admin потеряла смысл
// дважды: та папка ТЕПЕРЬ и должна быть недоступной на запись, а сама проба
// идёт с повышенным токеном и в Program Files всегда проходит — то есть могла
// бы дать только ложное зелёное.
// ⚠️ Честная оговорка: никакая проба со стороны установщика не доказывает, что
// писать сможет НЕпривилегированный пользователь. Это доказывает только вход
// второй учёткой (приёмка P5).
function CanWriteTo(Dir: String): Boolean;
var
  Probe: String;
begin
  Probe := AddBackslash(Dir) + 'dp_write_test.tmp';
  Result := ForceDirectories(Dir) and SaveStringToFile(Probe, 'x', False);
  if Result then
    DeleteFile(Probe);
end;

function DataRoot(): String;
begin
  Result := ExpandConstant('{commonappdata}\{#AppName}');
end;

{ Есть ли на машине СТАРАЯ установка — та, где данные лежат рядом с exe.

  ⭐ ВАЖНО про правило доверия. В storage.md записано: кандидата на ПЕРЕЕЗД
  называет только источник происхождения, содержимое лишь подтверждает. Здесь
  задача ДРУГАЯ и риск обратный: мы не выбираем, что переносить, — мы решаем,
  можно ли ставиться. Ошибка «померещилось» стоит отказа в установке, ошибка
  «не заметил» стоит клинике двух разных картотек. Поэтому здесь проверка
  НАРОЧНО шире: и ярлыки, и два прежних расположения по умолчанию.
  ⚠️ Ярлыки видны только у той учётки, что запустила установку: при вводе
  админского пароля «через плечо» это админ, а не регистратура. Дыру закрывают
  два прежних пути; авторитетная детекция для переезда живёт в app/legacy.py и
  работает уже от имени клиники. }
function LegacyDir(): String;
var
  Sh, Lnk: Variant;
  I: Integer;
  Cand: array[0..4] of String;
  T, Dir: String;
begin
  Result := '';
  Cand[0] := ExpandConstant('{userdesktop}\{#AppName}.lnk');
  Cand[1] := ExpandConstant('{userprograms}\{#AppName}.lnk');
  Cand[2] := ExpandConstant('{userstartup}\{#AppName}.lnk');
  Cand[3] := 'C:\DentPilot';
  Cand[4] := ExpandConstant('{commondocs}\..\{#AppName}');
  for I := 0 to 4 do
  begin
    Dir := '';
    if I <= 2 then
    begin
      if not FileExists(Cand[I]) then Continue;
      try
        Sh := CreateOleObject('WScript.Shell');
        Lnk := Sh.CreateShortcut(Cand[I]);
        T := Lnk.TargetPath;
      except
        T := '';
      end;
      if (T <> '') and (CompareText(ExtractFileName(T), '{#AppExeName}') = 0) then
        Dir := ExtractFileDir(T);
    end
    else
      Dir := Cand[I];
    if Dir = '' then Continue;
    { подтверждение содержимым — здесь оно уместно: путь уже назван }
    if DirExists(Dir) and (FileExists(AddBackslash(Dir) + 'clinic.json') or
                           DirExists(AddBackslash(Dir) + 'data')) and
       not IsUnderProgramFiles(Dir) then
    begin
      Result := RemoveBackslash(Dir);
      Exit;
    end;
  end;
end;

function NoLegacyFound(): Boolean;
begin
  Result := LegacyDir() = '';
end;

// ⛔ Блокировка, а не предупреждение. Пока переезд данных (P2) не написан,
// установка поверх старой раскладки оставила бы клинику с двумя картотеками:
// новая программа завела бы пустую базу в папке данных, а настоящая осталась
// бы рядом со старым exe — и обе выглядели бы исправно работающими.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Legacy: String;
begin
  Result := '';
  Legacy := LegacyDir();
  if Legacy <> '' then
  begin
    Result := FmtMessage(CustomMessage('LegacyText'), [Legacy]);
    Exit;
  end;
  if not CanWriteTo(DataRoot()) then
    Result := FmtMessage(CustomMessage('NoWriteText'), [DataRoot()]);
end;

{ Права на папку данных и запись намерения установщика.

  ⛔ Права выдаём ПО SID: на румынской Windows группа зовётся «Utilizatori», и
  /grant Users: не найдёт там ничего.
  ⛔ Без /C и /Q: /C велит icacls продолжать после ошибок, то есть ровно то, от
  чего код возврата перестаёт что-либо значить. }
procedure WriteInstallJson(AclOk: Boolean);
var
  S: TArrayOfString;
  Root, Data, Ok, Chan: String;
begin
  Root := ExpandConstant('{app}');
  Data := DataRoot();
  StringChangeEx(Root, '\', '\\', True);
  StringChangeEx(Data, '\', '\\', True);
  if AclOk then Ok := 'true' else Ok := 'false';
  { канал — НАМЕРЕНИЕ: лаунчер возьмёт его при первом создании dental.env }
  Chan := ExpandConstant('{param:CHANNEL|stable}');
  SetArrayLength(S, 8);
  S[0] := '{';
  S[1] := '  "schema": 1,';
  S[2] := '  "mode": "standalone",';
  S[3] := '  "channel": "' + Chan + '",';
  S[4] := '  "install_root": "' + Root + '",';
  S[5] := '  "data_root": "' + Data + '",';
  S[6] := '  "acl_ok": ' + Ok;
  S[7] := '}';
  SaveStringsToUTF8File(ExpandConstant('{app}\install.json'), S, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  RC: Integer;
  AclOk: Boolean;
begin
  if CurStep <> ssPostInstall then
    Exit;
  AclOk := Exec(ExpandConstant('{sys}\icacls.exe'),
                '"' + DataRoot() + '" /grant *S-1-5-32-545:(OI)(CI)M /T',
                '', SW_HIDE, ewWaitUntilTerminated, RC) and (RC = 0);
  WriteInstallJson(AclOk);
  if not AclOk then
    MsgBox(FmtMessage(CustomMessage('AclText'), [DataRoot()]), mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dir := DataRoot();
    if DirExists(Dir) and (FileExists(Dir + '\clinic.json') or
                           DirExists(Dir + '\data')) then
      MsgBox(FmtMessage(CustomMessage('DataKeptText'), [Dir]), mbInformation, MB_OK);
  end;
end;
