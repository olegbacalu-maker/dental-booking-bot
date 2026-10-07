# -*- coding: utf-8 -*-
"""Семейства своих моделей (07.10, вторая версия): резец, клык, премоляр, моляр.
Тип зуба = семейство + параметры (размеры по Wheeler, высоты бугров, где
контакты, какие борозды). Регистрирует все 16 типов в `gen_teeth.TEETH`.

Что изменилось против первой версии (кадры `compare/6_chernovik_16_tipov.png`):
- тело — лофт, а не пересечение трёх коробок: у премоляров и шеек ушли рёбра;
- бугры анизотропные: скаты бугра пологие, треугольные валики к центру круче —
  у премоляра появилась центральная фиссура, у моляров — настоящие ямки;
  «рога» по углам премоляра (концы краевых валиков выше скатов) ушли сами;
- ямки клыка, ямка и бугорок резца — смещения поверхности, а не тела: в первой
  версии эллипсоиды протыкали язычную стенку (два кармана у 13) и торчали
  диском из-под режущего края (31, 41);
- нижние премоляры и моляры наклонены к языку (`tilt`), как в челюсти.

Оси: +x дистально, −x мезиально, +z щёчно/губно, −z язычно/нёбно, +y окклюзионно,
шейка — y = 0. Миллиметры эталона.
"""
import numpy as np

import gen_teeth as G
from gen_teeth import Cusp, Loft, Ridge, Silhouette, Tooth, band, gauss, relief, smax, smoothstep


def _tilted(pts, tilt, H):
    """Силуэт сбоку (z, y), наклонённый к языку: верх сдвинут на −tilt."""
    return [(z - tilt * float(smoothstep(0.0, H, max(y, 0.0))), y) for z, y in pts]


# ---------------------------------------------------------------- резцы

class Incisor(Tooth):
    """Резец: губная выпуклость у шейки, тонкий режущий край; сечение у шейки —
    треугольник (язычная сторона сходится к бугорку), к краю — линза; язычная
    ямка между краевыми валиками; губные доли и едва заметные маммелоны."""
    front_tooth = True

    def __init__(self, md, bl, crown, cmd, cbl, *, contact_m=0.82, contact_d=0.70, corner_m=0.55,
                 corner_d=1.3, edge_drop=0.18, lab=None, cing=None, edge_t=0.95, lobes=0.09,
                 fossa=0.35, edge_z=0.15, cing_x=0.0):
        H = crown
        m, cm, cb = md / 2, cmd / 2, cbl / 2
        lab = lab if lab is not None else bl / 2
        cg = cing if cing is not None else bl / 2
        self.ref = {"md": md, "bl": bl, "crown": crown}
        self.h_cap = H - 1.0
        self.m, self.H, self.z0 = m, H, edge_z
        self.lobes, self.fossa = lobes, fossa
        e, z0 = edge_t, edge_z
        self.front = Silhouette([
            (-cm, -3.0), (-cm, 0.0), (-(cm + 0.6 * (m - cm)), 0.25 * H), (-(cm + 0.92 * (m - cm)), 0.5 * H),
            (-m, contact_m * H), (-(m - 0.08), H - corner_m * 1.05), (-(m - corner_m * 0.5), H - 0.04),
            (-0.45 * m, H + 0.05), (0.0, H + 0.03), (0.45 * m, H - edge_drop * 0.5),
            (m - corner_d * 0.6, H - edge_drop - 0.08), (m - 0.08, H - edge_drop - corner_d * 0.9),
            (m, contact_d * H), (cm + 0.92 * (m - cm), 0.5 * H), (cm + 0.6 * (m - cm), 0.25 * H),
            (cm, 0.0), (cm, -3.0)])
        self.side = Silhouette([
            (cb, -3.0), (cb, 0.0), (lab, 0.16 * H), (lab * 0.97, 0.26 * H), (lab * 0.85, 0.45 * H),
            (lab * 0.62, 0.65 * H), (z0 + e * 0.45 + 0.175 * (lab - z0), 0.84 * H), (z0 + e * 0.5, 0.95 * H),
            (z0 + e * 0.36, H - 0.12), (z0 + e * 0.08, H + 0.07), (z0 - e * 0.22, H - 0.12),
            (z0 - e * 0.38, 0.95 * H), (z0 - e * 0.55 - 0.35, 0.84 * H),
            (-(cg * 0.6), 0.62 * H), (-(cg * 0.88), 0.42 * H), (-cg, 0.25 * H), (-cg * 0.93, 0.1 * H),
            (-cb, 0.0), (-cb, -3.0)])
        cx = cing_x * m
        tri = Silhouette([
            (-m, 0.1 * lab), (-0.85 * m, 0.55 * lab), (-0.45 * m, 0.9 * lab), (0.0, lab), (0.45 * m, 0.9 * lab),
            (0.85 * m, 0.5 * lab), (m, 0.05 * lab), (0.8 * m, -0.35 * cg), (0.45 * m + cx, -0.72 * cg),
            (0.18 * m + cx, -0.95 * cg), (cx, -cg), (-0.2 * m + cx, -0.95 * cg), (-0.5 * m + cx, -0.72 * cg),
            (-0.82 * m, -0.35 * cg)])
        hb = bl / 2
        lens = Silhouette([
            (-m, 0.0), (-0.86 * m, 0.48 * hb), (-0.45 * m, 0.86 * hb), (0.0, hb), (0.45 * m, 0.86 * hb),
            (0.86 * m, 0.48 * hb), (m, 0.0), (0.86 * m, -0.36 * hb), (0.45 * m, -0.55 * hb), (0.0, -0.58 * hb),
            (-0.45 * m, -0.55 * hb), (-0.86 * m, -0.36 * hb)])
        # треугольник держится до средней трети (краевые валики сходятся к бугорку —
        # сверху контур клином), к режущей трети — линза
        self.loft = Loft(self.front, self.side, [(0.5 * H, tri), (0.85 * H, lens)])

    def sdf(self, p):
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        m, H, z0 = self.m, self.H, self.z0
        d = self.body(p)
        if self.fossa > 0:
            ling = smoothstep(z0 + 0.2, z0 - 0.6, z)
            d = d + self.fossa * np.exp(-(x / (0.5 * m)) ** 4) * band(y, 0.3 * H, 0.5 * H, 0.74 * H, 0.9 * H) * ling
        gx = 0.31 * m
        labm = smoothstep(z0, z0 + 1.0, z) * band(y, 0.42 * H, 0.75 * H, 0.95 * H, H + 0.1)
        d = d + self.lobes * labm * (gauss(x + gx, 0.13 * m) + gauss(x - gx, 0.13 * m))
        edge = smoothstep(0.95 * H, H, y)
        d = d + 0.03 * edge * (gauss(x + gx, 0.08 * m) + gauss(x - gx, 0.08 * m))
        return d


