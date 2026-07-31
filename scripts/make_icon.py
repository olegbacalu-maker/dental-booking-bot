"""Генерирует icon.ico (зуб на бирюзовом фоне) для DentArt.exe."""
import sys

from PIL import Image, ImageDraw

TEAL = (7, 94, 84, 255)
WHITE = (250, 250, 250, 255)


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 256.0
    # фон: скруглённый квадрат
    r = int(52 * s)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=TEAL)
    # коронка зуба
    d.rounded_rectangle([int(64 * s), int(52 * s), int(192 * s), int(150 * s)],
                        radius=int(46 * s), fill=WHITE)
    # корни: две «ножки»
    d.rounded_rectangle([int(78 * s), int(110 * s), int(120 * s), int(204 * s)],
                        radius=int(20 * s), fill=WHITE)
    d.rounded_rectangle([int(136 * s), int(110 * s), int(178 * s), int(204 * s)],
                        radius=int(20 * s), fill=WHITE)
    # выемка между корнями
    d.ellipse([int(112 * s), int(150 * s), int(144 * s), int(214 * s)], fill=TEAL)
    return img


def main(out: str) -> None:
    base = draw_icon(256)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(out, format="ICO", sizes=sizes)
    print(f"icon written: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "icon.ico")
