"""Генерирует icon.ico для DentPilot.exe.

Сам знак не рисуется здесь: он описан в bot/app/brand.py и оттуда же попадает
в шапку программы. Иконка на рабочем столе и знак в интерфейсе — одна фигура.

Каждый размер рисуется своим кадром, а не ужимается из 256: у мелких (16–32,
панель задач и заголовок окна) своя геометрия — зуб крупнее, линия толще
(brand.BOLD), иначе контур знака сливается в пятно.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from bot.app import brand  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)


def main(out: str) -> None:
    frames = [brand.draw_pil(s) for s in SIZES]
    frames[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print(f"icon written: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon.ico")