# ---------------------------------------------------------------- клыки

class Canine(Tooth):
    """Клык: бугор мезиальнее середины, мезиальный скат короче дистального;
    губной валик, бугорок; у верхнего — язычный валик и две мелкие ямки."""
    front_tooth = True

    def __init__(self, md, bl, crown, cmd, cbl, *, upper, tip_x=-0.1, mc=0.72, dc=0.56, lab=None, cing=None):
        H = crown
        m, cm, cb = md / 2, cmd / 2, cbl / 2
        lab = lab if lab is not None else bl / 2
        cg = cing if cing is not None else bl / 2
        self.ref = {"md": md, "bl": bl, "crown": crown}
        self.h_cap = H - 1.6
        self.m, self.H, self.tx, self.upper = m, H, tip_x * m, upper
        # скаты бугра — прямые с лёгкой выпуклостью: вогнутые (как в первой версии)
        # давали «сосок» на вершине
        tip = (tip_x * m, H + 0.05)
        sm = (-0.86 * m, (mc + 0.12) * H)          # мезиальный угол
        sd = (0.8 * m, (dc + 0.2) * H)             # дистальный угол
        mid_m = ((sm[0] + tip[0]) / 2, (sm[1] + tip[1]) / 2 + 0.07)
        mid_d = ((sd[0] + tip[0]) / 2, (sd[1] + tip[1]) / 2 + 0.09)
        self.front = Silhouette([
            (-cm, -3.0), (-cm, 0.0), (-(cm + 0.7 * (m - cm)), 0.3 * H), (-m, mc * H), sm, mid_m, tip, mid_d, sd,
            (m, dc * H), (cm + 0.8 * (m - cm), 0.3 * H), (cm, 0.0), (cm, -3.0)])
        self.side = Silhouette([
            (cb, -3.0), (cb, 0.0), (lab, 0.18 * H), (lab * 0.97, 0.32 * H), (lab * 0.86, 0.55 * H),
            (lab * 0.66, 0.75 * H), (lab * 0.4, 0.9 * H), (lab * 0.12, H + 0.06), (-lab * 0.12, 0.95 * H),
            (-cg * 0.42, 0.8 * H), (-cg * 0.76, 0.55 * H), (-cg, 0.3 * H), (-cg * 0.95, 0.12 * H),
            (-cb, 0.0), (-cb, -3.0)])
        top = Silhouette([
            (-m, 0.05 * lab), (-0.62 * m, 0.72 * lab), (-0.05 * m, lab), (0.55 * m, 0.74 * lab), (m, 0.02 * lab),
            (0.55 * m, -0.62 * cg), (0.0, -cg), (-0.55 * m, -0.62 * cg)])
        self.loft = Loft(self.front, self.side, [(0.0, top)])

    def sdf(self, p):
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        m, H, tx = self.m, self.H, self.tx
        d = self.body(p)
        labm = smoothstep(0.3, 1.5, z)
        lingm = smoothstep(-0.3, -1.5, z)
        # губной валик к бугру, по бокам — едва заметные вдавления
        d = d - 0.11 * gauss(x - tx, 0.28 * m) * labm * band(y, 0.1 * H, 0.45 * H, 0.92 * H, 1.02 * H)
        d = d + 0.04 * (gauss(x - tx + 0.55 * m, 0.16 * m) + gauss(x - tx - 0.55 * m, 0.16 * m)) * labm \
            * band(y, 0.3 * H, 0.55 * H, 0.85 * H, 0.95 * H)
        if self.upper:
            d = d - 0.08 * gauss(x - tx, 0.17 * m) * lingm * band(y, 0.3 * H, 0.5 * H, 0.88 * H, 0.98 * H)
            d = d + 0.13 * (gauss(x - tx + 0.42 * m, 0.17 * m) + gauss(x - tx - 0.42 * m, 0.17 * m)) * lingm \
                * band(y, 0.38 * H, 0.55 * H, 0.8 * H, 0.9 * H)
        else:
            d = d + 0.06 * gauss(x - tx, 0.35 * m) * lingm * band(y, 0.35 * H, 0.55 * H, 0.8 * H, 0.92 * H)
        return d


