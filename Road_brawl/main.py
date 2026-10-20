#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
 ROAD BRAWL  -  an ASCII motorcycle combat racer for your terminal
 ------------------------------------------------------------------
 Race 8 rival bikers across four scenic zones (sunset valley, desert mesa,
 neon night, misty pines).  Punch rivals off their bikes, dodge their hits,
 grab repair kits and nitro, and cross the finish line in first place.

 Pure standard library (curses).  Works on Linux / macOS terminals.
 On Windows:  pip install windows-curses

 Run:   python3 road_brawl.py
 Best:  a 256-colour terminal at least 100x32 (bigger is prettier).

 CONTROLS
   LEFT / RIGHT  (or A / D)   steer  (tap = nudge, hold = keep turning)
   DOWN (or S)                brake
   Z / X                      punch / kick LEFT / RIGHT
   SPACE                      toggle NITRO
   P pause     Q quit
"""
import bisect
import curses
import math
import random
import time

# --------------------------------------------------------------------------
#  tunables
# --------------------------------------------------------------------------
TRACK_LEN = 7200.0      # world units to the finish line
ZONE_LEN = 1800.0       # length of each scenic zone
DEPTH = 48.0            # how far ahead we draw (world units)
FPS = 30
MAX_SPEED = 44.0
BOOST_SPEED = 58.0
N_RIVALS = 8

USE256 = True


# --------------------------------------------------------------------------
#  small helpers
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
    """grey level 0..5"""
    return (v, v, v)


def ci(c):
    """colour (r,g,b in 0..5 floats) -> terminal colour index"""
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
            p = 0
        else:
            try:
                curses.init_pair(n, fg, bg)
                p = n
            except curses.error:
                p = 0
        _PAIRS[key] = p
    return curses.color_pair(p)


# --------------------------------------------------------------------------
#  themes / track
# --------------------------------------------------------------------------
THEMES = [
    dict(name="SUNSET VALLEY",
         sky=((0, 0, 1), (2.6, 0.4, 2.4), (5, 3, 1)),
         sun=(5, 5, 1), mfar=(2.4, 0.6, 2.2), mnear=(1.2, 0.2, 1.4),
         gA=(0.2, 2, 0.2), gB=(0, 1.4, 0.1), leaf=(0, 3, 0), stars=0.6,
         scenery=['tree', 'tree', 'lamp', 'sign', 'rock', 'bill']),
    dict(name="DESERT MESA",
         sky=((0, 1, 3), (2.5, 3, 5), (5, 4, 2.5)),
         sun=(5, 5, 3), mfar=(4, 2, 1), mnear=(3, 1, 0.5),
         gA=(5, 4, 1.2), gB=(4.2, 3.2, 1), leaf=(1, 3, 0), stars=0.0,
         scenery=['cactus', 'cactus', 'rock', 'rock', 'sign', 'bill']),
    dict(name="NEON NIGHT",
         sky=((0, 0, 0), (1.2, 0, 2), (4.5, 0.2, 3.5)),
         sun=(5, 1, 4), mfar=(1.2, 0, 2.2), mnear=(0.3, 0, 1.2),
         gA=(0, 0.3, 1.4), gB=(0, 0, 0.8), leaf=(0, 1.5, 3), stars=1.0,
         scenery=['lamp', 'lamp', 'bill', 'pine', 'sign']),
    dict(name="MISTY PINES",
         sky=((1, 2.5, 4.5), (3, 4, 5), (5, 5, 4.5)),
         sun=(5, 5, 3), mfar=(2.2, 3.2, 3.2), mnear=(1, 2, 2),
         gA=(0, 2.4, 0.4), gB=(0, 1.7, 0.3), leaf=(0, 2.2, 0.6), stars=0.0,
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
    glyphs = {}
    cur = None
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
#  ASCII art
# --------------------------------------------------------------------------
TRUNK = G(2.0)
LAMP = G(5)

ART = {
    'tree': [
        ["   .@@@.   ", " .@@@@@@@. ", "@@@@@@@@@@@", " '@@@@@@@' ",
         "    '#'    ", "     #     ", "     #     "],
        [" .@@@. ", "@@@@@@@", " '@@@' ", "   #   ", "   #   "],
        [" @@@ ", "'@@@'", "  #  "],
        ["@"],
    ],
    'pine': [
        ["   /\\   ", "  /@@\\  ", " /@@@@\\ ", "/@@@@@@\\", "  /@@\\  ",
         " /@@@@\\ ", "/@@@@@@\\", "   ##   "],
        ["  /\\  ", " /@@\\ ", "/@@@@\\", " /@@\\ ", "  ##  "],
        [" /\\ ", "/@@\\", " ## "],
        ["A"],
    ],
    'cactus': [
        ["   _   ", " _| |_ ", "| | | |", "|_| | |", "  | |_|", "  | |  ",
         "  |_|  "],
        [" _  ", "| |_ ", "|_| |", "  |_|"],
        ["|_|", "| |"],
        ["!"],
    ],
    'rock': [
        ["   ___   ", " _/   \\_ ", "/       \\"],
        [" _/\\_ ", "/    \\"],
        ["/\\"],
        ["^"],
    ],
    'lamp': [
        ["  ,-.  ", " ( O ) ", "  | |  ", "  | |  ", "  | |  ", "  | |  ",
         "  | |  "],
        [" (O) ", "  |  ", "  |  ", "  |  "],
        ["O", "|", "|"],
        ["!"],
    ],
    'sign': [
        ["+-----+", "| >>> |", "+-----+", "   |   ", "   |   "],
        ["[>>]", " || ", " || "],
        ["[>]", " | "],
        ["#"],
    ],
}
BILL_TEXT = ["NITRO", "TURBO", "BRAWL", "SPEED", "FURY!"]


def bill_art(size, text):
    if size == 0:
        return ["+-------+", "| %s |" % text, "+-------+", "   | |   ",
                "   | |   ", "   | |   "]
    if size == 1:
        return ["+-----+", "|%s|" % text, "+-----+", " | | "]
    if size == 2:
        return ["[===]", "  |  "]
    return ["#"]


RIVAL_ART = [
    ["   .-.   ", "  ( o )  ", " --|#|-- ", "   |#|   ", "  [===]  ",
     "   |#|   ", "   '-'   "],
    [" (o) ", "-|#|-", " [=] ", " |#| "],
    [" o ", "-#-", " # "],
    ["#"],
]
WRECK_ART = [
    ["  \\ | /  ", " -- * -- ", "  / | \\  ", " _/ \\_ "],
    [" \\*/ ", "_/ \\_"],
    ["*"],
    ["*"],
]
PICKUP_ART = [
    ["+-----+", "|  %s  |", "+-----+"],
    ["+---+", "| %s |", "+---+"],
    ["[%s]"],
    ["%s"],
]


def rival_art(size, r, t):
    if r.state == 'crash':
        return WRECK_ART[size], {}, G(3.2)
    art = RIVAL_ART[size]
    if size == 0 and r.atk > 0:
        art = list(art)
        art[2] = " --|#|=====o" if r.atk_side > 0 else "o=====|#|-- "
    cm = {'o': r.helmet, '(': r.helmet, ')': r.helmet, '#': r.jacket,
          '=': G(3.6), '[': G(3.6), ']': G(3.6)}
    return art, cm, G(1.6)


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

    def blit(self, art, cx, ybot, cmap, default):
        h = len(art)
        for i, line in enumerate(art):
            y = ybot - (h - 1 - i)
            if y < 0 or y >= self.H:
                continue
            x0 = cx - len(line) // 2
            for j, c in enumerate(line):
                if c == ' ':
                    continue
                x = x0 + j
                if 0 <= x < self.W:
                    self.ch[y][x] = c
                    self.fg[y][x] = ci(cmap.get(c, default))

    def flush(self, scr):
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
JACKETS = [(0.5, 1.5, 5)]
HELMETS = [(5, 5, 5)]


class Rival:
    def __init__(self, idx, rng):
        self.rng = rng
        self.idx = idx
        self.jacket = JACKETS[0]
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
                        self.rng.randint(8, 18)) for _ in range(6)]
        self.pos = 0.0
        self.speed = 20.0
        self.px = 0.0
        self.rivals = []
        self.pickups = []
        self.dead = set()
        self.msg = None
        self.best = None
        self.reset_player()

    # ------------------------------------------------------------ setup ----
    def reset_player(self):
        self.vx = 0.0
        self.health = 100.0
        self.nitro = 100.0
        self.boost = False
        self.score = 0.0
        self.race_t = 0.0
        self.brake_until = 0.0
        self.punch_t = 0.0
        self.punch_cd = 0.0
        self.punch_side = 1
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
            r.reset(slots[i] + self.rng.uniform(-2, 2), lanes[i % 4] + self.rng.uniform(-0.1, 0.1))
            self.rivals.append(r)
        self.state = 'countdown'
        self.cd = 3.6
        self.msg = None

    def say(self, text, color=None, ttl=1.2):
        self.msg = [text, G(5), ttl]

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

    # ------------------------------------------------------------- main ----
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
                self.try_punch(-1)
            elif k in ('x', '.'):
                self.try_punch(1)
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

        self.punch_t = max(0.0, self.punch_t - dt)
        self.punch_cd = max(0.0, self.punch_cd - dt)
        self.hurt_t = max(0.0, self.hurt_t - dt)
        if self.crash_t > 0:
            self.crash_t -= dt
            if self.crash_t <= 0:
                if abs(self.px) > 1.0:
                    self.px = 0.85 * (1 if self.px > 0 else -1)
                self.vx = 0.0

        # zone banner
        zi = int(self.pos // ZONE_LEN)
        if zi != self.zone_seen and zi < len(THEMES):
            self.zone_seen = zi
            self.say(">> %s <<" % THEMES[zi]['name'], (5, 5, 2), 2.2)

        # roadside crashes
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

        # pickups
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
        # keep rivals from stacking
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
        self.say("CRASH!  -12 HP", (5, 1, 0), 1.2)

    def hurt(self, dmg, attacker_gap):
        self.health -= dmg
        self.hurt_t = 0.35
        self.vx += (-1 if attacker_gap >= 0 else 1) * 1.6
        self.say("OUCH!  -%d HP" % dmg, (5, 1, 0), 0.8)

    def try_punch(self, side):
        if self.punch_cd > 0 or self.crash_t > 0:
            return
        self.punch_t = 0.28
        self.punch_side = side
        self.punch_cd = 0.38
        best = None
        for r in self.rivals:
            if r.state != 'ride':
                continue
            d = r.z - self.pos
            gap = (r.x - self.px) * side
            if abs(d) < 2.6 and 0.05 < gap < 1.5:
                if best is None or gap < best[0]:
                    best = (gap, r)
        if best:
            self.hit_rival(best[1], side)

    def hit_rival(self, r, side):
        r.hp -= 1
        r.x += side * 0.45
        r.stun = 0.5
        r.atk = 0
        r.speed *= 0.8
        self.score += 50
        if r.hp <= 0:
            r.state = 'crash'
            r.crash_t = 2.6
            self.score += 300
            self.say("TAKEN DOWN!  +300", (5, 4, 0), 1.3)
        else:
            self.say("WHAM!  +50", (5, 5, 1), 0.6)

    def update_rival(self, r, dt):
        d = r.z - self.pos
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

        # body bump
        gap = r.x - self.px
        if abs(d) < 1.3 and abs(gap) < 0.28 and self.crash_t <= 0:
            s = 1 if gap >= 0 else -1
            r.x += s * 0.2
            self.px -= s * 0.2
            self.speed *= 0.96

        # attack
        r.atk_cd -= dt
        if r.atk > 0:
            r.atk -= dt
            if r.atk <= 0:
                g = r.x - self.px
                if abs(r.z - self.pos) < 2.6 and abs(g) < 1.25 and self.crash_t <= 0 and r.stun <= 0:
                    self.hurt(r.dmg, g)
                r.atk_cd = self.rng.uniform(1.3, 2.4)
        elif (r.atk_cd <= 0 and r.stun <= 0 and abs(d) < 2.2 and
              0.15 < abs(gap) < 1.0 and self.crash_t <= 0 and
              self.rng.random() < r.aggr * dt * 4):
            r.atk = 0.45
            r.atk_side = -1 if gap > 0 else 1

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
            self.buf = Buf(W, H)
            try:
                self.scr.erase()
            except curses.error:
                pass
        else:
            self.buf = Buf(W, H)
        if W < 72 or H < 24:
            b = self.buf
            b.text(1, 1, "Terminal too small:", 7)
            b.text(1, 2, "need at least 72x24 (have %dx%d)" % (W, H), 7)
            b.flush(self.scr)
            self.scr.refresh()
            return
        self.render_world()
        s = self.state
        if s == 'title':
            self.render_title()
        else:
            self.render_hud()
            self.render_overlay()
        self.buf.flush(self.scr)
        self.scr.refresh()

    # ---- world ---------------------------------------------------------
    def render_world(self):
        W, H = self.W, self.H
        buf = self.buf
        horizon = int(H * 0.42)
        rows = H - 2 - horizon
        d0 = DEPTH / (0.92 * rows)
        self.horizon, self.rows = horizon, rows
        pos = self.pos
        th, zi = theme_at(pos)
        sky0, sky1, sky2 = th['sky']
        fogc = sky1
        skycols = []

        # sky gradient
        for y in range(horizon):
            tt = y / max(1, horizon - 1)
            c = sky1  # flat, uniform sky colour
            skycols.append(c)
            buf.span(y, 0, W, bg=ci(c))
        buf.span(horizon, 0, W, bg=ci(sky1))

        # stars
        if th['stars'] > 0.45:
            for fx, fy, ph in self.stars:
                if (self.frame // 7 + ph) % 6 == 0:
                    continue
                x = int(fx * W)
                y = int(fy * horizon * 0.75)
                buf.put(x, y, '*' if ph == 0 else '.', ci(G(5)))
        else:
            for fx, fy, ln in self.clouds:
                y = 3 + int(fy * horizon * 0.35)
                x = int((fx * W * 1.4 - self.bgoff * 0.25 + self.t * 1.5) % (W + 30)) - 15
                col = ci(G(4.6))
                for i in range(ln):
                    buf.put(x + i, y, '~', col)

        # sun
        ry = max(3, int(horizon * 0.24))
        rx = ry * 2
        sx = int((W * 0.55 - self.bgoff * 0.1) % (W + 40)) - 20
        sy = horizon - int(ry * 0.45)
        for dy in range(-ry, ry + 1):
            y = sy + dy
            if y < 0 or y >= horizon:
                continue
            if dy > ry * 0.15 and (dy + ry) % 3 == 0:
                continue
            half = int(rx * math.sqrt(max(0.0, 1 - (dy / ry) ** 2)))
            col = th['sun']
            buf.span(y, sx - half, sx + half + 1, bg=ci(col))

        # mountains (two parallax layers)
        hmax = max(3.0, horizon * 0.55)
        cfar, cnear = ci(th['mfar']), ci(th['mnear'])
        for x in range(W):
            u = x + self.bgoff * 0.5
            h1 = int(hmax * (0.45 + 0.28 * math.sin(u * 0.031) + 0.2 * math.sin(u * 0.083 + 2.0)
                             + 0.1 * math.sin(u * 0.21)))
            u2 = x + self.bgoff
            h2 = int(hmax * 0.62 * (0.4 + 0.3 * math.sin(u2 * 0.047 + 1.0)
                                    + 0.2 * math.sin(u2 * 0.13 + 4.0) + 0.1 * math.sin(u2 * 0.3)))
            for yy in range(max(0, horizon - h1), horizon):
                buf.bg[yy][x] = cfar
            for yy in range(max(0, horizon - h2), horizon):
                buf.bg[yy][x] = cnear

        # road geometry (near -> far, accumulating curvature)
        cen = [0.0] * H
        hw = [0.0] * H
        cx = W / 2.0
        dxv = 0.0
        for y in range(H - 2, horizon, -1):
            k = y - horizon
            d = DEPTH / k - d0
            dxv += curve_at(pos + d) * 0.05
            cx += dxv
            w = k / rows * W * 0.42 + 0.8
            cen[y] = cx - self.px * w
            hw[y] = w

        # ground + road
        for y in range(horizon + 1, H - 1):
            k = y - horizon
            tt = k / rows
            fogf = 0.0
            ph = math.sin(26 * (1 - tt) ** 3 + pos * 0.5)
            gcol = th['gA']
            buf.span(y, 0, W, bg=ci(gcol))
            l = int(cen[y] - hw[y])
            r = int(cen[y] + hw[y])
            if tt > 0.3:
                zz = int((pos + DEPTH / k - d0) * 1.5)
                sc = ci(lerp_rgb(gcol, (5, 5, 5), 0.25))
                for x in range(W):
                    h = (zz * 37 + x * 101) % 29
                    if h < 2 and (x < l - 1 or x > r + 1):
                        buf.put(x, y, ',' if h == 0 else '"', sc)
            road = G(1.0)
            rum = G(4.2)
            rw = max(1, int(hw[y] * 0.1))
            buf.span(y, l, l + rw, bg=ci(rum))
            buf.span(y, l + rw, r - rw + 1, bg=ci(road))
            buf.span(y, r - rw + 1, r + 1, bg=ci(rum))
            if tt > 0.06 and math.sin(40 * (1 - tt) ** 3 + pos * 0.9) > 0.2:
                lw = max(1, int(hw[y] * 0.03))
                lc = ci(G(4.2))
                for off in (-0.333, 0.333):
                    xc = int(cen[y] + off * hw[y])
                    buf.span(y, xc, xc + lw, bg=lc)

        # collect sprites
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

        for d, kind, obj in objs:
            kf = DEPTH / (d + d0)
            y = horizon + int(round(kf))
            if y <= horizon or y > H - 2:
                continue
            ratio = kf / rows
            size = 0 if ratio >= 0.45 else 1 if ratio >= 0.22 else 2 if ratio >= 0.09 else 3
            if kind == 'f':
                self.draw_finish(y, kf, cen, hw, ratio)
                continue
            if kind == 's':
                z, lat, sk, var = SCENERY[obj]
                cxs = int(cen[y] + lat * hw[y])
                self.draw_scenery(z, lat, sk, var, size, cxs, y, th)
            elif kind == 'p':
                cxs = int(cen[y] + obj['lat'] * hw[y])
                sym = '+' if obj['kind'] == 'hp' else 'N'
                art = [ln.replace('%s', sym) for ln in PICKUP_ART[size]]
                col = G(5) if int(self.t * 4) % 2 else G(3.5)
                buf.blit(art, cxs, y, {}, col)
            else:
                cxs = int(cen[y] + obj.x * hw[y])
                art, cm, df = rival_art(size, obj, self.t)
                buf.blit(art, cxs, y, cm, df)

        # speed streaks
        if self.speed > 34 and self.state in ('race', 'countdown'):
            n = int((self.speed - 34) * 0.9)
            for _ in range(n):
                y = self.rng.randint(horizon + 2, H - 3)
                x = self.rng.randint(0, W - 1)
                if cen[y] - hw[y] - 2 < x < cen[y] + hw[y] + 2:
                    continue
                buf.put(x, y, '/' if x < cen[y] else '\\', ci(lerp_rgb(G(3), th['gA'], 0.3)))

        # the player
        if self.state != 'title':
            self.draw_player(H - 2)
        else:
            self.draw_player(H - 2)
        self.cen, self.hw = cen, hw

    def draw_scenery(self, z, lat, kind, var, size, cx, y, th):
        buf = self.buf
        if kind == 'tree':
            buf.blit(ART['tree'][size], cx, y, {'#': TRUNK}, th['leaf'])
        elif kind == 'pine':
            buf.blit(ART['pine'][size], cx, y, {'#': TRUNK}, th['leaf'])
        elif kind == 'cactus':
            buf.blit(ART['cactus'][size], cx, y, {}, G(3))
        elif kind == 'rock':
            buf.blit(ART['rock'][size], cx, y, {}, G(2.4))
        elif kind == 'lamp':
            cm = {c: LAMP for c in 'O(),-.'}
            buf.blit(ART['lamp'][size], cx, y, cm, G(2.4))
        elif kind == 'sign':
            ch = '>' if curve_at(z) >= 0 else '<'
            art = [ln.replace('>', ch) for ln in ART['sign'][size]]
            buf.blit(art, cx, y, {}, G(4.5))
        elif kind == 'bill':
            cm = {c: G(4) for c in '+-|=[]'}
            buf.blit(bill_art(size, BILL_TEXT[var % 5]), cx, y, cm, G(4))

    def draw_finish(self, y, kf, cen, hw, ratio):
        buf, W = self.buf, self.W
        thick = max(1, int(ratio * 3))
        for yy in range(max(self.horizon + 1, y - thick + 1), y + 1):
            l = int(cen[yy] - hw[yy])
            r = int(cen[yy] + hw[yy])
            for x in range(max(0, l), min(W, r + 1)):
                buf.bg[yy][x] = ci(G(5)) if ((x // 2) + yy) % 2 else ci(G(0))
        h = max(2, int(ratio * 9))
        xl = int(cen[y] - hw[y]) - 1
        xr = int(cen[y] + hw[y]) + 1
        for i in range(1, h + 1):
            buf.put(xl, y - i, '|', ci(G(5)))
            buf.put(xr, y - i, '|', ci(G(5)))
        label = " FINISH "
        by = y - h
        if xr - xl > len(label) + 2:
            buf.span(by, xl, xr + 1, bg=ci(G(5)), fg=ci(G(0)))
            buf.text((xl + xr) // 2 - len(label) // 2, by, label, ci(G(0)), ci(G(5)))
        else:
            buf.span(by, xl, xr + 1, bg=ci(G(5)))

    def player_art(self):
        if self.crash_t > 0:
            if int(self.t * 10) % 2:
                return ["  \\  |  /  ", " --  *  -- ", "  /  |  \\  ", " ___/ \\___ ", "  ~  ~  ~  "]
            return ["  /  |  \\  ", " --  x  -- ", "  \\  |  /  ", " ___/ \\___ ", "  ~  ~  ~  "]
        row2 = "   ==/|###|\\==   "
        if self.punch_t > 0:
            row2 = " <<====|###|\\==   " if self.punch_side < 0 else "   ==/|###|====>> "
        return ["      _.-._      ",
                "     (  o  )     ",
                row2,
                "     [#####]     ",
                "      |###|      ",
                "     [=====]     ",
                "      '---'      "]

    def draw_player(self, ybot):
        jacket = (5, 5, 5) if (self.hurt_t > 0 and int(self.t * 20) % 2) else (5, 0.3, 0.3)
        cm = {'o': G(5), '(': G(5), ')': G(5), '#': jacket,
              '=': G(5), '<': G(5), '>': G(5),
              '[': G(4.2), ']': G(4.2), '*': G(5), 'x': G(5), '~': G(3)}
        shake = 0
        if self.state == 'race' and (abs(self.px) > 1.02 or self.crash_t > 0):
            shake = self.rng.choice((-1, 0, 1))
        jitter = 0
        if self.state == 'race' and self.speed > 20:
            jitter = 0 if int(self.t * 12) % 2 else 0
        self.buf.blit(self.player_art(), self.W // 2 + shake + jitter, ybot, cm, G(2.2))

    # ---- HUD / overlays --------------------------------------------------
    def render_hud(self):
        buf, W, H = self.buf, self.W, self.H
        dark = ci(G(0.9))
        for y in range(3):
            buf.span(y, 0, W, bg=dark, fg=ci(G(5)))
            for x in range(W):
                buf.ch[y][x] = ' '
        buf.span(H - 1, 0, W, bg=dark, fg=ci(G(3.2)))
        th, _ = theme_at(self.pos)
        kmh = int(self.speed * 4.2)
        t = self.race_t
        line = " SPD %3d km/h   POS %d/%d   SCORE %06d   TIME %02d:%02d   %s" % (
            kmh, self.rank(), N_RIVALS + 1, int(self.score), int(t // 60), int(t % 60), th['name'])
        buf.text(0, 0, line, ci(G(5)), dark)
        hb = 20
        hn = int(round(self.health / 100.0 * hb))
        hcol = G(5)
        buf.text(1, 1, "HEALTH [", ci(G(4)), dark)
        buf.text(9, 1, '#' * hn, ci(hcol), dark)
        buf.text(9 + hn, 1, '-' * (hb - hn), ci(G(1.8)), dark)
        buf.text(9 + hb, 1, "]", ci(G(4)), dark)
        nb = 14
        nn = int(round(self.nitro / 100.0 * nb))
        x0 = 9 + hb + 4
        ncol = G(5)
        buf.text(x0, 1, "NITRO [", ci(G(4)), dark)
        buf.text(x0 + 7, 1, '#' * nn, ci(ncol), dark)
        buf.text(x0 + 7 + nn, 1, '-' * (nb - nn), ci(G(1.8)), dark)
        buf.text(x0 + 7 + nb, 1, "]", ci(G(4)), dark)
        # progress bar
        bw = min(W - 12, 64)
        buf.text(1, 2, "TRACK [", ci(G(4)), dark)
        buf.text(8, 2, '-' * bw, ci(G(1.8)), dark)
        buf.text(8 + bw, 2, "]F", ci(G(4)), dark)
        for r in self.rivals:
            i = int(clamp(r.z / TRACK_LEN, 0, 1) * (bw - 1))
            buf.put(8 + i, 2, 'o', ci(G(3)), dark)
        i = int(clamp(self.pos / TRACK_LEN, 0, 1) * (bw - 1))
        buf.put(8 + i, 2, 'P', ci(G(5)), dark)
        hint = " A/D steer | S brake | Z/X punch left/right | SPACE nitro | P pause | Q quit "
        buf.text(max(0, (W - len(hint)) // 2), H - 1, hint, ci(G(3.2)), dark)

    def center(self, y, txt, fg, bg=None):
        self.buf.text((self.W - len(txt)) // 2, y, txt, ci(G(5)), bg)

    def box(self, lines):
        buf, W, H = self.buf, self.W, self.H
        w = max(len(t) for t, _ in lines) + 6
        h = len(lines) + 2
        x0, y0 = (W - w) // 2, (H - h) // 2
        bgc = ci(G(0.5))
        for y in range(y0, y0 + h):
            buf.span(y, x0, x0 + w, bg=bgc, ch=' ')
        edge = ci(G(5))
        buf.span(y0, x0, x0 + w, fg=edge, ch='-')
        buf.span(y0 + h - 1, x0, x0 + w, fg=edge, ch='-')
        for y in range(y0 + 1, y0 + h - 1):
            buf.put(x0, y, '|', edge, bgc)
            buf.put(x0 + w - 1, y, '|', edge, bgc)
        for i, (txt, col) in enumerate(lines):
            buf.text(x0 + (w - len(txt)) // 2, y0 + 1 + i, txt, ci(G(5)), bgc)

    def render_overlay(self):
        buf, W, H = self.buf, self.W, self.H
        s = self.state
        if s == 'countdown':
            n = int(math.ceil(self.cd - 0.6))
            word = str(n) if n >= 1 else "GO"
            if n >= 1:
                rows = big_text(word)
                for i, row in enumerate(rows):
                    self.center(6 + i, row, G(5))
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
            self.center(5, "  " + txt + "  ", col, ci(G(0.4)))

    def render_title(self):
        buf, W, H = self.buf, self.W, self.H
        if H >= 30:
            y = 1
            for word in ("ROAD", "BRAWL"):
                for i, row in enumerate(big_text(word)):
                    c = (5, 5, 5)
                    x = (W - len(row)) // 2
                    for j, chv in enumerate(row):
                        if chv != ' ':
                            buf.put(x + j, y + i, chv, ci(c))
                y += 6
        else:
            self.center(2, "R O A D   B R A W L", G(5))
        by = H - 9
        for i, (t, c) in enumerate([
                ("ASCII MOTORCYCLE COMBAT RACING", (5, 3, 2)),
                ("", G(5)),
                ("A / D  steer    S  brake    SPACE  nitro", G(5)),
                ("Z / X  punch left / right  -  knock rivals off their bikes!", G(5))]):
            self.center(by + i, t, c, ci(G(0.4)))
        if int(self.t * 2) % 2:
            self.center(H - 4, "  PRESS ENTER TO RACE  ", (1, 5, 1), ci(G(0.4)))
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
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass