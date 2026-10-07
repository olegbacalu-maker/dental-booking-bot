# -*- coding: utf-8 -*-
"""Студийный кадр своей модели зуба (06.10): цвет эмали по высоте, затенение
впадин (AO по расстоянию со знаком), блик — тем же лучевым маршем в numpy.

Запуск:  python studio.py U1 U6   → studio_U1.png, studio_U6.png (три ракурса)
"""
import sys

import numpy as np
from PIL import Image

import gen_teeth as G


def norm(v):
    return v / np.linalg.norm(v)


def shot(tooth, eye_dir, up_hint=(0, 1, 0), size=520, span=13.5, center_y=None):
    cy = tooth.ref["crown"] * 0.5 if center_y is None else center_y
    d = norm(np.asarray(eye_dir, float))
    right = norm(np.cross(d, up_hint))
    up = np.cross(right, d)
    half = span / 2
    u = np.linspace(-half, half, size)
    U, V = np.meshgrid(u, u[::-1])
    o = (U[..., None] * right + V[..., None] * up + np.array([0, cy, 0]) - d * 20).reshape(-1, 3)
    t = np.zeros(len(o))
    hit = np.zeros(len(o), bool)
    alive = np.ones(len(o), bool)
    for _ in range(700):
        idx = np.nonzero(alive)[0]
        if not len(idx):
            break
        p = o[idx] + t[idx, None] * d
        dist = tooth.sdf(p)
        step = tooth.step(p, dist) if hasattr(tooth, "step") else dist
        t[idx] += np.maximum(step * 0.75, 0.003)
        done = dist < 0.004
        hit[idx[done]] = True
        alive[idx[done | (t[idx] > 42)]] = False
    # фон — мягкий градиент
    bg_top = np.array([246, 247, 249.0])
    bg_bot = np.array([228, 232, 238.0])
    k = np.repeat(np.linspace(0, 1, size)[:, None], size, 1).reshape(-1, 1)
    img = bg_top * (1 - k) + bg_bot * k
    hi = np.nonzero(hit)[0]
    if len(hi):
        p = o[hi] + t[hi, None] * d
        e = 0.06
        n = np.stack([
            tooth.sdf(p + [e, 0, 0]) - tooth.sdf(p - [e, 0, 0]),
            tooth.sdf(p + [0, e, 0]) - tooth.sdf(p - [0, e, 0]),
            tooth.sdf(p + [0, 0, e]) - tooth.sdf(p - [0, 0, e])], -1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        # затенение впадин: насколько поверхность «закрыта» вдоль нормали
        ao = np.ones(len(p))
        for s, w in ((0.25, 1.6), (0.6, 0.8), (1.2, 0.35)):
            ao -= w * np.clip(s - tooth.sdf(p + n * s), 0, None)
        ao = np.clip(ao, 0.35, 1.0)
        # эмаль: у шейки теплее, к краю светлее; у резца край сероватый
        H = tooth.ref["crown"]
        tt = np.clip(p[:, 1] / H, 0, 1)[:, None]
        cerv = np.array([0.84, 0.74, 0.58])
        mid = np.array([0.95, 0.92, 0.86])
        edge = np.array([0.86, 0.89, 0.93])
        col = cerv * (1 - np.clip(tt / 0.42, 0, 1)) + mid * np.clip(tt / 0.42, 0, 1)
        if getattr(tooth, "front_tooth", False):
            ke = np.clip((tt - 0.72) / 0.28, 0, 1)
            col = col * (1 - 0.8 * ke) + edge * 0.8 * ke
        key = norm(np.array([-0.5, 0.75, 0.45]))
        fill = norm(np.array([0.7, 0.2, 0.5]))
        lam = 0.62 * np.clip(n @ key, 0, 1) + 0.25 * np.clip(n @ fill, 0, 1) + 0.28
        h = norm(key - d)
        spec = 0.42 * np.clip(n @ h, 0, 1) ** 70 + 0.12 * np.clip(n @ h, 0, 1) ** 12
        rim = 0.18 * (1 - np.clip(-(n @ d), 0, 1)) ** 3
        rgb = col * (lam * ao)[:, None] + (spec + rim)[:, None]
        img[hi] = np.clip(rgb, 0, 1) * 255
    return Image.fromarray(img.reshape(size, size, 3).astype(np.uint8))


def studio(name):
    tooth = G.TEETH[name]()
    views = [
        shot(tooth, (0.38, -0.32, -0.87)),          # губно-щёчная сторона, чуть сбоку и сверху
        shot(tooth, (0.05, -0.97, -0.24), up_hint=(0, 0, 1), center_y=tooth.ref["crown"] * 0.8),  # окклюзионная
        shot(tooth, (1.0, -0.15, 0.05)),            # мезиально
    ]
    sheet = Image.new("RGB", (sum(v.width for v in views) + 16 * 2, views[0].height), (255, 255, 255))
    x = 0
    for v in views:
        sheet.paste(v, (x, 0))
        x += v.width + 16
    out = G.HERE / f"studio_{name}.png"
    sheet.save(out)
    print("studio:", out)


if __name__ == "__main__":
    import family  # noqa: F401 — регистрирует типы
    for nm in sys.argv[1:] or list(G.TEETH):
        studio(nm)
