"""Задание оболочки без оболочки и окно UAC без окна — для стенда «мастер
обновления переживает закрытие оболочки» (18.10, 2.0.2).

Как это было у Олега (живой проход 2.0.0 → 2.0.1): оболочка держит движок в
«задании» Windows с KILL_ON_JOB_CLOSE; движок просит UAC, и служба UAC создаёт
повышенный процесс «от имени» движка — атрибутом PROC_THREAD_ATTRIBUTE_PARENT_PROCESS.
С таким атрибутом процесс наследует у названного родителя и задание (так
написано у UpdateProcThreadAttribute, и так показал опыт). По «started» оболочка
закрылась, Windows погасила задание — и операцию за UAC вместе с ним, во сне
перед запуском мастера.

Здесь то же без окна UAC: задание с пределами, прочитанными из `engine.rs`
(`JOB_LIMITS`), процесс «движка» в нём и процесс «за UAC», созданный тем же
атрибутом родителя. Повышения нет — для заданий оно ничего не меняет: задание
наследуется атрибутом, а не правами.

Подставной мастер — настоящий exe: пускач distlib (тот, что ставит pip для
`Scripts\\*.exe`) + строка `#!` интерпретатора + zip с `__main__.py`. Он
принимает ключи мастера (`/LOG=`, `/RESULT=`), пишет журнал и через полторы
секунды — «ok», как `WriteResult` мастера. Подписи у него нет: подпись и
версию отвечают швы (`suite_engine_layout`), а здесь проверяется только,
ПЕРЕЖИВЁТ ли он задание.
"""
from __future__ import annotations

import ctypes
import io
import pathlib
import re
import subprocess
import time
import zipfile
from ctypes import wintypes as W

# Имена пределов, которые может назвать `engine.rs::JOB_LIMITS` (WinNT.h).
# ⛔ Незнакомое имя — ошибка, а не ноль: иначе поломка строки читалась бы как
# «предела нет», и стенд зеленел бы или краснел не по той причине.
LIMITS = {"JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE": 0x2000,
          "JOB_OBJECT_LIMIT_BREAKAWAY_OK": 0x800,
          "JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK": 0x1000}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateJobObjectW.restype = W.HANDLE
_k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
_k32.OpenProcess.restype = W.HANDLE
_k32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
_k32.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
_k32.WaitForSingleObject.restype = W.DWORD
_k32.CloseHandle.argtypes = [W.HANDLE]
_k32.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
_k32.ResumeThread.argtypes = [W.HANDLE]
_k32.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
_k32.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
_k32.IsProcessInJob.argtypes = [W.HANDLE, W.HANDLE, ctypes.POINTER(W.BOOL)]
_k32.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
_k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, W.DWORD, W.DWORD,
                                                   ctypes.POINTER(ctypes.c_size_t)]
_k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, W.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                           ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
_k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]

_SYNCHRONIZE = 0x00100000
_TERMINATE = 0x0001
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_PARENT_PROCESS = 0x00020000          # PROC_THREAD_ATTRIBUTE_PARENT_PROCESS


