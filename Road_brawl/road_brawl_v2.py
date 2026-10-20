#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
 ROAD BRAWL v2  -  pixel-art motorcycle combat racer for the terminal
 ---------------------------------------------------------------------
 What's new compared to v1
   * Bikes and riders are drawn as tiny pixel art using half-block
     characters (the top and bottom half of each cell are separate
     "pixels"), so you see a real rider on a real motorcycle from behind:
     helmet, jacket, arms on the bars, legs, boots, exhaust pipes, tail light,
     spinning rear tyre, nitro flames.
   * Smooth perspective scaling of every sprite (no more 4 fixed sizes).
   * Animated combat: wind-up, punch / kick extension, recovery, impact
     flash + sparks, rider knock-back, and tumbling crashes.
   * The world is dithered with shade glyphs (░ ▒ ▓ █): smooth sky and sun
     gradients, hazy mountains with lit / shaded faces, distance fog, clouds,
     asphalt grain and grass texture.
   * Pixel-art scenery (trees, pines, cacti, rocks, lamps, signs, billboards).

 Needs a UTF-8 terminal with 256 colours.  Standard library only.
 Windows:  pip install windows-curses

 Run:  python3 road_brawl_v2.py          (best at 110x34 or larger)

 CONTROLS
   A / D or LEFT / RIGHT   steer (tap = nudge, hold = keep turning)
   S or DOWN               brake
   Z / X                   PUNCH left / right   (fast, 1 damage)
   C / V                   KICK  left / right   (slow, 2 damage, longer reach)
   SPACE                   nitro on / off
   P pause     Q quit
"""
import bisect
import curses
import locale
import math
import random
import time

TRACK_LEN = 7200.0
ZONE_LEN = 1800.0
DEPTH = 48.0
FPS = 30
MAX_SPEED = 44.0
BOOST_SPEED = 58.0
N_RIVALS = 8

USE256 = True


# --------------------------------------------------------------------------
#  helpers
# --------------------------------------------------------------------------
def clamp(v, a, b):
    return a if v < a else b if v > b else v


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_rgb(c1, c2, t):
    t = clamp(t, 0.0, 1.0)
    return (c1[0] + (c2[0] - c1[0]) * t,
            c1[1] + (c2[1] - c1[1]) * t,
            c1[2] + (c2[2] - c1[2]) * t)


def G(v):
    return (v, v, v)


def ci(c):
    """(r,g,b) 0..5 floats -> terminal colour index"""
    r, g, b = c
    if abs(r - g) < 0.02 and abs(g - b) < 0.02:
        v = clamp(r, 0.0, 5.0) / 5.0
        if not USE256:
            return 7 if v > 0.45 else 0
        if v >= 0.98:
            return 231
        if v <= 0.02:
            return 16
        return 232 + int(round(v * 23))
    ri = int(round(clamp(r, 0, 5)))
    gi = int(round(clamp(g, 0, 5)))
    bi = int(round(clamp(b, 0, 5)))
    if USE256:
        return 16 + 36 * ri + 6 * gi + bi
    return (1 if ri >= 3 else 0) | (2 if gi >= 3 else 0) | (4 if bi >= 3 else 0)


_PAIRS = {}


def pair(fg, bg):
    key = (fg, bg)
    p = _PAIRS.get(key)
    if p is None:
        n = len(_PAIRS) + 1
        if n >= curses.COLOR_PAIRS:
            return 0
        try:
            curses.init_pair(n, fg, bg)
            p = n
        except curses.error:
            p = 0
        _PAIRS[key] = p
    return curses.color_pair(p)


# ordered-dither tables ----------------------------------------------------
BAYER = [[(v + 0.5) / 16.0 for v in row] for row in
         ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))]
GLY = (' ', '\u2591', '\u2592', '\u2593', '\u2588')   # space ░ ▒ ▓ █


def dq(f, x, y):
    """dither level 0..4 for blend fraction f at cell (x, y)"""
    q = int(f * 4 + (BAYER[y & 3][x & 3] - 0.5) * 0.9 + 0.5)
    return 0 if q < 0 else 4 if q > 4 else q


# --------------------------------------------------------------------------
#  themes / track  (same layout as v1)
# --------------------------------------------------------------------------
THEMES = [
    dict(name="SUNSET VALLEY",
         sky=((0, 0, 1.2), (2.6, 0.4, 2.4), (5, 3, 1)),
         sun=(5, 5, 1), mfar=(2.4, 0.6, 2.2), mnear=(1.2, 0.2, 1.4),
         gA=(0.2, 2, 0.2), gB=(0, 1.6, 0.2), leaf=(0, 3, 0), stars=0.6,
         scenery=['tree', 'tree', 'lamp', 'sign', 'rock', 'bill']),
    dict(name="DESERT MESA",
         sky=((0, 1, 3), (2.5, 3, 5), (5, 4, 2.5)),
         sun=(5, 5, 3), mfar=(4, 2, 1), mnear=(3, 1, 0.5),
         gA=(5, 4, 1.2), gB=(4.4, 3.4, 1), leaf=(1, 3, 0), stars=0.0,
         scenery=['cactus', 'cactus', 'rock', 'rock', 'sign', 'bill']),
    dict(name="NEON NIGHT",
         sky=((0, 0, 0), (1.2, 0, 2), (4.5, 0.2, 3.5)),
         sun=(5, 1, 4), mfar=(1.2, 0, 2.2), mnear=(0.3, 0, 1.2),
         gA=(0, 0.3, 1.4), gB=(0, 0, 1.0), leaf=(0, 1.5, 3), stars=1.0,
         scenery=['lamp', 'lamp', 'bill', 'pine', 'sign']),
    dict(name="MISTY PINES",
         sky=((1, 2.5, 4.5), (3, 4, 5), (5, 5, 4.5)),
         sun=(5, 5, 3), mfar=(2.2, 3.2, 3.2), mnear=(1, 2, 2),
         gA=(0, 2.4, 0.4), gB=(0, 1.9, 0.4), leaf=(0, 2.2, 0.6), stars=0.0,
         scenery=['pine', 'pine', 'pine', 'rock', 'tree', 'sign']),
]


def blend_theme(a, b, t):
    out = {'name': a['name'] if t < 0.5 else b['name']}
    out['sky'] = tuple(lerp_rgb(x, y, t) for x, y in zip(a['sky'], b['sky']))
    for k in ('sun', 'mfar', 'mnear', 'gA', 'gB', 'leaf'):
        out[k] = lerp_rgb(a[k], b[k], t)
    out['stars'] = lerp(a['stars'], b['stars'], t)
    return out


def theme_at(pos):
    zi = int(pos // ZONE_LEN)
    frac = (pos % ZONE_LEN) / ZONE_LEN
    a = THEMES[zi % len(THEMES)]
    b = THEMES[(zi + 1) % len(THEMES)]
    t = clamp((frac - 0.80) / 0.20, 0.0, 1.0)
    t = t * t * (3 - 2 * t)
    if t <= 0:
        return a, zi
    return blend_theme(a, b, t), zi


def curve_at(p):
    ramp = clamp(p / 250.0, 0.0, 1.0)
    return ramp * (math.sin(p * 0.0031) * 1.1 +
                   math.sin(p * 0.0087 + 1.7) * 0.8 +
                   math.sin(p * 0.0213 + 0.4) * 0.45)


def build_scenery():
    rng = random.Random(7)
    objs = []
    z = 14.0
    while z < TRACK_LEN + 120:
        zone = int(z // ZONE_LEN) % len(THEMES)
        kinds = THEMES[zone]['scenery']

        def place(zz, side):
            kind = rng.choice(kinds)
            if kind in ('lamp', 'sign'):
                lat = side * rng.uniform(1.25, 1.6)
            elif kind == 'bill':
                lat = side * rng.uniform(1.9, 2.6)
            else:
                lat = side * rng.uniform(1.4, 4.2)
            objs.append((zz, lat, kind, rng.randint(0, 4)))

        side = rng.choice((-1, 1))
        place(z, side)
        if rng.random() < 0.55:
            place(z + rng.uniform(0, 2), -side)
        z += rng.uniform(3.0, 8.0)
    objs.sort()
    return objs


SCENERY = build_scenery()
SCEN_Z = [o[0] for o in SCENERY]


def build_pickups():
    rng = random.Random(11)
    out = []
    z = 320.0
    while z < TRACK_LEN - 150:
        out.append({'z': z, 'lat': rng.uniform(-0.7, 0.7),
                    'kind': rng.choice(('hp', 'nitro', 'hp')), 'taken': False})
        z += rng.uniform(380, 560)
    return out


# --------------------------------------------------------------------------
#  big title font
# --------------------------------------------------------------------------
FONT_SRC = r"""
@R
 ____  
|  _ \ 
| |_) |
|  _ < 
|_| \_\
@O
  ___  
 / _ \ 
| | | |
| |_| |
 \___/ 
@A
    _    
   / \   
  / _ \  
 / ___ \ 
/_/   \_\
@D
 ____  
