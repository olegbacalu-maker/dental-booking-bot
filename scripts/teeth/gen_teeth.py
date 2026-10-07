# -*- coding: utf-8 -*-
"""Свои модели зубов (06.10 образец 11 и 16; 07.10 вторая версия — все 16 типов).

Лепка расстояниями со знаком (SDF):
1. стенка — ЛОФТ: сечение на высоте y — контур зуба сверху (один или два, со
   смешиванием по высоте), растянутый на ширину силуэта спереди и глубину
   силуэта сбоку НА ЭТОЙ высоте. Первая версия брала пересечение трёх
   выдавленных силуэтов — это коробка с рёбрами по углам (премоляр «столбиком»);
   у лофта углы скруглены так же, как у самого контура;
2. верх жевательных зубов — РЕЛЬЕФ: бугры (анизотропные: пологие вдоль края
   коронки — скаты бугра, круче к центру — треугольные валики), валики краевые,
   косой и поперечный; мягкий максимум сам даёт фиссуры и ямки;
3. детали — смещения поверхности (ямка резца, валики клыка, борозды моляров):
   ни одного тела, которое могло бы проткнуть стенку или торчать наружу.

Силуэт — ТОЧНОЕ расстояние до плотного сплайна (дерево ближайших вершин +
расстояние до двух соседних отрезков), растр 0,02 мм и кубическая выборка.
В первой версии знак и величина шли из растра заливки — ступеньки пикселя
давали полосы на каждом блике.

Выход — ТАБЛИЦА для программы, а не сетка: радиус стенки коронки по высоте и
углу вокруг центра сечения + высоты жевательной поверхности (кольца к центру).
Программа строит по ней коронку (`three/sculpt.ts`), поэтому десна, корни и
слой пародонта работают без переделок.

Оси (как в программе): +x дистально, −x мезиально, +z щёчно/губно, −z язычно/
нёбно, +y окклюзионно; шейка (CEJ) — плоскость y = 0. Миллиметры эталона.

Запуск:  python gen_teeth.py [U1 …] --table      (типы — в family.py)
"""
import json
import pathlib
import sys

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree

HERE = pathlib.Path(__file__).resolve().parent


# ---------------------------------------------------------------- примитивы