# ---------------------------------------------------------------- премоляры

class Premolar(Tooth):
    """Премоляр: щёчный бугор и один-два язычных; жевательная поверхность —
    рельеф из анизотропных бугров и краевых валиков (центральная фиссура и
    треугольные ямки — сами). `tilt` — наклон коронки к языку (нижние)."""

    def __init__(self, md, bl, crown, cmd, cbl, *, buccal=(0.0, 0.5), lingual=((0.0, -0.48, 1.0),),
                 gt=0.75, gin=0.78, lab=None, ling_half=None, contact=0.58, tilt=0.0, outline=None,
                 marg=(1.45, 1.6), ridges=(), mesial_pit=0.0, ling_groove=None):
        H = crown
        m, cm, cb = md / 2, cmd / 2, cbl / 2
        bb = lab if lab is not None else bl / 2
        bL = ling_half if ling_half is not None else bl / 2
        self.ref = {"md": md, "bl": bl, "crown": crown}
        self.h_cap = H - 2.6
        self.m, self.bb, self.bL, self.H, self.tilt = m, bb, bL, H, tilt
        self.mesial_pit, self.ling_groove = mesial_pit, ling_groove
        top = H + 1.0
        self.front = Silhouette([
            (-cm, -3.0), (-cm, 0.0), (-(cm + 0.78 * (m - cm)), 0.3 * H), (-m, contact * H),
            (-0.94 * m, (contact + 0.17) * H), (-0.55 * m, top), (0.55 * m, top), (0.94 * m, (contact + 0.17) * H),
            (m, contact * H), (cm + 0.78 * (m - cm), 0.3 * H), (cm, 0.0), (cm, -3.0)])
        self.side = Silhouette(_tilted([
            (cb, -3.0), (cb, 0.0), (bb, 0.2 * H), (bb * 0.96, 0.38 * H), (bb * 0.84, 0.6 * H), (bb * 0.66, 0.8 * H),
            (bb * 0.45, top), (-bL * 0.45, top), (-bL * 0.72, 0.75 * H), (-bL * 0.93, 0.55 * H), (-bL, 0.4 * H),
            (-bL * 0.96, 0.2 * H), (-cb, 0.0), (-cb, -3.0)], tilt, H))
        outline = outline or [
            (-1.0, 0.15), (-0.8, 0.7), (-0.35, 0.97), (0.35, 0.97), (0.8, 0.7), (1.0, 0.15),
            (0.8, -0.55), (0.4, -0.92), (0.0, -1.0), (-0.4, -0.92), (-0.8, -0.55)]
        self.loft = Loft(self.front, self.side,
                         [(0.0, Silhouette([(u * m, w * (bb if w > 0 else bL)) for u, w in outline]))])
        bx, bz = buccal[0] * m, buccal[1] * bb
        self.btx = bx
        # кончики острее, чем у моляра (r0): у премоляра щёчный бугор — почти клык
        cusps = [Cusp(bx, bz, H, gt=gt, gin=gin, r0=0.35)]
        lz = []
        for lx, lzf, drop, *more in lingual:
            cusps.append(Cusp(lx * m, lzf * bL, H - drop, gt=more[0] if more else 0.5, gin=gin, r0=0.5))
            lz.append(lzf * bL)
        self.center = (0.0, (bz + float(np.mean(lz))) / 2)
        parts = list(cusps)
        # краевые валики: концы — на высоте скатов бугров в этих точках (чуть ниже),
        # середина — не выше `marg`; иначе концы встают над скатами «ушками»
        mx = m - 0.8

        def on_cusps(px, pz):
            return max(float(c.height(np.array(px), np.array(pz), self.center)) for c in cusps) - 0.12
        for sx, mg in ((-1.0, marg[0]), (1.0, marg[1])):
            a = (sx * mx, 0.36 * bb)
            b = (sx * mx, -0.3 * bL)
            ha, hb = on_cusps(*a), on_cusps(*b)
            mid = min(H - mg, (ha + hb) / 2)
            parts.append(Ridge(a, (sx * mx, (a[1] + b[1]) / 2), ha, mid, slope=0.9))
            parts.append(Ridge((sx * mx, (a[1] + b[1]) / 2), b, mid, hb, slope=0.9))
        for a, b, ha, hb in ridges:
            parts.append(Ridge((a[0] * m, a[1] * bb if a[1] > 0 else a[1] * bL),
                               (b[0] * m, b[1] * bb if b[1] > 0 else b[1] * bL), H - ha, H - hb, slope=0.8, r=0.6))
        self.parts = parts

    def sdf(self, p):
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        m, H = self.m, self.H
        d = self.body(p)
        occ = relief(x, z + self.tilt, self.parts, self.center, 0.2)
        d = smax(d, (y - occ) * 0.6, 0.3)
        _, zc = self.loft.center(y)
        bm = smoothstep(zc + 0.5, zc + 2.0, z)
        lm = smoothstep(zc - 0.5, zc - 2.0, z)
        # щёчный валик бугра
        d = d - 0.12 * gauss(x - self.btx, 0.3 * m) * bm * band(y, 0.15 * H, 0.45 * H, 0.92 * H, 1.05 * H)
        if self.mesial_pit:
            d = d + self.mesial_pit * gauss(z - zc, 0.22 * (self.bb + self.bL)) \
                * smoothstep(-0.55 * m, -0.9 * m, x) * band(y, -1.0, 0.0, 0.5 * H, 0.75 * H)
        if self.ling_groove is not None:
            d = d + 0.12 * gauss(x - self.ling_groove * m, 0.45) * lm * band(y, 0.5 * H, 0.75 * H, 2 * H, 3 * H)
        return d