|  _ \ 
| | | |
| |_| |
|____/ 
@B
 ____  
| __ ) 
|  _ \ 
| |_) |
|____/ 
@W
__        __
\ \      / /
 \ \ /\ / / 
  \ V  V /  
   \_/\_/   
@L
 _     
| |    
| |    
| |___ 
|_____|
@G
  ____ 
 / ___|
| |  _ 
| |_| |
 \____|
@1
 _ 
/ |
| |
| |
|_|
@2
 ____  
|___ \ 
  __) |
 / __/ 
|_____|
@3
 _____ 
|___ / 
  |_ \ 
 ___) |
|____/ 
"""


def load_font():
    glyphs, cur = {}, None
    for line in FONT_SRC.split("\n"):
        if line.startswith("@"):
            cur = line[1]
            glyphs[cur] = []
        elif cur is not None and line != "":
            glyphs[cur].append(line)
    return glyphs


GLYPHS = load_font()


def big_text(word):
    rows = [""] * 5
    for chv in word:
        g = GLYPHS[chv]
        w = max(len(r) for r in g)
        for j in range(5):
            rows[j] += g[j].ljust(w) + " "
    return rows


# --------------------------------------------------------------------------
#  PIXEL ART
#  Every sprite is a tuple of equal-length strings; '.' is transparent and
#  every other character is looked up in a palette.  Two pixels stack in one
#  terminal cell using the half-block glyphs.
# --------------------------------------------------------------------------
def mk(w, h):
    return [['.'] * w for _ in range(h)]


def rect(g, x0, y0, x1, y1, c):
    for y in range(max(0, y0), min(len(g), y1 + 1)):
        for x in range(max(0, x0), min(len(g[0]), x1 + 1)):
            g[y][x] = c


def fin(g):
    return tuple(''.join(r) for r in g)


# ---- the motorcycle + rider, seen from behind (20 x 24 pixels) -----------
#  h helmet  S helmet stripe  k dark  g grey  G chrome  r/R/L jacket
#  y gloves  n trousers  w white (exhaust tips)
BIKE_ROWS = [
    ".......hhhhhh.......",
    "......hhhhhhhh......",
    "......hhhSShhh......",
    "......hhhSShhh......",
    ".......hhhhhh.......",
    "........kkkk........",
    ".....rrrrrrrrrr.....",
    "....rrrrLLLLrrrr....",
    "...rrrrrrLLrrrrrr...",
    "..rrrr.rrrrrr.rrrr..",
    ".rrrR..rrrrrr..Rrrr.",
    ".kyyk..rrrrrr..kyyk.",
    ".GGGGGGGRrrRGGGGGGG.",
    "....nnnnnnnnnnnn....",
    "...nnnnnkkkknnnnn...",
    "...nnnn.kkkk.nnnn...",
    "...kkkn.RRRR.nkkk...",
    "...kkk.gRRRRg.kkk...",
    "..GwG..gkkkkg..GwG..",
    "...GG..gkggkg..GG...",
    ".......kggggk.......",
    ".......kgkkgk.......",
    ".......kggggk.......",
    ".......kkkkkk.......",
]
BIKE_ROWS = [r.ljust(20, '.')[:20] for r in BIKE_ROWS]
BW, BH = 20, 24
CW, CH, OX = 46, 24, 13          # canvas used for animation (arms can reach out)

# a small far-away version of the same biker (10 x 12)
MINI_ROWS = [
    "...hhhh...",
    "...hSSh...",
    "..rrrrrr..",
    ".rrLLLLrr.",
    ".rrrrrrrr.",
    "yGGGGGGGGy",
    "..nnnnnn..",
    "..nkkkkn..",
    "...kRRk...",
    "...kggk...",
    "...kggk...",
    "...kkkk...",
]

_FRAMES = {}


def build_frame(lean, kind, side, ext, wheel, flame):
    """Return the 46x24 canvas for the biker, as a tuple of strings.
       lean   -1..1 (rider leans left/right, in thirds)
       kind   None | 'punch' | 'kick'      side -1 / +1
       ext    limb extension  (-0.3 wind-up ... 1.0 fully extended)"""
    lq = int(round(clamp(lean, -1.0, 1.0) * 3))
    eq = int(round(ext * 8)) if kind else 0
    key = (lq, kind, side, eq, wheel, flame)
    fr = _FRAMES.get(key)
    if fr is not None:
        return fr
    base = [list(r) for r in BIKE_ROWS]
    # tyre tread animation
    tread = (("kggggk", "kgkkgk", "kggggk") if wheel == 0 else
             ("kgkkgk", "kggggk", "kgkkgk"))
    for i, t in enumerate(tread):
        for j, c in enumerate(t):
            base[20 + i][7 + j] = c
    # the attacking limb leaves the bike
    if kind == 'punch':
        xs = range(0, 6) if side < 0 else range(14, 20)
        for y in (9, 10, 11):
            for x in xs:
                base[y][x] = '.'
    elif kind == 'kick':
        xs = range(2, 7) if side < 0 else range(13, 18)
        for y in (15, 16, 17, 18, 19):
            for x in xs:
                if base[y][x] in 'knGwg' and not (6 < x < 13):
                    base[y][x] = '.'
    g = mk(CW, CH)

    def sh(y):                              # lean skew (more at the top)
        return int(round(lq / 3.0 * (CH - 1 - y) / (CH - 1) * 3))

    for y in range(CH):
        s = sh(y)
        for x in range(BW):
            c = base[y][x]
            if c != '.':
                xx = OX + x + s
                if 0 <= xx < CW:
                    g[y][xx] = c
    if flame:
        f = 1 if wheel else 0
        for cx in (OX + 3, OX + 16):
            for i in range(3 + f):
                yy = 20 + i
                if yy < CH and g[yy][cx] == '.':
                    g[yy][cx] = 'F' if i < 2 else 'f'
                    if g[yy][cx + 1] == '.':
                        g[yy][cx + 1] = 'f' if i == 0 else '.'
    if kind == 'punch':
        s0 = sh(8)
        sx = OX + (3 if side < 0 else 16) + s0
        sy = 7
        if ext < 0:                         # wind-up: elbow back, fist up
            rect(g, sx if side > 0 else sx - 1, sy, sx + (1 if side > 0 else 0), sy + 2, 'r')
            fx = sx + side * 2
            rect(g, min(fx, fx + side), sy - 3, max(fx, fx + side), sy - 1, 'y')
        else:
            L = int(2 + 12 * ext)
            for i in range(L):
                x = sx + side * i
                if 0 <= x < CW:
                    g[sy][x] = 'L' if i < 2 else 'r'
                    g[sy + 1][x] = 'R'
            fx = sx + side * L
            rect(g, min(fx, fx + side * 2), sy - 1, max(fx, fx + side * 2), sy + 2, 'y')
            if 0 <= fx + side * 2 < CW:
                g[sy + 1][fx + side * 2] = 'k'
    elif kind == 'kick':
        s0 = sh(14)
        hx = OX + (4 if side < 0 else 15) + s0
        hy = 14
        if ext < 0:                         # wind-up: knee up
            rect(g, hx + side, hy - 2, hx + side * 2, hy + 1, 'n')
            rect(g, hx + side, hy - 3, hx + side * 3, hy - 2, 'k')
        else:
            L = int(3 + 13 * ext)
            for i in range(L):
                x = hx + side * i
                yy = hy - int(i * 0.28)
                for dy in (0, 1):
                    if 0 <= x < CW and 0 <= yy + dy < CH:
                        g[yy + dy][x] = 'n'
            for i in range(L - 3, L + 2):
                x = hx + side * i
                yy = hy - int(i * 0.28)
                for dy in (-1, 0, 1, 2):
                    if 0 <= x < CW and 0 <= yy + dy < CH:
                        g[yy + dy][x] = 'k'
            x = hx + side * (L + 2)
            yy = hy - int((L + 2) * 0.28)
            for dy in (-1, 0, 1, 2):
                if 0 <= x < CW and 0 <= yy + dy < CH:
                    g[yy + dy][x] = 'w'
    fr = fin(g)
    _FRAMES[key] = fr
    return fr


_ROT = {}


def rotate_grid(grid, ang, N=34):
    key = (id(grid), int(ang * 6) % 38, N)
    if key in _ROT:
        return _ROT[key]
    h, w = len(grid), len(grid[0])
    c, s = math.cos(ang), math.sin(ang)
    out = []
    for y in range(N):
        row = []
        for x in range(N):
            dx, dy = x - N / 2.0 + 0.5, y - N / 2.0 + 0.5
            sx = int(dx * c + dy * s + w / 2.0)
            sy = int(-dx * s + dy * c + h / 2.0)
            row.append(grid[sy][sx] if 0 <= sx < w and 0 <= sy < h else '.')
        out.append(''.join(row))
    res = tuple(out)
    if len(_ROT) > 400:
        _ROT.clear()
    _ROT[key] = res
    return res


_BPAL = {}


def biker_pal(jacket, helmet, flash):
    key = (jacket, helmet, flash)
    p = _BPAL.get(key)
    if p is None:
        j = (5, 5, 5) if flash else jacket
        raw = {'r': j, 'R': lerp_rgb(j, (0, 0, 0), 0.5), 'L': lerp_rgb(j, (5, 5, 5), 0.4),
               'S': jacket, 'h': (5, 5, 5) if flash else helmet,
               'w': G(5), 'k': G(0.5), 'g': G(1.7), 'G': G(3.4),
               'y': (4.8, 3.6, 1.0), 'n': (0.6, 0.7, 1.7),
               'F': (5, 2, 0), 'f': (5, 4.6, 1.0)}
        p = {k: ci(v) for k, v in raw.items()}
        _BPAL[key] = p
    return p


# ---- scenery sprites ------------------------------------------------------
def gen_tree():
    rows = [
        "....dLLLLd....",
        "..dLLLLLLLLd..",
        ".dLLLlLLLLLLd.",
        ".dLLLLLLlLLLd.",
        "dLLlLLLLLLLLLd",
        "dLLLLLLLLlLLLd",
        ".dLLLlLLLLLLd.",
        ".dddLLLLLLddd.",
        "..ddddLLdddd..",
        "....dddddd....",
        "......tT......",
        "......tT......",
        "......tT......",
        ".....ttTT.....",
    ]
    return tuple(r.ljust(14, '.')[:14] for r in rows)


def gen_pine():
    w, h = 17, 21
    g = mk(w, h)
    cx = (w - 1) / 2.0
    for i, (hmin, hmax) in enumerate(((1, 4), (2, 6), (3, 8))):
        for r in range(7):
            yy = i * 5 + r
            half = hmin + (hmax - hmin) * r / 6.0
            for x in range(w):
                dx = x - cx
                if abs(dx) <= half:
                    c = 'L'
                    if dx < -half * 0.35:
                        c = 'l'
                    elif dx > half * 0.35:
                        c = 'd'
                    if r == 6:
                        c = 'd'
                    g[yy][x] = c
    rect(g, 7, 17, 9, 20, 't')
    rect(g, 9, 17, 9, 20, 'T')
    return fin(g)


def gen_cactus():
    g = mk(13, 22)
    rect(g, 5, 1, 7, 21, 'C')
    rect(g, 5, 1, 5, 21, 'c')
    rect(g, 7, 1, 7, 21, 'D')
    rect(g, 6, 0, 6, 0, 'C')
    rect(g, 1, 6, 2, 12, 'C')
    rect(g, 1, 6, 1, 12, 'c')
    rect(g, 2, 11, 5, 12, 'C')
    rect(g, 10, 8, 11, 15, 'C')
    rect(g, 11, 8, 11, 15, 'D')
    rect(g, 7, 14, 10, 15, 'C')
    return fin(g)


def gen_rock():
    w, h = 16, 9
    g = mk(w, h)
    for y in range(h):
        for x in range(w):
            dx = (x - 7.5) / 8.0
            dy = (y - 8.2) / 8.6
            if dx * dx + dy * dy <= 1.0:
                s = dx * 0.7 - dy * 0.7
                g[y][x] = 'z' if s > 0.35 else 'A' if s < -0.3 else 'a'
    return fin(g)


def gen_lamp():
    g = mk(10, 28)
    rect(g, 4, 5, 5, 27, 'p')
    rect(g, 5, 5, 5, 27, 'P')
    rect(g, 4, 1, 8, 2, 'p')
    rect(g, 6, 3, 9, 4, 'Y')
    rect(g, 5, 5, 9, 5, 'y')
    return fin(g)


def gen_sign(rev):
    g = mk(14, 20)
    rect(g, 6, 10, 7, 19, 'p')
    rect(g, 0, 0, 13, 9, 'w')
    rect(g, 1, 1, 12, 8, 'k')
    for y in range(2, 8):
        x = 4 + min(y - 2, 7 - y)
        rect(g, x, y, x + 1, y, 'o')
        rect(g, x + 3, y, x + 4, y, 'o')
    if rev:
        g = [list(reversed(r)) for r in g]
    return fin(g)


def gen_bill(v):
    w, h = 24, 22
    g = mk(w, h)
    rect(g, 5, 12, 6, 21, 'p')
    rect(g, 17, 12, 18, 21, 'p')
    rect(g, 0, 0, 23, 11, 'w')
    fillc = 'mqo'[v % 3]
    rect(g, 1, 1, 22, 10, fillc)
    for y in range(1, 11):
        for x in range(1, 23):
            if v % 3 == 0 and (x + y) % 6 < 2:
                g[y][x] = 'w'
            elif v % 3 == 1 and (x // 3) % 2 == 0 and 3 < y < 8:
                g[y][x] = 'k'
            elif v % 3 == 2 and 4 < x < 19 and y in (4, 5, 7, 8) and (x % 4 != 0):
                g[y][x] = 'k'
    return fin(g)


def gen_pick(kind):
    if kind == 'hp':
        g = mk(12, 9)
        rect(g, 0, 0, 11, 8, 'p')
        rect(g, 1, 1, 10, 7, 'w')
        rect(g, 5, 1, 6, 7, 'x')
        rect(g, 3, 3, 8, 4, 'x')
    else:
        g = mk(8, 12)
        rect(g, 2, 0, 5, 1, 'p')
        rect(g, 0, 2, 7, 11, 'q')
        rect(g, 0, 2, 0, 11, 'p')
        rect(g, 7, 2, 7, 11, 'p')
        rect(g, 1, 5, 6, 7, 'w')
        rect(g, 3, 4, 4, 8, 'o')
    return fin(g)


SPR = {
    'tree': gen_tree(), 'pine': gen_pine(), 'cactus': gen_cactus(),
    'rock': gen_rock(), 'lamp': gen_lamp(),
    'sign_r': gen_sign(False), 'sign_l': gen_sign(True),
    'bill0': gen_bill(0), 'bill1': gen_bill(1), 'bill2': gen_bill(2),
    'hp': gen_pick('hp'), 'nitro': gen_pick('nitro'),
}
# how wide each object is compared to the road's half width
KSIZE = {'tree': 0.55, 'pine': 0.48, 'cactus': 0.30, 'rock': 0.40, 'lamp': 0.13,
         'sign': 0.22, 'bill': 0.80, 'hp': 0.26, 'nitro': 0.18}


def scenery_pal(th):
    leaf = th['leaf']
    raw = {'L': leaf, 'l': lerp_rgb(leaf, (5, 5, 5), 0.3), 'd': lerp_rgb(leaf, (0, 0, 0), 0.5),
           't': (2.2, 1.2, 0.3), 'T': (1.4, 0.7, 0.2),
           'C': (0.6, 3.0, 1.0), 'c': (1.6, 4, 1.8), 'D': (0.2, 1.8, 0.6),
           'a': G(2.2), 'A': G(3.4), 'z': G(1.2),
           'p': G(2.6), 'P': G(1.4), 'Y': (5, 4.6, 1.5), 'y': (3.5, 3, 0.6),
           'w': G(5), 'k': G(0.4), 'o': (5, 3, 0.2), 'm': (4.4, 0.6, 3.4),
           'q': (0.4, 3.6, 5), 'x': (4.6, 0.5, 0.5)}
    return {k: ci(v) for k, v in raw.items()}


# --------------------------------------------------------------------------
#  screen buffer
# --------------------------------------------------------------------------
class Buf:
    def __init__(self, W, H):
        self.W, self.H = W, H
        self.ch = [[' '] * W for _ in range(H)]
        self.fg = [[7] * W for _ in range(H)]
        self.bg = [[0] * W for _ in range(H)]

    def span(self, y, x0, x1, bg=None, fg=None, ch=None):
        if y < 0 or y >= self.H:
            return
        x0 = max(0, x0)
        x1 = min(self.W, x1)
        if x1 <= x0:
            return
        n = x1 - x0
        if bg is not None:
            self.bg[y][x0:x1] = [bg] * n
        if fg is not None:
            self.fg[y][x0:x1] = [fg] * n
        if ch is not None:
            self.ch[y][x0:x1] = [ch] * n

    def put(self, x, y, c, fg=None, bg=None):
        if 0 <= y < self.H and 0 <= x < self.W:
            self.ch[y][x] = c
            if fg is not None:
                self.fg[y][x] = fg
            if bg is not None:
                self.bg[y][x] = bg

    def text(self, x, y, txt, fg=None, bg=None):
        for i, c in enumerate(txt):
            self.put(x + i, y, c, fg, bg)

    def blit_px(self, grid, pal, cx, ybot, scale):
        """draw a pixel sprite, scaled, bottom-centred on cell (cx, ybot)"""
        h, w = len(grid), len(grid[0])
        tw = int(round(w * scale))
        thp = int(round(h * scale))
        if tw < 1 or thp < 1:
            return
        if thp & 1:
            thp += 1
        cells = thp >> 1
        x0 = cx - tw // 2
        H, W = self.H, self.W
        xs = [min(w - 1, int((tx + 0.5) * w / tw)) for tx in range(tw)]
        pget = pal.get
        for cy in range(cells):
            y = ybot - (cells - 1 - cy)
            if y < 0 or y >= H:
                continue
            rt = grid[min(h - 1, int((2 * cy + 0.5) * h / thp))]
            rb = grid[min(h - 1, int((2 * cy + 1.5) * h / thp))]
            chy, fgy, bgy = self.ch[y], self.fg[y], self.bg[y]
            for tx in range(tw):
                x = x0 + tx
                if x < 0 or x >= W:
                    continue
                sx = xs[tx]
                t = pget(rt[sx])
                b = pget(rb[sx])
                if t is not None:
                    chy[x] = '\u2580'
                    fgy[x] = t
                    if b is not None:
                        bgy[x] = b
                elif b is not None:
                    chy[x] = '\u2584'
                    fgy[x] = b
        return cells

    def flush(self, scr):
        if len(_PAIRS) > max(0, curses.COLOR_PAIRS - 300):
            _PAIRS.clear()
        for y in range(self.H):
            rc, rf, rb = self.ch[y], self.fg[y], self.bg[y]
            x = 0
            W = self.W
            while x < W:
                f, b = rf[x], rb[x]
                x2 = x + 1
                while x2 < W and rf[x2] == f and rb[x2] == b:
                    x2 += 1
                try:
                    scr.addstr(y, x, ''.join(rc[x:x2]), pair(f, b))
                except curses.error:
                    pass
                x = x2


# --------------------------------------------------------------------------
#  rivals
# --------------------------------------------------------------------------
JACKETS = [(0.6, 1.6, 5), (0.4, 3.6, 1.2), (5, 4, 0.4), (3.4, 1, 5),
           (5, 2.4, 0.3), (0.2, 4, 4.4), (5, 1.2, 3), (1.2, 1.2, 1.6)]
HELMETS = [(5, 5, 5), (5, 4.2, 0.6), (4, 5, 5), (5, 1.5, 1.5), (3.5, 5, 1.5), (1.2, 1.2, 1.5)]
PLAYER_JACKET = (4.8, 0.4, 0.4)
PLAYER_HELMET = (5, 5, 5)
HIT_WORDS = ["POW!", "WHAM!", "BAM!", "CRACK!", "THUD!"]
ATK_WIND = 0.45
ATK_RECOVER = 0.25


class Rival:
    def __init__(self, idx, rng):
        self.rng = rng
        self.idx = idx
        self.jacket = JACKETS[idx % len(JACKETS)]
        self.helmet = rng.choice(HELMETS)
        self.base = rng.uniform(27, 38)
        self.dmg = rng.choice((6, 7, 8, 10))
        self.aggr = rng.uniform(0.35, 1.0)
        self.side = rng.choice((-1, 1))
        self.reset(0.0, 0.0)

    def reset(self, z, x):
        self.z = z
        self.x = x
        self.want = x
        self.speed = 0.0
        self.hp = 3
        self.state = 'ride'
        self.crash_t = 0.0
        self.atk = 0.0
        self.atk_side = 0
        self.atk_kind = 'punch'
        self.recover = 0.0
        self.ext = 0.0
        self.hit_t = 0.0
        self.recoil = 0.0
        self.fx_t = 0.0
        self.fx_txt = "POW!"
        self.atk_cd = self.rng.uniform(0.5, 1.8)
        self.lane_t = 0.0
        self.stun = 0.0


# --------------------------------------------------------------------------
#  the game
# --------------------------------------------------------------------------
class Game:
    def __init__(self, scr):
        self.scr = scr
        self.rng = random.Random()
        H, W = scr.getmaxyx()
        self.W, self.H = W, H
        self.buf = Buf(W, H)
        self.t = 0.0
        self.frame = 0
        self.state = 'title'
        self.bgoff = 0.0
        self.stars = [(self.rng.random(), self.rng.random(),
                       self.rng.randint(0, 4)) for _ in range(90)]
        self.clouds = [(self.rng.random(), self.rng.random(),
                        self.rng.randint(10, 22)) for _ in range(5)]
        self.pos = 0.0
        self.speed = 20.0
        self.px = 0.0
        self.rivals = []
        self.pickups = []
        self.dead = set()
        self.msg = None
        self.best = None
        self.lean = 0.0
        self.demo_t = 1.5
        self.reset_player()

    def reset_player(self):
        self.vx = 0.0
        self.health = 100.0
        self.nitro = 100.0
        self.boost = False
        self.score = 0.0
        self.race_t = 0.0
        self.brake_until = 0.0
        self.atk_t = 0.0
        self.atk_len = 0.3
        self.atk_kind = 'punch'
        self.atk_side = 1
        self.atk_cd = 0.0
        self.hit_pending = 0.0
        self.hurt_t = 0.0
        self.crash_t = 0.0
        self.cd = 0.0
        self.zone_seen = -1
        self.result = None

    def new_race(self):
        self.reset_player()
        self.pos = 0.0
        self.speed = 0.0
        self.px = 0.0
        self.dead = set()
        self.pickups = build_pickups()
        slots = [10, 22, 35, 48, 62, 78, 95, 115]
        lanes = [-0.7, -0.25, 0.25, 0.7]
        self.rivals = []
        for i in range(N_RIVALS):
            r = Rival(i, self.rng)
            r.reset(slots[i] + self.rng.uniform(-2, 2),
                    lanes[i % 4] + self.rng.uniform(-0.1, 0.1))
            self.rivals.append(r)
        self.state = 'countdown'
        self.cd = 3.6
        self.msg = None

    def say(self, text, color=(5, 5, 1), ttl=1.2):
        self.msg = [text, color, ttl]

    # ------------------------------------------------------------ input ----
    def read_keys(self):
        out = []
        while True:
            k = self.scr.getch()
            if k == -1:
                break
            if k == curses.KEY_LEFT:
                out.append('left')
            elif k == curses.KEY_RIGHT:
                out.append('right')
            elif k == curses.KEY_DOWN:
                out.append('down')
            elif k == curses.KEY_UP:
                out.append('up')
            elif k in (10, 13, curses.KEY_ENTER):
                out.append('enter')
            elif k == 32:
                out.append('space')
            elif 0 <= k < 256:
                out.append(chr(k).lower())
        return out

    def run(self):
        last = time.time()
        while True:
            now = time.time()
            dt = min(0.05, now - last)
            last = now
            self.t += dt
            self.frame += 1
            keys = self.read_keys()
            if self.step(dt, keys) == 'quit':
                break
            self.render()
            sleep = 1.0 / FPS - (time.time() - now)
            if sleep > 0:
                time.sleep(sleep)

    def step(self, dt, keys):
        s = self.state
        self.atk_t = max(0.0, self.atk_t - dt)
        self.lean += (clamp(self.vx / 2.2, -1, 1) - self.lean) * min(1.0, dt * 9)
        if s == 'title':
            if 'q' in keys:
                return 'quit'
            if 'enter' in keys or 'space' in keys:
                self.new_race()
                return None
            self.speed = 22.0
            self.pos += self.speed * dt
            if self.pos > 5400:
                self.pos = 0.0
            self.bgoff += curve_at(self.pos) * self.speed * dt * 0.6
            self.px = 0.35 * math.sin(self.t * 0.7)
            self.vx = 1.3 * math.cos(self.t * 0.7)
            self.demo_t -= dt
            if self.demo_t <= 0:                      # showcase the animations
                self.demo_t = 2.2
                kind = 'kick' if self.rng.random() < 0.4 else 'punch'
                self.start_attack(kind, self.rng.choice((-1, 1)))
        elif s == 'countdown':
            if 'q' in keys:
                return 'quit'
            self.cd -= dt
            if self.cd <= 0:
                self.state = 'race'
                self.say(">> GO! <<", (1, 5, 1), 1.0)
        elif s == 'race':
            if 'q' in keys:
                return 'quit'
            if 'p' in keys:
                self.state = 'pause'
                return None
            self.update_race(dt, keys)
        elif s == 'pause':
            if 'q' in keys:
                return 'quit'
            if 'p' in keys:
                self.state = 'race'
        elif s in ('finish', 'over'):
            self.speed = max(0.0, self.speed - 20 * dt)
            self.pos += self.speed * dt * (1 if s == 'over' else 0.3)
            for r in self.rivals:
                self.tick_rival_fx(r, dt)
            if 'q' in keys:
                return 'quit'
            if 'r' in keys or 'enter' in keys:
                self.new_race()
        if self.msg:
            self.msg[2] -= dt
            if self.msg[2] <= 0:
                self.msg = None
        return None

    # --------------------------------------------------------- gameplay ----
    def start_attack(self, kind, side):
        if self.atk_cd > 0 or self.crash_t > 0:
            return False
        self.atk_kind = kind
        self.atk_side = side
        if kind == 'punch':
            self.atk_len, self.atk_cd = 0.32, 0.40
        else:
            self.atk_len, self.atk_cd = 0.50, 0.75
        self.atk_t = self.atk_len
        self.hit_pending = self.atk_len * 0.58
        return True

    def resolve_attack(self):
        side, kind = self.atk_side, self.atk_kind
        reach = 1.5 if kind == 'punch' else 1.9
        zr = 2.6 if kind == 'punch' else 3.1
        best = None
        for r in self.rivals:
            if r.state != 'ride':
                continue
            d = r.z - self.pos
            gap = (r.x - self.px) * side
            if abs(d) < zr and 0.05 < gap < reach:
                if best is None or gap < best[0]:
                    best = (gap, r)
        if best:
            self.hit_rival(best[1], side, 1 if kind == 'punch' else 2)

    def update_race(self, dt, keys):
        now = self.t
        self.race_t += dt
        for k in keys:
            if k in ('left', 'a'):
                self.vx -= 1.25
            elif k in ('right', 'd'):
                self.vx += 1.25
            elif k in ('down', 's'):
                self.brake_until = now + 0.25
            elif k == 'space':
                if self.boost:
                    self.boost = False
                elif self.nitro > 8:
                    self.boost = True
                    self.say("NITRO!", (0, 5, 5), 0.7)
            elif k in ('z', ','):
                self.start_attack('punch', -1)
            elif k in ('x', '.'):
                self.start_attack('punch', 1)
            elif k == 'c':
                self.start_attack('kick', -1)
            elif k == 'v':
                self.start_attack('kick', 1)
        self.vx = clamp(self.vx, -2.2, 2.2)

        crash = self.crash_t > 0
        on_road = abs(self.px) <= 1.02
        cap = MAX_SPEED if on_road else MAX_SPEED * 0.6
        acc = 15.0
        if self.boost and not crash:
            cap = BOOST_SPEED if on_road else cap * 1.2
            acc = 34.0
            self.nitro -= 32 * dt
            if self.nitro <= 0:
                self.nitro = 0
                self.boost = False
        else:
            self.nitro = min(100.0, self.nitro + 4 * dt)
        if crash:
            self.speed = max(0.0, self.speed - 55 * dt)
        elif now < self.brake_until:
            self.speed = max(0.0, self.speed - 45 * dt)
        elif self.speed < cap:
            self.speed = min(cap, self.speed + acc * dt * (1.25 - self.speed / (BOOST_SPEED + 6)))
        else:
            self.speed = max(cap, self.speed - 22 * dt)

        sf = 0.35 + self.speed / 38.0
        self.px += self.vx * dt * sf
        self.px -= curve_at(self.pos) * self.speed * dt * 0.02
        self.vx *= math.exp(-5 * dt)
        self.px = clamp(self.px, -3.4, 3.4)
        self.pos += self.speed * dt
        self.bgoff += curve_at(self.pos) * self.speed * dt * 0.6
        self.score += self.speed * dt * 0.4

        self.atk_cd = max(0.0, self.atk_cd - dt)
        self.hurt_t = max(0.0, self.hurt_t - dt)
        if self.hit_pending > 0:
            self.hit_pending -= dt
            if self.hit_pending <= 0:
                self.resolve_attack()
        if self.crash_t > 0:
            self.crash_t -= dt
            if self.crash_t <= 0:
                if abs(self.px) > 1.0:
                    self.px = 0.85 * (1 if self.px > 0 else -1)
                self.vx = 0.0

        zi = int(self.pos // ZONE_LEN)
        if zi != self.zone_seen and zi < len(THEMES):
            self.zone_seen = zi
            self.say(">> %s <<" % THEMES[zi]['name'], (5, 5, 2), 2.2)

        if self.crash_t <= 0:
            i0 = bisect.bisect_left(SCEN_Z, self.pos - 0.4)
            i1 = bisect.bisect_right(SCEN_Z, self.pos + 1.4)
            for i in range(i0, i1):
                if i in self.dead:
                    continue
                if abs(SCENERY[i][1] - self.px) < 0.32:
                    self.dead.add(i)
                    self.do_crash()
                    break

        for p in self.pickups:
            if p['taken']:
                continue
            if abs(p['z'] - self.pos) < 1.4 and abs(p['lat'] - self.px) < 0.45:
                p['taken'] = True
                if p['kind'] == 'hp':
                    self.health = min(100.0, self.health + 25)
                    self.say("REPAIR KIT  +25 HP", (1, 5, 1), 1.3)
                else:
                    self.nitro = min(100.0, self.nitro + 60)
                    self.say("NITRO CANISTER  +60", (0, 5, 5), 1.3)

        for r in self.rivals:
            self.update_rival(r, dt)
        for i, a in enumerate(self.rivals):
            for b in self.rivals[i + 1:]:
                if abs(a.z - b.z) < 1.6 and abs(a.x - b.x) < 0.3:
                    s = 1 if a.x >= b.x else -1
                    a.x += s * 0.02
                    b.x -= s * 0.02

        if self.health <= 0:
            self.health = 0
            self.state = 'over'
            self.speed = max(self.speed, 10.0)
        elif self.pos >= TRACK_LEN:
            self.finish()

    def do_crash(self):
        self.crash_t = 1.3
        self.health -= 12
        self.speed *= 0.5
        self.boost = False
        self.atk_t = 0.0
        self.hit_pending = 0.0
        self.say("CRASH!  -12 HP", (5, 1, 0), 1.2)

    def hurt(self, dmg, attacker_gap):
        self.health -= dmg
        self.hurt_t = 0.4
        self.vx += (-1 if attacker_gap >= 0 else 1) * 1.6
        self.say("OUCH!  -%d HP" % dmg, (5, 1, 0), 0.8)

    def hit_rival(self, r, side, dmg):
        r.hp -= dmg
        r.x += side * (0.45 if dmg == 1 else 0.7)
        r.stun = 0.5 if dmg == 1 else 0.9
        r.atk = 0
        r.recover = 0
        r.hit_t = 0.2
        r.recoil = side * 1.0
        r.fx_t = 0.4
        r.fx_txt = self.rng.choice(HIT_WORDS)
        r.speed *= 0.8
        self.score += 50 * dmg
        if r.hp <= 0:
            r.state = 'crash'
            r.crash_t = 2.6
            self.score += 300
            self.say("TAKEN DOWN!  +300", (5, 4, 0), 1.3)
        else:
            self.say("%s  +%d" % (r.fx_txt, 50 * dmg), (5, 5, 1), 0.6)

    def tick_rival_fx(self, r, dt):
        r.hit_t = max(0.0, r.hit_t - dt)
        r.fx_t = max(0.0, r.fx_t - dt)
        r.recoil *= math.exp(-8 * dt)

    def update_rival(self, r, dt):
        d = r.z - self.pos
        self.tick_rival_fx(r, dt)
        if r.state == 'crash':
            r.speed *= math.exp(-2.2 * dt)
            r.z += r.speed * dt
            r.crash_t -= dt
            if r.crash_t <= 0:
                r.state = 'ride'
                r.hp = 3
                r.speed = r.base * 0.5
                r.x = clamp(r.x, -0.8, 0.8)
            return
        tgt = r.base
        if d > 110:
            tgt *= 0.8
        elif d > 60:
            tgt *= 0.92
        elif d < -30:
            tgt *= 1.18
        if r.stun > 0:
            r.stun -= dt
            tgt *= 0.5
        r.speed += (tgt - r.speed) * min(1.0, dt * 1.2)
        r.z += r.speed * dt

        r.lane_t -= dt
        if abs(d) < 8 and r.aggr > 0.5 and self.crash_t <= 0:
            r.want = clamp(self.px + r.side * 0.55, -0.95, 0.95)
        elif r.lane_t <= 0:
            r.want = self.rng.uniform(-0.85, 0.85)
            r.lane_t = self.rng.uniform(1.5, 3.5)
        r.x += clamp(r.want - r.x, -0.8 * dt, 0.8 * dt)

        gap = r.x - self.px
        if abs(d) < 1.3 and abs(gap) < 0.28 and self.crash_t <= 0:
            s = 1 if gap >= 0 else -1
            r.x += s * 0.2
            self.px -= s * 0.2
            self.speed *= 0.96

        # attack: wind-up -> strike -> recover (all animated via r.ext)
        r.atk_cd -= dt
        if r.atk > 0:
            r.atk -= dt
            ph = 1.0 - max(0.0, r.atk) / ATK_WIND
            r.ext = (-0.3 * ph / 0.7) if ph < 0.7 else lerp(-0.3, 1.0, (ph - 0.7) / 0.3)
            if r.atk <= 0:
                g = r.x - self.px
                if abs(r.z - self.pos) < 2.8 and abs(g) < 1.35 and self.crash_t <= 0 and r.stun <= 0:
                    self.hurt(r.dmg, g)
                r.atk_cd = self.rng.uniform(1.3, 2.4)
                r.recover = ATK_RECOVER
        elif r.recover > 0:
            r.recover -= dt
            r.ext = clamp(r.recover / ATK_RECOVER, 0.0, 1.0)
        else:
            r.ext = 0.0
            if (r.atk_cd <= 0 and r.stun <= 0 and abs(d) < 2.2 and
                    0.15 < abs(gap) < 1.0 and self.crash_t <= 0 and
                    self.rng.random() < r.aggr * dt * 4):
                r.atk = ATK_WIND
                r.atk_side = -1 if gap > 0 else 1
                r.atk_kind = 'kick' if self.rng.random() < 0.3 else 'punch'

    def rank(self):
        return 1 + sum(1 for r in self.rivals if r.z > self.pos)

    def finish(self):
        rank = self.rank()
        bonus = max(0, N_RIVALS + 1 - rank) * 250 + int(self.health) * 5
        total = int(self.score) + bonus
        self.result = dict(rank=rank, bonus=bonus, total=total, time=self.race_t)
        if self.best is None or total > self.best:
            self.best = total
        self.state = 'finish'

    # ----------------------------------------------------------- render ----
    def render(self):
        H, W = self.scr.getmaxyx()
        if (W, H) != (self.W, self.H):
            self.W, self.H = W, H
            try:
                self.scr.erase()
            except curses.error:
                pass
        self.buf = Buf(W, H)
        if W < 72 or H < 24:
            self.buf.text(1, 1, "Terminal too small:", 7)
            self.buf.text(1, 2, "need at least 72x24 (have %dx%d)" % (W, H), 7)
            self.buf.flush(self.scr)
            self.scr.refresh()
            return
        self.render_world()
        if self.state == 'title':
            self.render_title()
        else:
            self.render_hud()
            self.render_overlay()
        self.buf.flush(self.scr)
        self.scr.refresh()

    def render_world(self):
        W, H = self.W, self.H
        buf = self.buf
        horizon = int(H * 0.42)
        rows = H - 2 - horizon
        d0 = DEPTH / rows
        self.horizon, self.rows = horizon, rows
        pos = self.pos
        th, zi = theme_at(pos)
        sky0, sky1, sky2 = th['sky']
        fogc = lerp_rgb(sky2, sky1, 0.25)
        fogi = ci(fogc)
        CH_, FG_, BG_ = buf.ch, buf.fg, buf.bg

        # ---- sky: dithered gradient between 8 palette steps ----
        NS = 8
        steps = []
        for i in range(NS):
            t = i / (NS - 1.0)
            steps.append(ci(lerp_rgb(sky0, sky1, t * 2) if t < 0.5 else lerp_rgb(sky1, sky2, (t - 0.5) * 2)))
        for y in range(horizon):
            v = y / max(1.0, horizon - 1.0) * (NS - 1)
            k = min(NS - 2, int(v))
            f = v - k
            c1, c2 = steps[k], steps[k + 1]
            BG_[y][:] = [c1] * W
            if c1 != c2:
                rch, rfg = CH_[y], FG_[y]
                br = BAYER[y & 3]
                for x in range(W):
                    q = int(f * 4 + (br[x & 3] - 0.5) * 0.9 + 0.5)
                    if q > 0:
                        rch[x] = GLY[4 if q > 4 else q]
                        rfg[x] = c2
        BG_[horizon][:] = [fogi] * W

        # ---- stars / clouds ----
        if th['stars'] > 0.45:
            for fx, fy, ph in self.stars:
                if (self.frame // 7 + ph) % 6 == 0:
                    continue
                buf.put(int(fx * W), int(fy * horizon * 0.75), '*' if ph == 0 else '.', ci(G(5)))
        else:
            cc = ci(G(4.8))
            for fx, fy, ln in self.clouds:
                cy = 2 + int(fy * horizon * 0.35)
                cx0 = int((fx * W * 1.4 - self.bgoff * 0.25 + self.t * 1.5) % (W + 40)) - 20
                for dy in range(-1, 2):
                    for dx in range(-ln // 2, ln // 2 + 1):
                        e = (dx / (ln / 2.0)) ** 2 + (dy / 1.6) ** 2
                        if e < 1.0:
                            lv = int((1 - e) * 4.2)
                            if lv > 0:
                                buf.put(cx0 + dx, cy + dy, GLY[min(3, lv)], cc)

        # ---- sun: dithered disc + halo + retro stripes ----
        ry = max(3, int(horizon * 0.26))
        rx = ry * 2
        sx = int((W * 0.55 - self.bgoff * 0.1) % (W + 40)) - 20
        sy = horizon - int(ry * 0.45)
        sun1 = ci(th['sun'])
        sun2c = ci(lerp_rgb(th['sun'], (5, 0.7, 1.5), 0.65))
        for dy in range(-ry - 1, ry + 2):
            y = sy + dy
            if y < 0 or y >= horizon:
                continue
            rr = math.sqrt(max(0.0, 1 - (dy / float(ry)) ** 2))
            half = int(rx * rr)
            for x in range(sx - half - 3, sx - half):
                buf.put(x, y, GLY[1], sun1)
            for x in range(sx + half + 1, sx + half + 4):
                buf.put(x, y, GLY[1], sun1)
            if dy > ry * 0.15 and (dy + ry) % 3 == 0:
                continue
            f = (dy + ry) / (2.0 * ry)
            for x in range(sx - half, sx + half + 1):
                if 0 <= x < W:
                    q = dq(f, x, y)
                    BG_[y][x] = sun1
                    FG_[y][x] = sun2c
                    CH_[y][x] = GLY[q]

        # ---- mountains: lit/shaded faces, hazy base, soft ridge ----
        hmax = max(3.0, horizon * 0.55)
        for layer in (0, 1):
            base = th['mfar'] if layer == 0 else th['mnear']
            lit = ci(base)
            shd = ci(lerp_rgb(base, (0, 0, 0), 0.38))
            prev = None
            for x in range(W):
                if layer == 0:
                    u = x + self.bgoff * 0.5
                    hf = hmax * (0.45 + 0.28 * math.sin(u * 0.031) + 0.2 * math.sin(u * 0.083 + 2.0)
                                 + 0.1 * math.sin(u * 0.21))
                else:
                    u = x + self.bgoff
                    hf = hmax * 0.62 * (0.4 + 0.3 * math.sin(u * 0.047 + 1.0)
                                        + 0.2 * math.sin(u * 0.13 + 4.0) + 0.1 * math.sin(u * 0.3))
                col = lit if (prev is None or hf >= prev) else shd
                prev = hf
                h = int(hf)
                top = horizon - h
                for yy in range(max(0, top), horizon):
                    BG_[yy][x] = col
                    CH_[yy][x] = ' '
                    depth = (yy - top) / float(max(1, h))
                    if layer == 0 and depth > 0.45:
                        q = dq((depth - 0.45) * 1.1, x, yy)
                        if q:
                            CH_[yy][x] = GLY[q]
                            FG_[yy][x] = fogi
                if hf - h >= 0.5 and top - 1 >= 0:
                    CH_[top - 1][x] = '\u2584'
                    FG_[top - 1][x] = col

        # ---- road geometry ----
        cen = [0.0] * H
        hw = [0.0] * H
        cx = W / 2.0
        dxv = 0.0
        for y in range(H - 2, horizon, -1):
            k = y - horizon
            d = DEPTH / k - d0
            dxv += curve_at(pos + d) * 0.05
            cx += dxv
            w = k / float(rows) * W * 0.42 + 0.8
            cen[y] = cx - self.px * w
            hw[y] = w

        # ---- ground, road, texture and distance fog ----
        for y in range(horizon + 1, H - 1):
            k = y - horizon
            tt = k / float(rows)
            ph = math.sin(26 * (1 - tt) ** 3 + pos * 0.5)
            gcol = th['gA'] if ph > 0 else th['gB']
            buf.span(y, 0, W, bg=ci(gcol), ch=' ')
            l = int(cen[y] - hw[y])
            r = int(cen[y] + hw[y])
            rw = max(1, int(hw[y] * 0.1))
            buf.span(y, l, l + rw, bg=ci((4.6, 0.3, 0.3) if ph > 0 else G(5)))
            buf.span(y, l + rw, r - rw + 1, bg=ci(G(1.15) if ph > 0 else G(0.85)))
            buf.span(y, r - rw + 1, r + 1, bg=ci((4.6, 0.3, 0.3) if ph > 0 else G(5)))
            if tt > 0.3:
                zz = int((pos + DEPTH / k - d0) * 1.5)
                t_hi = ci(lerp_rgb(gcol, (5, 5, 3), 0.25))
                t_lo = ci(lerp_rgb(gcol, (0, 0, 0), 0.35))
                t_rd = ci(G(0.55))
                rch, rfg = CH_[y], FG_[y]
                for x in range(W):
                    h = (zz * 37 + x * 101) % 31
                    if l + rw <= x <= r - rw:
                        if h < 3:
                            rch[x] = GLY[1]
                            rfg[x] = t_rd
                    elif x < l - 1 or x > r + 1:
                        if h < 2:
                            rch[x] = ',' if h == 0 else '"'
                            rfg[x] = t_hi
                        elif h < 5:
                            rch[x] = GLY[1]
                            rfg[x] = t_lo
            if tt > 0.06 and math.sin(40 * (1 - tt) ** 3 + pos * 0.9) > 0.2:
                lw = max(1, int(hw[y] * 0.03))
                lc = ci(G(4.4))
                for off in (-0.333, 0.333):
                    xc = int(cen[y] + off * hw[y])
                    buf.span(y, xc, xc + lw, bg=lc)
            fogf = (1 - tt) ** 2 * 0.8
            if fogf > 0.03:
                rch, rfg = CH_[y], FG_[y]
                br = BAYER[y & 3]
                for x in range(W):
                    q = int(fogf * 4 + (br[x & 3] - 0.5) * 0.9 + 0.5)
                    if q > 0:
                        rch[x] = GLY[4 if q > 4 else q]
                        rfg[x] = fogi

        # ---- collect sprites ----
        objs = []
        lim = DEPTH - d0 - 0.5
        i0 = bisect.bisect_left(SCEN_Z, pos - 0.3)
        i1 = bisect.bisect_right(SCEN_Z, pos + lim)
        for i in range(i0, i1):
            if i not in self.dead:
                objs.append((SCENERY[i][0] - pos, 's', i))
        for p in self.pickups:
            if not p['taken'] and -0.3 < p['z'] - pos < lim:
                objs.append((p['z'] - pos, 'p', p))
        for r in self.rivals:
            if -0.3 < r.z - pos < lim:
                objs.append((r.z - pos, 'r', r))
        dfin = TRACK_LEN - pos
        if -0.3 < dfin < lim:
            objs.append((dfin, 'f', None))
        objs.sort(key=lambda o: -o[0])
        spal = scenery_pal(th)

        for d, kind, obj in objs:
            kf = DEPTH / (d + d0)
            y = horizon + int(round(kf))
            if y <= horizon or y > H - 2:
                continue
            ratio = kf / rows
            if kind == 'f':
                self.draw_finish(y, kf, cen, hw, ratio)
                continue
            if kind == 's':
                z, lat, sk, var = SCENERY[obj]
                cxs = int(cen[y] + lat * hw[y])
                if sk == 'sign':
                    grid = SPR['sign_r' if curve_at(z) >= 0 else 'sign_l']
                elif sk == 'bill':
                    grid = SPR['bill%d' % (var % 3)]
                else:
                    grid = SPR[sk]
                sc = hw[y] * KSIZE[sk] / len(grid[0])
                if sc * len(grid[0]) >= 1.3:
                    buf.blit_px(grid, spal, cxs, y, sc)
            elif kind == 'p':
                cxs = int(cen[y] + obj['lat'] * hw[y])
                grid = SPR[obj['kind']]
                sc = hw[y] * KSIZE[obj['kind']] / len(grid[0])
                if int(self.t * 4) % 2 == 0 or sc * len(grid[0]) < 3:
                    buf.blit_px(grid, spal, cxs, y, sc)
                else:
                    pal2 = dict(spal)
                    pal2['w'] = ci((5, 5, 2))
                    buf.blit_px(grid, pal2, cxs, y, sc)
            else:
                cxs = int(cen[y] + obj.x * hw[y])
                self.draw_rival(obj, y, cxs, hw[y])

        # ---- speed streaks ----
        if self.speed > 34 and self.state in ('race', 'countdown'):
            n = int((self.speed - 34) * 0.9)
            for _ in range(n):
                y = self.rng.randint(horizon + 2, H - 3)
                x = self.rng.randint(0, W - 1)
                if cen[y] - hw[y] - 2 < x < cen[y] + hw[y] + 2:
                    continue
                buf.put(x, y, '/' if x < cen[y] else '\\', ci(G(3)))

        self.draw_player(cen, hw)
        self.cen, self.hw = cen, hw

    # ---- bikers ----------------------------------------------------------
    def shadow(self, cx, ybot, width):
        half = max(1, int(width * 0.5))
        c = ci(G(0.25))
        for x in range(cx - half, cx + half + 1):
            self.buf.put(x, ybot, GLY[2], c)

    def draw_rival(self, r, y, cx, hwy):
        buf = self.buf
        s = hwy * 0.46 / BW
        if s * BW < 2:
            buf.put(cx, y, '\u2584', ci(r.jacket))
            return
        pal = biker_pal(r.jacket, r.helmet, r.hit_t > 0.1)
        self.shadow(cx, y, BW * s * 0.9)
        small = s < 0.42
        if small:
            grid = MINI_ROWS
            sc = s * 2
            if r.state == 'crash':
                grid = rotate_grid(MINI_ROWS, math.pi / 2, 14)
        else:
            sc = s
            wheel = int(self.t * (3 + r.speed * 0.4)) % 2
            if r.state == 'crash':
                ph = 1 - r.crash_t / 2.6
                ang = (ph / 0.45) * math.pi * 2.5 if ph < 0.45 else math.pi * 2.5
                grid = rotate_grid(build_frame(0, None, 0, 0, wheel, False), ang)
            else:
                lean = clamp((r.want - r.x) * 1.4, -1, 1) + r.recoil * 0.9
                if r.atk > 0 or r.recover > 0:
                    lean += r.atk_side * 0.35 * max(r.ext, 0)
                kind = r.atk_kind if (r.atk > 0 or r.recover > 0) else None
                grid = build_frame(lean, kind, r.atk_side, r.ext, wheel, False)
        ybot = y
        if r.state == 'crash':
            ph = 1 - r.crash_t / 2.6
            if ph < 0.45:
                ybot = y - int(math.sin(ph / 0.45 * math.pi) * 5 * s)
        cells = buf.blit_px(grid, pal, cx, ybot, sc) or 2
        if r.state == 'crash' and r.crash_t < 2.0:
            for i in range(3):                             # smoke
                buf.put(cx - 1 + i + int(math.sin(self.t * 3 + i) * 1.5),
                        ybot - cells - 1 - ((int(self.t * 4) + i) % 3), '\u2591', ci(G(2.6)))
        if r.fx_t > 0 and not small:
            self.impact(cx, ybot - cells // 2, cells, r.fx_txt, ybot - cells - 1)

    def impact(self, cx, cy, cells, word, ty):
        buf = self.buf
        hot = ci((5, 5, 1.5))
        mid = ci((5, 2.5, 0))
        spread = max(2, cells // 2 + 1)
        for dx, dy, c in ((-spread, -1, '\\'), (spread, -1, '/'), (-spread, 1, '/'),
                          (spread, 1, '\\'), (0, -cells // 2 - 1, '|'), (-spread - 2, 0, '-'),
                          (spread + 2, 0, '-')):
            buf.put(cx + dx, cy + dy, c, hot)
        buf.put(cx, cy, '*', ci(G(5)))
        buf.put(cx - 1, cy, '\u2593', mid)
        buf.put(cx + 1, cy, '\u2593', mid)
        buf.text(cx - len(word) // 2, ty, word, hot)

    def draw_player(self, cen, hw):
        H, W = self.H, self.W
        ybot = H - 2
        s = max(0.7, hw[ybot] * 0.46 / BW)
        flash = self.hurt_t > 0 and int(self.t * 20) % 2 == 0
        pal = biker_pal(PLAYER_JACKET, PLAYER_HELMET, flash)
        cx = W // 2
        if self.state == 'title' or self.state == 'countdown':
            pass
        shake = 0
        if self.state == 'race' and (abs(self.px) > 1.02 or self.crash_t > 0):
            shake = self.rng.choice((-1, 0, 1))
        wheel = int(self.t * (3 + self.speed * 0.4)) % 2
        self.shadow(cx + shake, ybot, BW * s * 0.9)
        if self.crash_t > 0:
            ph = clamp(1 - self.crash_t / 1.3, 0, 1)
            ang = ph * math.pi * 3.0
            lift = int(math.sin(ph * math.pi) * 5)
            grid = rotate_grid(build_frame(0, None, 0, 0, wheel, False), ang)
            cells = len(grid) // 2
            yb = int(round(ybot - 5.5 * s + cells * s / 2.0)) - lift
            self.buf.blit_px(grid, pal, cx + shake, yb, s)
            return
        lean = self.lean
        kind, ext, side = None, 0.0, self.atk_side
        if self.atk_t > 0:
            ph = 1 - self.atk_t / self.atk_len
            ext = (-0.3 * ph / 0.25) if ph < 0.25 else math.sin(math.pi * (ph - 0.25) / 0.75)
            kind = self.atk_kind
            lean += side * 0.4 * max(ext, 0)
        flame = self.boost and self.state == 'race'
        grid = build_frame(lean, kind, side, ext, wheel, flame)
        cells = self.buf.blit_px(grid, pal, cx + shake, ybot, s)
        if self.hurt_t > 0.15:
            self.impact(cx, ybot - cells // 2, cells // 2, "OUCH!", ybot - cells - 1)

    def draw_finish(self, y, kf, cen, hw, ratio):
        buf, W = self.buf, self.W
        thick = max(1, int(ratio * 3))
        w_, b_ = ci(G(5)), ci(G(0))
        for yy in range(max(self.horizon + 1, y - thick + 1), y + 1):
            l = int(cen[yy] - hw[yy])
            r = int(cen[yy] + hw[yy])
            for x in range(max(0, l), min(W, r + 1)):
                buf.bg[yy][x] = w_ if ((x // 2) + yy) % 2 else b_
                buf.ch[yy][x] = ' '
        h = max(2, int(ratio * 9))
        xl = int(cen[y] - hw[y]) - 1
        xr = int(cen[y] + hw[y]) + 1
        for i in range(1, h + 1):
            buf.put(xl, y - i, '\u2588', w_)
            buf.put(xr, y - i, '\u2588', w_)
        label = " FINISH "
        by = y - h
        buf.span(by, xl, xr + 1, bg=w_, fg=b_, ch=' ')
        if xr - xl > len(label) + 2:
            buf.text((xl + xr) // 2 - len(label) // 2, by, label, b_, w_)

    # ---- HUD / overlays ---------------------------------------------------
    def render_hud(self):
        buf, W, H = self.buf, self.W, self.H
        dark = ci((0.3, 0.3, 0.6))
        for y in range(3):
            buf.span(y, 0, W, bg=dark, fg=ci(G(5)), ch=' ')
        buf.span(H - 1, 0, W, bg=dark, fg=ci(G(3.2)), ch=' ')
        th, _ = theme_at(self.pos)
        kmh = int(self.speed * 4.2)
        t = self.race_t
        line = " SPD %3d km/h   POS %d/%d   SCORE %06d   TIME %02d:%02d   %s" % (
            kmh, self.rank(), N_RIVALS + 1, int(self.score), int(t // 60), int(t % 60), th['name'])
        buf.text(0, 0, line, ci((5, 4.5, 1)), dark)
        hb = 20
        hn = int(round(self.health / 100.0 * hb))
        hcol = (1, 5, 1) if self.health > 55 else (5, 4, 0) if self.health > 28 else (5, 0.5, 0.5)
        buf.text(1, 1, "HEALTH \u2595", ci(G(4)), dark)
        buf.text(9, 1, '\u2588' * hn, ci(hcol), dark)
        buf.text(9 + hn, 1, '\u2591' * (hb - hn), ci(G(2)), dark)
        buf.text(9 + hb, 1, "\u258f", ci(G(4)), dark)
        nb = 14
        nn = int(round(self.nitro / 100.0 * nb))
        x0 = 9 + hb + 4
        ncol = (0, 4.5, 5) if not self.boost else (5, 5, 5)
        buf.text(x0, 1, "NITRO \u2595", ci(G(4)), dark)
        buf.text(x0 + 7, 1, '\u2588' * nn, ci(ncol), dark)
        buf.text(x0 + 7 + nn, 1, '\u2591' * (nb - nn), ci(G(2)), dark)
        buf.text(x0 + 7 + nb, 1, "\u258f", ci(G(4)), dark)
        bw = min(W - 12, 64)
        buf.text(1, 2, "TRACK ", ci(G(4)), dark)
        buf.text(7, 2, '\u2500' * bw, ci(G(2)), dark)
        buf.text(7 + bw, 2, "\u2502F", ci(G(4)), dark)
        for r in self.rivals:
            i = int(clamp(r.z / TRACK_LEN, 0, 1) * (bw - 1))
            buf.put(7 + i, 2, '\u25cf', ci(r.jacket), dark)
        i = int(clamp(self.pos / TRACK_LEN, 0, 1) * (bw - 1))
        buf.put(7 + i, 2, '\u25c6', ci((5, 5, 0.5)), dark)
        hint = " A/D steer | S brake | Z/X punch | C/V kick | SPACE nitro | P pause | Q quit "
        buf.text(max(0, (W - len(hint)) // 2), H - 1, hint, ci(G(3.4)), dark)

    def center(self, y, txt, fg, bg=None):
        self.buf.text((self.W - len(txt)) // 2, y, txt, ci(fg), bg)

    def box(self, lines):
        buf, W, H = self.buf, self.W, self.H
        w = max(len(t) for t, _ in lines) + 6
        h = len(lines) + 2
        x0, y0 = (W - w) // 2, (H - h) // 2
        bgc = ci((0.3, 0.3, 0.7))
        edge = ci((5, 2.5, 0.5))
        for y in range(y0, y0 + h):
            buf.span(y, x0, x0 + w, bg=bgc, ch=' ')
        buf.span(y0, x0, x0 + w, fg=edge, ch='\u2550')
        buf.span(y0 + h - 1, x0, x0 + w, fg=edge, ch='\u2550')
        for y in range(y0 + 1, y0 + h - 1):
            buf.put(x0, y, '\u2551', edge, bgc)
            buf.put(x0 + w - 1, y, '\u2551', edge, bgc)
        buf.put(x0, y0, '\u2554', edge)
        buf.put(x0 + w - 1, y0, '\u2557', edge)
        buf.put(x0, y0 + h - 1, '\u255a', edge)
        buf.put(x0 + w - 1, y0 + h - 1, '\u255d', edge)
        for i, (txt, col) in enumerate(lines):
            buf.text(x0 + (w - len(txt)) // 2, y0 + 1 + i, txt, ci(col), bgc)

    def render_overlay(self):
        s = self.state
        if s == 'countdown':
            n = int(math.ceil(self.cd - 0.6))
            if n >= 1:
                for i, row in enumerate(big_text(str(n))):
                    self.center(6 + i, row, (5, 5 - i * 0.5, 0.5))
            self.center(13, "GET READY - rivals are on the grid ahead!", (5, 5, 5))
        elif s == 'pause':
            self.box([("PAUSED", (5, 5, 1)), ("", G(5)), ("P  resume", G(4)), ("Q  quit", G(4))])
        elif s == 'finish':
            r = self.result
            suf = {1: 'ST', 2: 'ND', 3: 'RD'}.get(r['rank'], 'TH')
            self.box([("*** FINISH ***", (5, 5, 1)), ("", G(5)),
                      ("You placed %d%s of %d" % (r['rank'], suf, N_RIVALS + 1), (1, 5, 1)),
                      ("Race time   %02d:%05.2f" % (int(r['time'] // 60), r['time'] % 60), G(5)),
                      ("Race score  %d" % int(self.score), G(5)),
                      ("Bonus       %d" % r['bonus'], G(5)),
                      ("TOTAL       %d" % r['total'], (5, 4, 0)),
                      ("Best        %d" % (self.best or 0), G(3.5)), ("", G(5)),
                      ("ENTER race again   Q quit", G(4))])
        elif s == 'over':
            self.box([("W R E C K E D", (5, 0.6, 0.6)), ("", G(5)),
                      ("The gang ran you off the road.", G(5)),
                      ("Score %d" % int(self.score), (5, 4, 0)), ("", G(5)),
                      ("ENTER try again   Q quit", G(4))])
        if self.msg and s in ('race', 'countdown'):
            txt, col, ttl = self.msg
            self.center(5, "  " + txt + "  ", col, ci((0.2, 0.2, 0.5)))

    def render_title(self):
        buf, W, H = self.buf, self.W, self.H
        if H >= 30:
            y = 1
            for wi, word in enumerate(("ROAD", "BRAWL")):
                for i, row in enumerate(big_text(word)):
                    c = lerp_rgb((5, 5, 0.8), (5, 1.0, 1.8), (i + 5 * wi) / 10.0)
                    x = (W - len(row)) // 2
                    for j, chv in enumerate(row):
                        if chv != ' ':
                            buf.put(x + j + 1, y + i + 1, chv, ci(G(0.4)))
                    for j, chv in enumerate(row):
                        if chv != ' ':
                            buf.put(x + j, y + i, chv, ci(c))
                y += 6
        else:
            self.center(2, "R O A D   B R A W L", (5, 4, 0.5))
        by = H - 9
        for i, (t, c) in enumerate([
                ("PIXEL-ART MOTORCYCLE COMBAT RACING", (5, 3, 2)),
                ("A / D  steer     S  brake     SPACE  nitro", G(5)),
                ("Z / X  punch left / right     C / V  kick left / right", G(5))]):
            self.center(by + i, t, c, ci((0.2, 0.2, 0.5)))
        if int(self.t * 2) % 2:
            self.center(H - 4, "  PRESS ENTER TO RACE  ", (1, 5, 1), ci((0.2, 0.2, 0.5)))
        self.center(H - 2, "Q quit", G(3.2))


# --------------------------------------------------------------------------
def main(stdscr):
    global USE256
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.nodelay(True)
    stdscr.keypad(True)
    curses.start_color()
    USE256 = curses.COLORS >= 256
    Game(stdscr).run()


if __name__ == "__main__":
    import os
    os.environ.setdefault("ESCDELAY", "25")
    try:
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        pass
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
