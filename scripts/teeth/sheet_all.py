# -*- coding: utf-8 -*-
"""Обзор всех типов (07.10): студийные кадры трёх ракурсов, таблица 4×4.

Запуск:  python sheet_all.py [U2 U3 …]   (без аргументов — все 16)
"""
import sys

from PIL import Image, ImageDraw, ImageFont

import family as F
import gen_teeth as G
import studio as S

NAMES = {
    "U1": "Sus · incisiv central (11/21)", "U2": "Sus · incisiv lateral (12/22)", "U3": "Sus · canin (13/23)",
    "U4": "Sus · premolar 1 (14/24)", "U5": "Sus · premolar 2 (15/25)", "U6": "Sus · molar 1 (16/26)",
    "U7": "Sus · molar 2 (17/27)", "U8": "Sus · molar 3 (18/28)",
    "L1": "Jos · incisiv central (31/41)", "L2": "Jos · incisiv lateral (32/42)", "L3": "Jos · canin (33/43)",
    "L4": "Jos · premolar 1 (34/44)", "L5": "Jos · premolar 2 (35/45)", "L6": "Jos · molar 1 (36/46)",
    "L7": "Jos · molar 2 (37/47)", "L8": "Jos · molar 3 (38/48)",
}


def tile(name, size=230):
    tooth = G.TEETH[name]()
    H = tooth.ref["crown"]
    span = max(tooth.ref["md"], tooth.ref["bl"], H) * 1.45
    views = [
        S.shot(tooth, (0.38, -0.32, -0.87), size=size, span=span),
        S.shot(tooth, (0.05, -0.97, -0.24), up_hint=(0, 0, 1), size=size, span=span, center_y=H * 0.8),
        S.shot(tooth, (1.0, -0.15, 0.05), size=size, span=span),
    ]
    w = size * 3 + 8
    im = Image.new("RGB", (w, size + 36), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.text((8, 6), f"{name} · {NAMES.get(name, '')}", fill=(15, 23, 42),
           font=ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 18))
    for i, v in enumerate(views):
        im.paste(v, (i * (size + 4), 36))
    return im


def main():
    args = sys.argv[1:]
    if args[:1] == ["--tiles"]:                      # кадры по типам — для параллельных процессов
        for n in args[1:]:
            tile(n).save(G.HERE / f"tile_{n}.png")
            print("tile", n, flush=True)
        return
    if args[:1] == ["--sheet"]:                      # собрать из готовых кадров
        names = F.ALL
        from PIL import Image as _I
        tiles = [_I.open(G.HERE / f"tile_{n}.png") for n in names]
    else:
        names = args or F.ALL
        tiles = []
        for n in names:
            tiles.append(tile(n))
            print("tile", n, flush=True)
    cols = 2
    tw, th = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw + 12, rows * th + (rows - 1) * 8), (226, 232, 240))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * (tw + 12), (i // cols) * (th + 8)))
    out = G.HERE / ("sheet_all.png" if len(sys.argv) == 1 or args[:1] == ["--sheet"] else f"sheet_{'_'.join(names)}.png")
    sheet.save(out, optimize=True)
    print("sheet:", out)


if __name__ == "__main__":
    main()