def length(v):
    return np.sqrt(np.sum(v * v, axis=-1))


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b + (a - b) * h - k * h * (1.0 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def soft_max(vals, k):
    out = vals[0]
    for v in vals[1:]:
        out = smax(out, v, k)
    return out


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def gauss(v, w):
    return np.exp(-(v / w) ** 2)


def band(y, a0, a1, b0, b1):
    """Полоса по высоте: растёт на [a0, a1], гаснет на [b0, b1]."""
    return smoothstep(a0, a1, y) * (1.0 - smoothstep(b0, b1, y))


def seg_dist(x, z, a, b):
    """Расстояние на плоскости x–z до отрезка a–b и доля вдоль него."""
    ax, az = a
    bx, bz = b
    vx, vz = bx - ax, bz - az
    t = np.clip(((x - ax) * vx + (z - az) * vz) / (vx * vx + vz * vz), 0.0, 1.0)
    return np.hypot(x - (ax + t * vx), z - (az + t * vz)), t


# ---------------------------------------------------------------- силуэты

def catmull_closed(pts, per=160):
    """Замкнутый сплайн Катмулла–Рома через точки → плотный многоугольник."""
    P = np.asarray(pts, float)
    n = len(P)
    t = np.linspace(0, 1, per, endpoint=False)[:, None]
    t2, t3 = t * t, t * t * t
    out = []
    for i in range(n):
        p0, p1, p2, p3 = P[(i - 1) % n], P[i], P[(i + 1) % n], P[(i + 2) % n]
        out.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                          + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    return np.concatenate(out)


def poly_sdf(poly, P, chunk=250000):
    """Точное расстояние со знаком от точек P до замкнутого многоугольника (обход
    против часовой). Ближайшая вершина — деревом, дальше два соседних отрезка;
    знак — по наружной нормали отрезка (в вершине — по средней)."""
    A = poly
    D = np.roll(poly, -1, 0) - A
    L2 = np.maximum(np.sum(D * D, 1), 1e-18)
    Ns = np.stack([D[:, 1], -D[:, 0]], -1)
    Ns /= np.maximum(np.linalg.norm(Ns, axis=1, keepdims=True), 1e-12)
    Nv = Ns + np.roll(Ns, 1, 0)
    Nv /= np.maximum(np.linalg.norm(Nv, axis=1, keepdims=True), 1e-12)
    tree = cKDTree(A)
    M = len(A)
    out = np.empty(len(P))
    for s in range(0, len(P), chunk):
        p = P[s:s + chunk]
        _, i = tree.query(p)
        best = np.full(len(p), np.inf)
        sgn = np.ones(len(p))
        for seg in ((i - 1) % M, i):
            a = A[seg]
            d = D[seg]
            t = np.clip(np.einsum("ij,ij->i", p - a, d) / L2[seg], 0.0, 1.0)
            r = p - (a + t[:, None] * d)
            dist = np.sqrt(np.einsum("ij,ij->i", r, r))
            n = Ns[seg]
            n = np.where((t <= 0.0)[:, None], Nv[seg], n)
            n = np.where((t >= 1.0)[:, None], Nv[(seg + 1) % M], n)
            sg = np.where(np.einsum("ij,ij->i", r, n) >= 0, 1.0, -1.0)
            better = dist < best
            best = np.where(better, dist, best)
            sgn = np.where(better, sg, sgn)
        out[s:s + chunk] = best * sgn
    return out


class Silhouette:
    """2D-силуэт → точное знаковое расстояние на растре 0,02 мм, выборка кубическим
    сплайном (у билинейки нормаль скачет на каждой клетке — полосы на свету)."""

    def __init__(self, pts, lo=-9.0, hi=14.0, px=0.02):
        poly = catmull_closed(pts)
        a, b = poly, np.roll(poly, -1, 0)
        if np.sum(a[:, 0] * b[:, 1] - b[:, 0] * a[:, 1]) < 0:
            poly = poly[::-1].copy()
        self.poly = poly
        self.lo, self.px = lo, px
        n = int(round((hi - lo) / px)) + 1
        g = lo + px * np.arange(n)
        U, V = np.meshgrid(g, g)                 # строка — v, столбец — u
        sdf = poly_sdf(poly, np.stack([U.ravel(), V.ravel()], -1)).reshape(n, n)
        self.coef = ndimage.spline_filter(sdf, order=3)
        self.u0, self.u1 = float(poly[:, 0].min()), float(poly[:, 0].max())
        self.v0, self.v1 = float(poly[:, 1].min()), float(poly[:, 1].max())

    def __call__(self, u, v):
        iu = (u - self.lo) / self.px
        iv = (v - self.lo) / self.px
        coords = np.stack([np.ravel(iv), np.ravel(iu)])
        return ndimage.map_coordinates(self.coef, coords, order=3, mode="nearest",
                                       prefilter=False).reshape(np.shape(u))


def extents(poly, ys, chunk=120):
    """Наименьшая и наибольшая u многоугольника на каждой высоте v = ys."""
    A = poly
    B = np.roll(poly, -1, 0)
    ya, yb, xa, xb = A[:, 1], B[:, 1], A[:, 0], B[:, 0]
    dy = yb - ya
    ok = np.abs(dy) > 1e-12
    dys = np.where(ok, dy, 1.0)
    lo = np.empty(len(ys))
    hi = np.empty(len(ys))
    for s in range(0, len(ys), chunk):
        y = ys[s:s + chunk, None]
        t = (y - ya[None]) / dys[None]
        m = ok[None] & (t >= 0) & (t < 1)
        x = xa[None] + t * (xb - xa)[None]
        lo[s:s + chunk] = np.where(m, x, np.inf).min(1)
        hi[s:s + chunk] = np.where(m, x, -np.inf).max(1)
    lo[~np.isfinite(lo)] = np.nan
    hi[~np.isfinite(hi)] = np.nan
    return lo, hi


class Loft:
    """Стенка: сечение на высоте y — контур сверху, растянутый на ширину силуэта
    спереди (x) и глубину силуэта сбоку (z) на этой высоте.

    `sections` — [(y, контур)] по возрастанию: между ключами контуры смешиваются
    (у резца треугольник у шейки переходит в линзу к режущему краю).
    Там, где ширина силуэта меняется круче `gmax` (скругление режущего края,
    вершина клыка), сечение замирает и форму дорезают сами силуэты — иначе
    расстояние врёт в разы. Ниже шейки (только для кадров: таблица шейку не
    видит) сечение сужается тем же правилом, что корень в программе."""

    def __init__(self, front, side, sections, gmax=12.0, step=0.01):
        ys = np.arange(-2.6, 14.0 + step / 2, step)
        xl, xr = extents(front.poly, ys)
        zl, zr = extents(side.poly, ys)
        gx = self._hold(ys, xl, xr, gmax)
        gz = self._hold(ys, zl, zr, gmax)
        g = np.maximum(gx, gz)
        g = ndimage.maximum_filter1d(g, size=61)          # ±0,3 мм — с запасом
        # корень: сечение шейки сужается к корню (как `surf` в sculpt.ts)
        dd = np.clip(-ys, 0, None)
        w = np.where(dd <= 2.4, 1 - 0.14 * smoothstep(0, 2.4, dd), 0.86)
        for lo_, hi_ in ((xl, xr), (zl, zr)):
            c = (lo_ + hi_) / 2
            h = (hi_ - lo_) / 2 * w
            lo_[:] = c - h
            hi_[:] = c + h
        self.ys, self.step = ys, step
        self.xl, self.xr, self.zl, self.zr = xl, xr, zl, zr
        self.lipv = np.sqrt(1 + np.minimum(g, gmax) ** 2)
        self.sections = sections

    @staticmethod
    def _hold(ys, lo, hi, gmax):
        s = np.maximum(np.abs(np.gradient(lo, ys)), np.abs(np.gradient(hi, ys)))
        s[~np.isfinite(s)] = np.inf
        bad = np.nonzero((ys > 0.0) & (s > gmax))[0]
        k = int(bad[0]) - 1 if len(bad) else len(ys) - 1
        lo[k + 1:] = lo[k]
        hi[k + 1:] = hi[k]
        s[k + 1:] = 0.0
        return s

    def at(self, y):
        """Края сечения на высоте y: xl, xr, zl, zr и запас по наклону."""
        fi = (np.clip(y, self.ys[0], self.ys[-1]) - self.ys[0]) / self.step
        i0 = np.clip(np.floor(fi).astype(int), 0, len(self.ys) - 2)
        f = fi - i0

        def lerp(a):
            return a[i0] + (a[i0 + 1] - a[i0]) * f
        return lerp(self.xl), lerp(self.xr), lerp(self.zl), lerp(self.zr), lerp(self.lipv)

    def __call__(self, p):
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        xl, xr, zl, zr, lip = self.at(y)
        wx = np.maximum(xr - xl, 0.05)
        wz = np.maximum(zr - zl, 0.05)
        parts = []
        for _, T in self.sections:
            bw, bd = T.u1 - T.u0, T.v1 - T.v0
            X = T.u0 + (x - xl) / wx * bw
            Z = T.v0 + (z - zl) / wz * bd
            parts.append(T(X, Z) * np.minimum(wx / bw, wz / bd))
        d = parts[0]
        for k in range(1, len(parts)):
            t = smoothstep(self.sections[k - 1][0], self.sections[k][0], y)
            d = d + (parts[k] - d) * t
        # ⚠️ НЕ делить на запас по наклону: смещения и мягкие стыки считают в этих
        # единицах, и там, где расстояние сжато в 12 раз, доля 0,03 мм вырастала
        # в 0,36 — бусины на режущем крае. Запас нужен только шагу луча (`lip`).
        return d

    def lip(self, y):
        """Во сколько раз расстояние лофта может врать по вертикали — делитель
        шага луча в кадрах (таблице не нужен: она ищет пересечения густо)."""
        return self.at(y)[4]

    def center(self, y):
        xl, xr, zl, zr, _ = self.at(y)
        return (xl + xr) / 2, (zl + zr) / 2


# ---------------------------------------------------------------- рельеф

class Cusp:
    """Бугор: вершина (x, z) на высоте tip; скаты анизотропные — вдоль края
    коронки `gt` (скаты бугра), к центру жевательной поверхности `gin`
    (треугольный валик), наружу `gout`. Кончик скруглён радиусом r0."""

    def __init__(self, x, z, tip, gt=0.55, gin=0.85, gout=1.25, r0=0.85, bulge=0.06):
        self.x, self.z, self.tip = x, z, tip
        self.gt, self.gin, self.gout, self.r0 = gt, gin, gout, r0
        self.bulge = bulge                                # выпуклость: конус даёт плоские грани

    def height(self, x, z, center):
        ux, uz = center[0] - self.x, center[1] - self.z
        n = np.hypot(ux, uz)
        dx, dz = x - self.x, z - self.z
        if n < 0.3:                                       # бугор в центре — круглый
            e = self.gin * np.hypot(dx, dz)
            return self.tip - (np.sqrt(e * e + self.r0 ** 2) - self.r0) - self.bulge * e * e
        ux, uz = ux / n, uz / n
        dr = dx * ux + dz * uz                            # > 0 — к центру
        dt = -dx * uz + dz * ux
        gr = self.gout + (self.gin - self.gout) * smoothstep(-0.3, 0.3, dr)
        e2 = (self.gt * dt) ** 2 + (gr * dr) ** 2
        return self.tip - (np.sqrt(e2 + self.r0 ** 2) - self.r0) - self.bulge * e2


class Ridge:
    """Валик вдоль отрезка a–b: высота от ha до hb, скат поперёк `slope`."""

    def __init__(self, a, b, ha, hb=None, slope=0.9, r=0.55):
        self.a, self.b, self.ha = a, b, ha
        self.hb = ha if hb is None else hb
        self.slope, self.r = slope, r

    def height(self, x, z, center):
        dist, t = seg_dist(x, z, self.a, self.b)
        h = self.ha + (self.hb - self.ha) * t
        return h - self.slope * (np.sqrt(dist * dist + self.r * self.r) - self.r)


def relief(x, z, parts, center, k=0.22):
    return soft_max([p.height(x, z, center) for p in parts], k)


# ---------------------------------------------------------------- зуб

class Tooth:
    """Основа: лофт по трём силуэтам + обрезка самими силуэтами (верх резца,
    вершина клыка). Наследники задают front/side/top и `detail`."""
    ref: dict
    h_cap: float
    front_tooth = False

    def body(self, p):
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        trim = np.maximum(self.front(x, y), self.side(z, y))
        return smax(self.loft(p), trim, 0.15)

    def sdf(self, p):
        return self.body(p)

    def step(self, p, d):
        """Безопасный шаг луча в кадрах: у тела — расстояние, делённое на запас лофта
        по наклону; вдали — расстояние до обрезки силуэтами (она точная, а тело
        внутри неё; 0,6 мм — запас на смещения-валики). Без второго члена лучи над
        режущим краем ползли шагом /12 и не доходили — «вилка» на вершине резца."""
        x, y, z = p[..., 0], p[..., 1], p[..., 2]
        trim = np.maximum(self.front(x, y), self.side(z, y))
        return np.maximum(d / self.loft.lip(y), trim - 0.6)


TEETH = {}


# ---------------------------------------------------------------- таблица

N_TH = 96
RINGS = 24
# кольца жевательной поверхности гуще у края: там над стенкой ещё крутой подъём
# к буграм, и равные шаги (16 колец через 6 %) давали складку-поясок на стыке
CAP_S = [round(1.0 - (i / RINGS) ** 1.8, 5) for i in range(1, RINGS)]


def _first_cross(f, lo, hi, step, inside_first=True, iters=12):
    """По каждому лучу (строка f(t) — функция параметра) — первое пересечение.
    f: t[(n, m)] → sdf[(n, m)]; ищет первую смену знака на сетке шага step,
    потом уточняет делением пополам."""
    ts = np.arange(lo, hi + step / 2, step)
    D = f(np.broadcast_to(ts, (f.n, len(ts))))
    hit = (D > 0) if inside_first else (D <= 0)
    k = np.argmax(hit, axis=1)
    found = hit[np.arange(f.n), k]
    k = np.where(found, k, len(ts) - 1)
    k = np.maximum(k, 1)
    a = ts[k - 1].astype(float)
    b = ts[k].astype(float)
    for _ in range(iters):
        m = (a + b) / 2
        dm = f(m[:, None])[:, 0]
        cond = (dm > 0) if inside_first else (dm <= 0)
        b = np.where(cond, m, b)
        a = np.where(cond, a, m)
    return (a + b) / 2, found


class _Rays:
    def __init__(self, sdf, origin, dirs):
        self.sdf, self.o, self.d = sdf, origin, dirs
        self.n = len(origin)

    def __call__(self, t):
        P = self.o[:, None, :] + t[..., None] * self.d[:, None, :]
        return self.sdf(P.reshape(-1, 3)).reshape(t.shape)


def occlusal_floor(tooth, hc, H):
    """Самая низкая точка верха над сечением высоты hc (центральная ямка, фиссуры):
    стенка таблицы обязана кончиться НИЖЕ — иначе луч из центра сечения стартует
    в воздухе ямки и даёт радиус 0,5 мм вместо 5 (так было у 37 на первом запекании)."""
    g = np.linspace(-7, 7, 71)
    GX, GZ = np.meshgrid(g, g)
    pts = np.stack([GX.ravel(), np.full(GX.size, hc), GZ.ravel()], -1)
    d = tooth.sdf(pts)
    inside = d <= -0.6                             # внутри, не у самой стенки
    if not inside.any():                           # тонкое сечение (резец у края)
        inside = d <= -0.15
    if not inside.any():
        return hc + 1.0
    xs, zs = GX.ravel()[inside], GZ.ravel()[inside]
    top = H + 3.0
    o = np.stack([xs, np.full(len(xs), top), zs], -1)
    down = np.tile([0.0, -1.0, 0.0], (len(xs), 1))
    t, ok = _first_cross(_Rays(tooth.sdf, o, down), 0.0, top - hc + 0.5, 0.03, inside_first=False)
    return float((top - t[ok]).min())


def table(name):
    tooth = TEETH[name]()
    H = tooth.ref["crown"]
    hc = tooth.h_cap
    floor = occlusal_floor(tooth, hc, H)
    if floor - 0.3 < hc:
        print(f"  {name}: верх опускается до {floor:.2f} — стенка до {floor - 0.3:.2f} вместо {hc:.2f}", flush=True)
        hc = floor - 0.3
    # строки гуще у шейки (там садится десна), до верха стенки — плавно реже
    heights = hc * np.linspace(0.0, 1.0, 34) ** 1.15
    th = 2 * np.pi * np.arange(N_TH) / N_TH
    dirs2 = np.stack([np.cos(th), np.sin(th)], -1)          # (x, z)
    g = np.linspace(-8, 8, 161)
    GX, GZ = np.meshgrid(g, g)
    rows, cxs, czs = [], [], []
    for h in heights:
        pts = np.stack([GX, np.full_like(GX, h), GZ], -1).reshape(-1, 3)
        inside = tooth.sdf(pts) <= 0
        cx = float(GX.ravel()[inside].mean())
        cz = float(GZ.ravel()[inside].mean())
        o = np.tile([cx, h, cz], (N_TH, 1))
        d3 = np.stack([dirs2[:, 0], np.zeros(N_TH), dirs2[:, 1]], -1)
        r, ok = _first_cross(_Rays(tooth.sdf, o, d3), 0.0, 9.0, 0.04, inside_first=True)
        assert ok.all(), f"{name}: стенка не найдена на высоте {h}"
        rows.append(r)
        cxs.append(cx)
        czs.append(cz)
    # жевательная поверхность: кольца от контура верхнего ряда к центру, высота — лучом сверху
    rc, cxc, czc = rows[-1], cxs[-1], czs[-1]
    top = H + 3.0
    cap = []
    down = np.tile([0.0, -1.0, 0.0], (N_TH, 1))
    for s in CAP_S:
        o = np.stack([cxc + s * rc * dirs2[:, 0], np.full(N_TH, top), czc + s * rc * dirs2[:, 1]], -1)
        t, ok = _first_cross(_Rays(tooth.sdf, o, down), 0.0, top - hc + 1.5, 0.03, inside_first=False)
        cap.append(np.where(ok, top - t, hc))
    o = np.array([[cxc, top, czc]])
    t, ok = _first_cross(_Rays(tooth.sdf, o, np.array([[0.0, -1.0, 0.0]])), 0.0, top - hc + 1.5, 0.03,
                         inside_first=False)
    center = float(top - t[0]) if ok[0] else hc
    out = {
        "type": name, "ref": tooth.ref, "hCap": round(float(hc), 4), "theta": N_TH,
        "heights": [round(float(h), 4) for h in heights],
        "cx": [round(v, 4) for v in cxs], "cz": [round(v, 4) for v in czs],
        "r": [[round(float(v), 4) for v in row] for row in rows],
        "cap": [[round(float(v), 4) for v in ring] for ring in cap], "capS": CAP_S, "capCenter": round(center, 4),
    }
    path = HERE / f"table_{name}.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    tip = max(max(r) for r in out["cap"] + [[center]])
    print("table:", path.name, "rows", len(heights), "tip", round(tip, 2), flush=True)
    return out


if __name__ == "__main__":
    import family                       # регистрирует типы в модуле gen_teeth (не в __main__)
    G = family.G
    args = sys.argv[1:]
    names = [a for a in args if a in G.TEETH] or list(G.TEETH)
    for nm in names:
        G.table(nm)