class _Basic(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", W.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", W.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class _Io(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _Extended(ctypes.Structure):        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [("Basic", _Basic), ("Io", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR), ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR),
                ("dwX", W.DWORD), ("dwY", W.DWORD), ("dwXSize", W.DWORD), ("dwYSize", W.DWORD),
                ("dwXCountChars", W.DWORD), ("dwYCountChars", W.DWORD), ("dwFillAttribute", W.DWORD),
                ("dwFlags", W.DWORD), ("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
                ("lpReserved2", ctypes.c_void_p), ("hStdInput", W.HANDLE), ("hStdOutput", W.HANDLE),
                ("hStdError", W.HANDLE)]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcInfo(ctypes.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE), ("dwProcessId", W.DWORD),
                ("dwThreadId", W.DWORD)]


_k32.CreateProcessW.argtypes = [W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL, W.DWORD,
                                ctypes.c_void_p, W.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(_ProcInfo)]


def shell_limits(engine_rs: pathlib.Path) -> int:
    """Пределы задания оболочки — из строки `pub const JOB_LIMITS: u32 = …;`."""
    m = re.search(r"pub const JOB_LIMITS: u32 = ([^;]+);", engine_rs.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"в {engine_rs.name} нет строки `pub const JOB_LIMITS: u32 = …;`")
    flags = 0
    for name in (n.strip() for n in m.group(1).split("|")):
        if name not in LIMITS:
            raise ValueError(f"незнакомый предел задания: {name!r}")
        flags |= LIMITS[name]
    return flags


class Proc:
    """Процесс, созданный своими руками: ручка, pid, ожидание, снятие."""

    def __init__(self, pi: _ProcInfo):
        self.handle, self.pid, self._thread = pi.hProcess, pi.dwProcessId, pi.hThread

    def resume(self) -> None:
        _k32.ResumeThread(self._thread)

    def alive(self) -> bool:
        return _k32.WaitForSingleObject(self.handle, 0) == 0x102     # WAIT_TIMEOUT

    def wait(self, seconds: float) -> bool:
        """True — вышел за отведённое."""
        return _k32.WaitForSingleObject(self.handle, int(seconds * 1000)) == 0

    def exit_code(self) -> int | None:
        """Код выхода; None — ещё жив."""
        code = W.DWORD()
        if self.alive() or not _k32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            return None
        return code.value

    def kill(self) -> None:
        if self.alive():
            _k32.TerminateProcess(self.handle, 1)
            self.wait(3)

    def close(self) -> None:
        for h in (self._thread, self.handle):
            if h:
                _k32.CloseHandle(h)
        self._thread = self.handle = None


def start(cmd: list[str], *, parent: Proc | None = None, suspended: bool = False) -> Proc:
    """CreateProcessW без окна. `parent` — создать «от имени» другого процесса
    (PROC_THREAD_ATTRIBUTE_PARENT_PROCESS): так создаёт повышенный процесс
    служба UAC, и задание он наследует у названного родителя."""
    si = _StartupInfoEx()
    si.StartupInfo.cb = ctypes.sizeof(si)
    flags = _CREATE_NO_WINDOW | (_CREATE_SUSPENDED if suspended else 0)
    attrs = None
    hparent = W.HANDLE(parent.handle) if parent else None
    if parent is not None:
        size = ctypes.c_size_t()
        _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attrs = (ctypes.c_byte * size.value)()
        if not _k32.InitializeProcThreadAttributeList(attrs, 1, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not _k32.UpdateProcThreadAttribute(attrs, 0, _PARENT_PROCESS, ctypes.byref(hparent),
                                              ctypes.sizeof(hparent), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        si.lpAttributeList = ctypes.addressof(attrs)
        flags |= _EXTENDED_STARTUPINFO_PRESENT
    pi = _ProcInfo()
    line = ctypes.create_unicode_buffer(subprocess.list2cmdline(cmd))
    try:
        if not _k32.CreateProcessW(None, line, None, None, False, flags, None, None,
                                   ctypes.byref(si), ctypes.byref(pi)):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if attrs is not None:
            _k32.DeleteProcThreadAttributeList(attrs)
    return Proc(pi)


class Job:
    """«Задание» Windows с пределами `flags`; `close()` — как выход оболочки:
    последняя ручка закрыта, и с KILL_ON_JOB_CLOSE Windows гасит всех внутри."""

    def __init__(self, flags: int):
        self.handle = _k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _Extended()
        info.Basic.LimitFlags = flags
        if not _k32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def add(self, p: Proc) -> None:
        if not _k32.AssignProcessToJobObject(self.handle, p.handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def holds(self, p: Proc) -> bool:
        inside = W.BOOL()
        _k32.IsProcessInJob(p.handle, self.handle, ctypes.byref(inside))
        return bool(inside.value)

    def close(self) -> None:
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None


def wait_pid(pid: int, seconds: float) -> bool:
    """Дождаться выхода чужого процесса по pid. True — вышел (или его нет)."""
    h = _k32.OpenProcess(_SYNCHRONIZE, False, pid)
    if not h:
        return True
    try:
        return _k32.WaitForSingleObject(h, int(seconds * 1000)) == 0
    finally:
        _k32.CloseHandle(h)


def kill_pid(pid: int) -> None:
    h = _k32.OpenProcess(_TERMINATE | _SYNCHRONIZE, False, pid)
    if h:
        _k32.TerminateProcess(h, 1)
        _k32.WaitForSingleObject(h, 3000)
        _k32.CloseHandle(h)


# Подставной мастер: ключи как у Inno, итог как у `WriteResult` (CRLF), pid
# пускача в журнале — чтобы стенд дождался его выхода перед уборкой.
FAKE_SETUP = r'''
import os, pathlib, sys, time
keys = dict(a.split("=", 1) for a in sys.argv[1:] if a.startswith("/") and "=" in a)
log, result = pathlib.Path(keys["/LOG"]), pathlib.Path(keys["/RESULT"])
log.write_text("fake setup: launcher pid=%d args=%r\n" % (os.getppid(), sys.argv[1:]), encoding="utf-8")
time.sleep(1.5)
result.write_text("ok\r\n", encoding="utf-8")
'''


def fake_setup_exe(dst: pathlib.Path, python: str, pad: int = 5_200_000) -> pathlib.Path:
    """Собрать подставной мастер: пускач distlib + `#!python` + zip. `pad` —
    несжимаемый балласт внутри zip: операция за UAC не берёт файл меньше 5 МБ."""
    from pip._vendor import distlib      # пускач — тот же, что у Scripts\\*.exe venv
    launcher = (pathlib.Path(distlib.__file__).parent / "t64.exe").read_bytes()
    exe = f'"{python}"' if " " in python else python
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("__main__.py", FAKE_SETUP)
        z.writestr(zipfile.ZipInfo("ballast.bin"), bytes(range(256)) * (pad // 256),
                   compress_type=zipfile.ZIP_STORED)
    dst.write_bytes(launcher + b"#!" + exe.encode("utf-8") + b"\n" + buf.getvalue())
    return dst


# Процесс «за UAC»: настоящий `install-setup` из исходников (`argv[1]` — папка
# bot), с теми же швами подписи и версии, что у `suite_engine_layout`:
# учебный мастер не подписан.
UAC_CHILD = r'''
import pathlib, sys
bot, lab = sys.argv[1], pathlib.Path(sys.argv[2])
sys.path.insert(0, bot)
from app import authenticode, privileged
app_dir = lab / "Program Files" / "DentPilot"
privileged._self_exe = lambda: app_dir / "engine" / "DentPilot-Engine.exe"
privileged._current_version = lambda exe: (1, 0, 0, 0)
authenticode.signer_thumbprint = lambda p: next(iter(privileged.SIGNERS))
authenticode.file_version = lambda p: (99, 0, 0, 0)
print(privileged.run_op("install-setup", [], lambda: lab / "data", app_dir))
'''


def make_lab(lab: pathlib.Path, python: str) -> tuple[pathlib.Path, pathlib.Path]:
    """Лаборатория обновления: «установка» (оболочка + `engine\\`), папка данных
    с подставным мастером и описанием (размер, sha256) по условленным именам
    `privileged`, скрипт процесса «за UAC». → (папка `updates` данных, скрипт).
    ⚠️ Имена — строками, а не из `privileged`: стенд гоняет и ЧУЖОЙ `bot`
    (прежнюю версию), а имена эти не менялись с 03.10."""
    import hashlib
    import json

    app_dir = lab / "Program Files" / "DentPilot"
    (app_dir / "engine").mkdir(parents=True)
    (app_dir / "DentPilot.exe").write_bytes(b"OBOLOCHKA")
    (app_dir / "engine" / "DentPilot-Engine.exe").write_bytes(b"MOTOR")
    work = lab / "data" / "updates"
    work.mkdir(parents=True)
    body = fake_setup_exe(work / "DentPilot-Setup.new.exe", python).read_bytes()
    (work / "install.request").write_text(json.dumps(
        {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}), encoding="utf-8")
    child = lab / "uac_child.py"
    child.write_text(UAC_CHILD, encoding="utf-8")
    return work, child


class _Entry(ctypes.Structure):           # PROCESSENTRY32W
    _fields_ = [("dwSize", W.DWORD), ("cntUsage", W.DWORD), ("th32ProcessID", W.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", W.DWORD),
                ("cntThreads", W.DWORD), ("th32ParentProcessID", W.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", W.DWORD), ("szExeFile", W.WCHAR * 260)]


_k32.CreateToolhelp32Snapshot.restype = W.HANDLE
_k32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
_k32.Process32FirstW.argtypes = [W.HANDLE, ctypes.POINTER(_Entry)]
_k32.Process32NextW.argtypes = [W.HANDLE, ctypes.POINTER(_Entry)]


def children_of(pid: int) -> list[tuple[int, str]]:
    """Дети процесса: [(pid, имя файла)]."""
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
    out: list = []
    if snap in (None, W.HANDLE(-1).value):
        return out
    e = _Entry()
    e.dwSize = ctypes.sizeof(e)
    more = _k32.Process32FirstW(snap, ctypes.byref(e))
    while more:
        if e.th32ParentProcessID == pid and e.th32ProcessID != pid:
            out.append((e.th32ProcessID, e.szExeFile))
        more = _k32.Process32NextW(snap, ctypes.byref(e))
    _k32.CloseHandle(snap)
    return out


def open_pid(pid: int) -> Proc:
    """Ручка чужого процесса — годная в родители (`start(parent=…)`)."""
    access = 0x0080 | _SYNCHRONIZE | 0x1000 | _TERMINATE   # CREATE_PROCESS | … | QUERY_LIMITED
    h = _k32.OpenProcess(access, False, pid)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    pi = _ProcInfo()
    pi.hProcess, pi.dwProcessId = h, pid
    return Proc(pi)


def in_any_job(pid: int) -> bool:
    h = _k32.OpenProcess(0x1000, False, pid)
    if not h:
        return False
    inside = W.BOOL()
    try:
        _k32.IsProcessInJob(h, None, ctypes.byref(inside))
    finally:
        _k32.CloseHandle(h)
    return bool(inside.value)


def wait_text(path: pathlib.Path, want, seconds: float, step: float = 0.02) -> str:
    """Ждать, пока текст файла не станет годным (`want(text)`); вернуть последний."""
    end = time.monotonic() + seconds
    text = ""
    while True:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if want(text) or time.monotonic() >= end:
            return text
        time.sleep(step)


# ---- документ фиши: обработчик вне задания (18.10, 2.0.3) ----

# Подставной «Word»: `.vbs` открывается wscript.exe — классической программой,
# как Word или Acrobat (приложения Store запускает брокер, и болезнь на них не
# видна). Стучит файлом на каждом такте — счёт растёт, пока он жив; по `stop`
# выходит сам и пишет `done`. Потолок ~15 с: стенд, упавший до `stop`, не
# оставляет вечного процесса. ⛔ `On Error Resume Next` — не украшение:
# ошибка скрипта у wscript — окно на экране, и обработчик висел бы на нём, не
# стуча и не уходя (первый прогон стенда: `"\b"` без r — забой в имени).
DOC_VBS = r'''On Error Resume Next
Set fs = CreateObject("Scripting.FileSystemObject")
d = "{dir}"
For i = 1 To 150
  If fs.FileExists(d & "\stop") Then Exit For
  fs.CreateTextFile(d & "\b" & i, True).Close
  WScript.Sleep 100
Next
fs.CreateTextFile(d & "\done", True).Close
'''

# «Движок» стенда: открывает документ из исходников (`argv[1]` — папка bot)
# настоящим `core.shellopen.open_file` или прежним `os.startfile` и спит, как
# движок, пока задание его не погасит. Итог открытия — в файл `argv[4]`.
OPEN_ENGINE = r'''
import os, pathlib, sys, time
bot, how, doc, said = sys.argv[1:5]
sys.path.insert(0, bot)
try:
    if how == "startfile":
        opener = os.startfile               # прежний путь — контроль стенда
    else:
        from app.core import shellopen
        opener = shellopen.open_file
    opener(doc)
    pathlib.Path(said).write_text("opened", encoding="utf-8")
except OSError as e:
    pathlib.Path(said).write_text("ERR %r" % (e,), encoding="utf-8")
time.sleep(60)
'''


def doc_stand_missing() -> str:
    """Пусто — стенду документа есть на чём стоять; иначе причина пропуска.
    ⛔ Без рабочего стола explorer.exe, запущенный с файлом, сам становится
    оболочкой сеанса (раннер CI) — туда его не пускать."""
    if not ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None):
        return "нет рабочего стола Explorer (сеанс без панели задач)"
    buf = ctypes.create_unicode_buffer(520)
    n = W.DWORD(len(buf))
    hr = ctypes.windll.shlwapi.AssocQueryStringW(0, 2, ".vbs", None, buf, ctypes.byref(n))  # EXECUTABLE
    if hr != 0 or not buf.value.lower().endswith("wscript.exe"):
        return f".vbs открывает не wscript.exe ({buf.value or hex(hr & 0xFFFFFFFF)}) — VBScript выключен?"
    return ""


def beats(d: pathlib.Path) -> int:
    """Сколько раз подставной обработчик стукнул."""
    return sum(1 for p in d.iterdir() if p.name[:1] == "b" and p.name[1:].isdigit())
