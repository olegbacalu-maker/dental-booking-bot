"""Документы пациента (файлы на диске удаляет вызывающий маршрут)."""
from __future__ import annotations

from .conn import _execute, _fetch, _utcnow_iso
from .events import log_event


async def documents(pid: int) -> list:
    return await _fetch(
        """SELECT id, filename, size, mime, category, uploaded_at
           FROM documents WHERE patient_id = ? ORDER BY id DESC""", pid)


async def documents_with_paths(pid: int) -> list:
    """То же, что documents(), но с путём к файлу на диске.

    Отдельной функцией, а не полем в documents(): путь нужен ровно двум местам —
    выгрузке данных пациента и удалению — и не должен попадать на страницы,
    откуда его видно в исходном коде HTML.
    """
    return await _fetch(
        """SELECT id, filename, stored_path, size, mime, category, uploaded_at
           FROM documents WHERE patient_id = ? ORDER BY id""", pid)


async def add_document(pid: int, filename: str, stored_path: str,
                       size: int, mime: str, category: str = "alt") -> None:
    await _execute(
        """INSERT INTO documents(patient_id, filename, stored_path, size, mime,
                                 category, uploaded_at) VALUES(?, ?, ?, ?, ?, ?, ?)""",
        pid, filename, stored_path, size, mime, category, _utcnow_iso(),
    )
    await log_event(pid, "doc_add", f"Document încărcat: {filename}")


async def get_document(doc_id: int) -> dict | None:
    rows = await _fetch(
        """SELECT id, patient_id, filename, stored_path, size, mime
           FROM documents WHERE id = ?""", doc_id)
    return rows[0] if rows else None


async def delete_document(doc_id: int, pid: int) -> bool:
    """Строка документа (файл с диска снимает маршрут, `_drop_doc`). Летопись —
    ПОСЛЕ DELETE и только за реально снятую строку (как у `delete_bridge`).
    False — документа у пациента нет."""
    d = await get_document(doc_id)
    if not d or d["patient_id"] != pid:
        return False
    n = await _execute(
        "DELETE FROM documents WHERE id = ? AND patient_id = ?", doc_id, pid)
    if n != 1:
        return False
    await log_event(pid, "doc_del", f"Document șters: {d['filename']}")
    return True