# ---------------------------------------------------------------- моляры

class Molar(Tooth):
    """Моляр по набору бугров: тело — лофт по трём силуэтам, жевательная
    поверхность — рельеф (бугры, валики), борозды — продолжение фиссур на
    стенки, щёчный пришеечный валик, у 16/26 — бугорок Карабелли."""

    def __init__(self, md, bl, crown, cmd, cbl, *, cusps, ridges=(), top, buc_grooves=(), ling_grooves=(),
                 lab=None, ling_half=None, contact=0.55, lingual_bulge=0.45, tilt=0.0, carabelli=0.0,
                 gt=0.45, gin=0.68, k=0.2):
        H = crown
        m, cm, cb = md / 2, cmd / 2, cbl / 2
        bb = lab if lab is not None else bl / 2
        bL = ling_half if ling_half is not None else bl / 2
        self.ref = {"md": md, "bl": bl, "crown": crown}
        self.h_cap = 0.62 * H                     # стенка до середины высоты; ниже ямок — сам `table`
        self.buc, self.ling = buc_grooves, ling_grooves
        self.H, self.tilt, self.carabelli, self.k = H, tilt, carabelli, k
        t = H + 1.3
        self.front = Silhouette([
            (-cm, -3.0), (-cm, 0.0), (-(cm + 0.72 * (m - cm)), 0.2 * H), (-(m - 0.1), 0.42 * H), (-m, contact * H),
            (-(m - 0.1), (contact + 0.18) * H), (-(m - 0.7), t), ((m - 0.7), t), ((m - 0.1), (contact + 0.18) * H),
            (m, contact * H), ((m - 0.1), 0.42 * H), (cm + 0.72 * (m - cm), 0.2 * H), (cm, 0.0), (cm, -3.0)])
        self.side = Silhouette(_tilted([
            (cb, -3.0), (cb, 0.0), (bb, 0.2 * H), (bb * 0.98, 0.35 * H), (bb * 0.9, 0.6 * H), (bb * 0.74, 0.85 * H),
            (bb * 0.55, t), (-bL * 0.55, t), (-bL * 0.76, 0.85 * H), (-bL * 0.95, 0.62 * H), (-bL, lingual_bulge * H),
            (-bL * 0.96, 0.22 * H), (-cb, 0.0), (-cb, -3.0)], tilt, H))
        self.loft = Loft(self.front, self.side, [(0.0, Silhouette(top))])
        parts = []
        for c in cusps:
            cx, cz, tip, *more = c
            parts.append(Cusp(cx, cz, tip, gt=more[0] if more else gt, gin=more[1] if len(more) > 1 else gin,
                              r0=1.0, bulge=0.045))
        for a, b, ha, *more in ridges:
            parts.append(Ridge(a, b, ha, more[0] if more else None, slope=more[1] if len(more) > 1 else 0.9))
        self.parts = parts

    def sdf(self, p):
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        H = self.H
        d = self.body(p)
        occ = relief(x, z + self.tilt, self.parts, (0.0, 0.0), self.k)
        d = smax(d, (y - occ) * 0.6, 0.3)
        _, zc = self.loft.center(y)
        bm = smoothstep(zc + 1.0, zc + 3.0, z)
        lm = smoothstep(zc - 1.0, zc - 3.0, z)
        buc = bm * smoothstep(0.42 * H, 0.83 * H, y)
        for gx in self.buc:
            d = d + 0.16 * buc * gauss(x - gx, 0.55)
        lin = lm * smoothstep(0.48 * H, 0.82 * H, y)
        for gx in self.ling:
            d = d + 0.14 * lin * gauss(x - gx, 0.6)
        d = d - 0.08 * gauss(y - 0.22 * H, 0.2 * H) * bm
        if self.carabelli:
            d = d - self.carabelli * np.exp(-((x + 2.3) / 1.0) ** 2 - ((y - 0.52 * H) / 0.9) ** 2) * lm
        return d


