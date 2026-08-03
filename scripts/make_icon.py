"""Генерирует icon.ico для DentPilot.exe.

Сам знак не рисуется здесь: он описан в bot/app/brand.py и оттуда же попадает
в шапку программы. Иконка на рабочем столе и знак в интерфейсе — одна фигура.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from bot.app import brand  # noqa: E402


def main(out: str) -> None:
    base = brand.draw_pil(256)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(out, format="ICO", sizes=sizes)
    print(f"icon written: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon.ico")