# ---------------------------------------------------------------- реестр

TYPES = {
    # --- верхние
    "U1": lambda: Incisor(8.6, 7.0, 10.5, 7.3, 6.0, contact_m=0.76, contact_d=0.66, corner_m=0.55, corner_d=1.25,
                          edge_drop=0.22, lab=3.5, cing=3.4, lobes=0.1, fossa=0.45, edge_t=1.0, edge_z=0.3,
                          cing_x=0.08),
    "U2": lambda: Incisor(6.6, 6.0, 9.0, 5.5, 5.0, contact_m=0.72, contact_d=0.58, corner_m=0.9, corner_d=1.9,
                          edge_drop=0.35, lobes=0.06, fossa=0.5, edge_t=0.9),
    "U3": lambda: Canine(7.6, 8.0, 10.0, 6.1, 7.0, upper=True, tip_x=-0.1, mc=0.68, dc=0.52),
    "U4": lambda: Premolar(7.0, 9.0, 8.5, 5.6, 8.0, buccal=(0.06, 0.5), lingual=((-0.08, -0.5, 1.0),),
                           outline=[(-0.97, 0.15), (-0.8, 0.72), (-0.35, 0.98), (0.35, 0.98), (0.8, 0.72),
                                    (1.0, 0.15), (0.78, -0.5), (0.36, -0.9), (0.0, -1.0), (-0.38, -0.9),
                                    (-0.8, -0.5)],
                           mesial_pit=0.18),
    "U5": lambda: Premolar(6.8, 9.0, 8.0, 5.5, 8.0, buccal=(0.0, 0.48), lingual=((0.0, -0.48, 0.4),),
                           marg=(1.35, 1.45)),
    "U6": lambda: Molar(10.4, 11.2, 7.4, 8.5, 10.0,
                        cusps=[(-2.5, 3.0, 7.35), (2.6, 2.9, 7.0), (-2.0, -2.6, 7.25, 0.45), (2.8, -2.4, 6.5, 0.6)],
                        ridges=[((-2.0, -2.6), (2.6, 2.9), 6.2, 5.95, 0.8), ((-4.35, 2.6), (-4.3, -2.6), 6.15),
                                ((4.25, 2.4), (4.1, -2.2), 5.8)],
                        top=[(-5.0, 3.6), (-4.0, 5.0), (-1.8, 5.55), (0.2, 5.3), (2.3, 5.45), (4.2, 4.8), (5.0, 3.0),
                             (5.1, 0.6), (4.6, -1.8), (3.8, -3.6), (2.4, -4.9), (0.4, -5.55), (-1.6, -5.45),
                             (-3.4, -4.6), (-4.6, -3.0), (-5.2, -0.8), (-5.3, 1.4)],
                        buc_grooves=(0.15,), ling_grooves=(1.0,), lab=5.65, ling_half=5.6, contact=0.56,
                        carabelli=0.16),
    "U7": lambda: Molar(9.2, 11.0, 7.0, 7.8, 10.0,
                        cusps=[(-2.2, 3.0, 7.0), (2.25, 2.6, 6.6), (-1.8, -2.6, 7.0, 0.45), (2.4, -2.0, 6.0, 0.62)],
                        ridges=[((-1.6, -2.3), (2.0, 2.3), 5.95, 5.7, 0.8), ((-3.95, 2.6), (-3.9, -2.5), 5.85),
                                ((3.85, 2.2), (3.55, -1.8), 5.5)],
                        top=[(-4.5, 3.4), (-3.5, 4.9), (-1.4, 5.5), (0.6, 5.3), (2.5, 5.1), (4.1, 4.0), (4.6, 1.8),
                             (4.2, -0.8), (3.0, -3.0), (1.2, -4.8), (-1.0, -5.4), (-3.0, -4.6), (-4.3, -2.6),
                             (-4.7, 0.4)],
                        buc_grooves=(0.1,), ling_grooves=(1.0,)),
    "U8": lambda: Molar(8.6, 10.2, 6.5, 7.3, 9.2,
                        cusps=[(-1.9, 2.7, 6.5), (1.9, 2.3, 6.1), (-0.5, -2.4, 6.5, 0.45)],
                        ridges=[((-3.5, 2.4), (-3.0, -2.1), 5.35)],
                        top=[(-4.2, 3.0), (-3.0, 4.6), (-0.8, 5.1), (1.6, 4.8), (3.7, 3.4), (4.3, 1.0), (3.6, -1.8),
                             (1.8, -4.2), (-0.6, -5.0), (-2.8, -4.2), (-4.1, -1.8), (-4.4, 1.0)],
                        buc_grooves=(0.0,), lingual_bulge=0.5),
    # --- нижние
    "L1": lambda: Incisor(5.4, 6.0, 9.0, 4.1, 5.4, contact_m=0.8, contact_d=0.78, corner_m=0.35, corner_d=0.5,
                          edge_drop=0.0, lobes=0.035, fossa=0.15, edge_t=0.85, edge_z=-0.15),
    "L2": lambda: Incisor(5.9, 6.3, 9.5, 4.5, 5.8, contact_m=0.78, contact_d=0.7, corner_m=0.4, corner_d=0.9,
                          edge_drop=0.12, lobes=0.035, fossa=0.18, edge_t=0.85, edge_z=-0.15),
    "L3": lambda: Canine(7.0, 7.6, 11.0, 5.8, 7.0, upper=False, tip_x=-0.08, mc=0.72, dc=0.55),
    "L4": lambda: Premolar(7.0, 7.6, 8.5, 5.6, 6.6, buccal=(-0.02, 0.3), lingual=((-0.12, -0.55, 2.4, 0.7),),
                           gin=0.7, lab=4.0, ling_half=3.6, tilt=1.0, marg=(1.6, 1.8),
                           ridges=[((-0.02, 0.3), (-0.12, -0.55), 1.15, 2.6)],
                           outline=[(-1.0, 0.1), (-0.78, 0.7), (-0.32, 0.98), (0.32, 0.98), (0.8, 0.68),
                                    (1.0, 0.1), (0.72, -0.52), (0.3, -0.9), (-0.05, -1.0), (-0.42, -0.86),
                                    (-0.78, -0.48)]),
    "L5": lambda: Premolar(7.2, 8.2, 8.0, 5.7, 7.0, buccal=(-0.02, 0.36),
                           lingual=((-0.42, -0.5, 1.0), (0.45, -0.5, 1.35)), lab=4.1, ling_half=4.1, tilt=0.6,
                           ling_groove=0.12,
                           outline=[(-1.0, 0.12), (-0.82, 0.72), (-0.35, 0.98), (0.35, 0.98), (0.82, 0.72),
                                    (1.0, 0.12), (0.9, -0.62), (0.5, -0.95), (0.0, -1.0), (-0.5, -0.95),
                                    (-0.9, -0.62)]),
    "L6": lambda: Molar(11.0, 10.4, 7.5, 9.0, 9.0,
                        cusps=[(-3.3, 2.5, 7.1), (0.2, 2.9, 6.8), (3.6, 1.6, 6.3, 0.6),
                               (-2.7, -2.6, 7.5, 0.5, 0.95), (2.1, -2.6, 7.2, 0.5, 0.95)],
                        ridges=[((-4.7, 2.6), (-4.6, -2.5), 6.1), ((4.6, 1.9), (4.4, -2.3), 5.8)],
                        top=[(-5.4, 2.6), (-4.6, 4.4), (-2.6, 5.1), (0.0, 5.0), (2.6, 4.7), (4.6, 3.5), (5.5, 1.0),
                             (5.2, -2.0), (4.2, -4.0), (1.8, -4.9), (-1.2, -5.0), (-3.8, -4.4), (-5.2, -2.4),
                             (-5.6, 0.2)],
                        buc_grooves=(-1.6, 1.9), ling_grooves=(-0.3,), lingual_bulge=0.5, tilt=0.8),
    "L7": lambda: Molar(10.5, 10.0, 7.0, 8.5, 9.0,
                        cusps=[(-2.6, 2.5, 6.9), (2.5, 2.5, 6.6), (-2.5, -2.5, 7.2, 0.5, 0.95),
                               (2.4, -2.5, 6.9, 0.5, 0.95)],
                        ridges=[((-4.4, 2.4), (-4.3, -2.4), 5.9), ((4.3, 2.2), (4.1, -2.2), 5.6)],
                        top=[(-5.1, 2.4), (-4.2, 4.3), (-1.8, 4.9), (1.0, 4.9), (3.6, 4.3), (5.0, 2.5), (5.3, 0.0),
                             (4.8, -2.6), (3.4, -4.4), (0.6, -4.9), (-2.4, -4.8), (-4.4, -3.6), (-5.3, -1.2)],
                        buc_grooves=(0.0,), ling_grooves=(0.0,), lingual_bulge=0.5, tilt=0.7),
    "L8": lambda: Molar(10.0, 9.5, 6.8, 8.0, 8.6,
                        cusps=[(-2.3, 2.3, 6.6), (2.3, 2.2, 6.3), (-2.2, -2.3, 6.8, 0.5, 0.9),
                               (2.2, -2.2, 6.5, 0.5, 0.9), (0.1, 0.1, 5.3, 0.9, 0.9)],
                        ridges=[((-4.0, 2.2), (-3.9, -2.1), 5.6), ((4.0, 1.9), (3.8, -1.9), 5.3)],
                        top=[(-4.8, 2.4), (-3.8, 4.1), (-1.4, 4.7), (1.4, 4.6), (3.7, 3.8), (4.8, 1.8), (4.9, -0.8),
                             (4.0, -3.2), (2.0, -4.6), (-0.6, -4.8), (-3.0, -4.2), (-4.5, -2.4), (-5.0, 0.0)],
                        buc_grooves=(0.0,), ling_grooves=(0.0,), lingual_bulge=0.5, tilt=0.6),
}

G.TEETH.update(TYPES)
ALL = ["U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"]
