# -*- coding: utf-8 -*-
"""클로드 펫 — 데스크톱에 상주하며 Claude Code 세션 이벤트를 말풍선으로 알려주는 펫.

이벤트 공급: Claude Code hooks(Notification/Stop) → pet_hook.py → events.jsonl append
이 프로세스는 events.jsonl을 tail 하며 새 줄이 오면 말풍선 + 바운스로 알린다.

외형: assets/ 에 이미지가 있으면 그것을 쓰고, 없으면 내장 벡터 펫을 그린다.
      assets/idle.(png|gif) · notify.* · blink.*  (idle만 있어도 동작)
"""
import ctypes
import json
import math
import os
import random
import socket
import time
import tkinter as tk
from ctypes import wintypes

BASE = os.path.dirname(os.path.abspath(__file__))
EVENTS_PATH = os.path.join(BASE, "events.jsonl")
CONFIG_PATH = os.path.join(BASE, "config.json")
ASSETS_DIR = os.path.join(BASE, "assets")
SIT_ACTIONS_DIR = os.path.join(ASSETS_DIR, "sit_actions")
SIT_ACTIONS_CONFIG = os.path.join(SIT_ACTIONS_DIR, "actions.json")

TRANSPARENT = "#ff00fe"  # -transparentcolor 키색: 이 색 픽셀은 투명 + 클릭 통과
TRANSPARENT_RGB = (255, 0, 254)
CLAY = "#d97757"
CLAY_DARK = "#b85c3f"
BLUSH = "#eda88f"
CREAM = "#fdf8f1"
INK = "#2d2318"
BADGE = "#e5484d"

VECTOR_SIZE = 104          # 내장 벡터 펫이 차지하는 정사각 크기
BUBBLE_ZONE = 150          # 말풍선용 상단 여백
BUBBLE_SECONDS = 12
BUBBLE_GAP = 6             # 말풍선 꼬리와 몸 사이 간격(px)
SINGLETON_PORT = 48620
SNAP_DIST = 70             # 이 거리 안이면 가장자리·창 위에 달라붙는다
SNAP_FRAMES = 7            # 달라붙는 동안의 프레임 수
IDLE_LIE_SECONDS = 300     # 이만큼 조용하면 드러눕고
IDLE_SLEEP_SECONDS = 1200  # 더 오래 조용하면 잠든다
WANDER_EVERY = (45, 150)   # 이 간격(초)으로 가끔 좌우로 거닌다
WANDER_TIME = (0.8, 3.0)   # 한 번에 걷는 시간(초) — 이 사이에서 무작위
WANDER_SPEED = 4           # 프레임당 이동 픽셀 (25ms 틱 → 초당 160px)
TICK_MS = 25               # 화면 갱신 주기. 낮출수록 부드럽다 (40fps)
POSES = (
    "fall",
    "idle", "sit", "sit_blink", "sit_sleep", "hang", "hang_blink", "hang_sleep",
    "lie", "lie_blink", "prone", "prone_blink", "sleep", "walk", "notify",
    "sit_notify", "hang_notify", "lie_notify", "prone_notify", "blink", "drag"
)
# 자세별 눈 깜빡임 그림. 잠든 자세는 이미 눈을 감고 있으니 없다.
BLINK_OF = {"idle": "blink", "sit": "sit_blink", "hang": "hang_blink",
            "lie": "lie_blink", "prone": "prone_blink"}
# 매달리는 자세는 발바닥이 아니라 손끝(위쪽)을 기준으로 붙인다.
TOP_ALIGNED = {"hang", "hang_blink", "hang_sleep"}
# 방향이 있는 그림 — 오른쪽을 향해 그려져 있고, 왼쪽으로 갈 땐 좌우로 뒤집는다.
DIRECTIONAL = {"walk"}
GRAVITY = 0.6              # 공중에 놓으면 이만큼씩 빨라지며 떨어진다
MAX_FALL = 21              # 프레임당 최대 낙하 픽셀
# 눕지 못하는 자리(창 위·매달린 상태)에서 오래 조용할 때 쓸 그림. 없으면 그 자세 유지.
SLEEP_OF = {"sit": "sit_sleep", "hang": "hang_sleep"}
# 그 자세로 알림에 놀라는 그림. 없으면 서 있는 notify로 대신한다.
NOTIFY_OF = {"sit": "sit_notify", "hang": "hang_notify",
             "lie": "lie_notify", "prone": "prone_notify"}


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def window_rect(hwnd):
    """살아 있고 보이는 창이면 화면 좌표 사각형, 아니면 None."""
    try:
        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
            return None
        if user32.IsIconic(hwnd):      # 최소화
            return None
        r = _RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def perchable_windows(exclude_hwnd, exclude_pid=None):
    """펫이 올라앉을 만한 최상위 창 목록. 앞에 있는 창부터 담긴다.

    펫 자신의 창은 물론 메뉴 팝업 같은 부수 창까지 빼려면 프로세스로 거른다.
    """
    user32 = ctypes.windll.user32
    found = []

    def cb(hwnd, _):
        if hwnd == exclude_hwnd:
            return True
        if exclude_pid is not None:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == exclude_pid:
                return True
        rect = window_rect(hwnd)
        if not rect:
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        left, top, right, bottom = rect
        if right - left < 160 or bottom - top < 100:
            return True
        try:  # 화면에 없는 UWP 유령 창 거르기
            cloaked = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), 4)
            if cloaked.value:
                return True
        except Exception:
            pass
        found.append((hwnd, left, top, right, bottom))
        return True

    try:
        user32.EnumWindows(_WNDENUMPROC(cb), 0)
    except Exception:
        return []
    return found


def work_area_at(x, y):
    """(x, y)가 속한 모니터의 작업 영역 — 작업표시줄을 뺀 사각형.

    작업표시줄이 어느 변에 있든(자동 숨김이면 화면 전체) 알아서 반영된다.
    """
    try:
        user32 = ctypes.windll.user32
        hmon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # NEAREST
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            w = mi.rcWork
            return w.left, w.top, w.right, w.bottom
    except Exception:
        pass
    return None

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def resize_rgba(im, size):
    """알파를 곱한 상태로 축소한다.

    un-premultiplied RGBA는 투명 픽셀의 RGB가 보통 검정이라, 그대로 축소하면
    그 검정이 가장자리로 번져 어두운 테두리가 생긴다.
    """
    if not HAS_NUMPY:
        return im.resize(size, Image.LANCZOS)
    a = np.asarray(im, dtype=np.float32) / 255.0
    alpha = a[..., 3:4]
    pm = np.concatenate([a[..., :3] * alpha, alpha], axis=-1)
    small = Image.fromarray((pm * 255.0 + 0.5).astype(np.uint8), "RGBA") \
                 .resize(size, Image.LANCZOS)
    b = np.asarray(small, dtype=np.float32) / 255.0
    alpha2 = b[..., 3:4]
    rgb = np.where(alpha2 > 0.0, b[..., :3] / np.maximum(alpha2, 1e-6), 0.0)
    out = np.concatenate([np.clip(rgb, 0.0, 1.0), alpha2], axis=-1)
    return Image.fromarray((out * 255.0 + 0.5).astype(np.uint8), "RGBA")


def body_bbox(mask):
    """정렬 기준이 될 몸통 영역.

    땀방울·반짝임 같은 작은 이펙트까지 넣어 경계를 잡으면, 그것이 나타났다 사라질 때마다
    중심이 밀려 캐릭터가 좌우로 흔들린다. 세로로 얇게 걸친 열은 빼고 잡는다.
    """
    box = mask.getbbox()
    if not box or not HAS_NUMPY:
        return box
    arr = np.asarray(mask, dtype=bool)
    cols = arr.sum(axis=0)
    if cols.max() <= 0:
        return box
    solid = np.nonzero(cols > max(2, cols.max() * 0.08))[0]
    if len(solid) == 0:
        return box
    return int(solid[0]), box[1], int(solid[-1]) + 1, box[3]


def seat_ratio(mask, bbox):
    """걸터앉은 자세에서 '앉는 면'이 몸의 어느 높이인지 0~1로 돌려준다.

    아래에서 위로 훑다가 폭이 다시 굵어지는 지점 = 늘어뜨린 다리가 끝나고
    몸통이 시작되는 곳. 그 선이 창 윗변에 닿아야 걸터앉은 모양이 된다.
    발이 바닥을 딛는 자세면 몸통이 맨 아래까지 이어져 1.0에 가깝게 나온다.
    """
    x0, y0, x1, y1 = bbox
    if y1 - y0 < 8 or not HAS_NUMPY:
        return 1.0
    arr = np.asarray(mask, dtype=bool)[y0:y1, x0:x1]
    widths = arr.sum(axis=1)
    if widths.max() <= 0:
        return 1.0
    thresh = widths.max() * 0.55
    for i in range(len(widths) - 1, -1, -1):
        if widths[i] >= thresh:
            return i / max(1, len(widths) - 1)
    return 1.0


class Sprite:
    """이미지 한 장 또는 GIF 애니메이션 프레임 묶음."""

    def __init__(self, frames, durations, boxes, seat=1.0, flipped=None,
                 align_top=False):
        # 위쪽(머리)을 기준으로 맞출지. 다리를 흔드는 동작은 발끝이 크게 변해서
        # 그걸 고정하면 몸통이 밀려 올라간다.
        self.align_top = align_top
        # 좌우 반전본. 걷는 그림처럼 방향이 있는 자세에만 만들어 둔다.
        self.flipped = flipped
        self.seat = seat                # 앉는 면 높이 (bbox 기준 0~1)
        self.frames = frames            # ImageTk.PhotoImage 리스트
        self.durations = durations      # 프레임별 지속 ms
        self.total = sum(durations) or 1
        self.width = frames[0].width()
        self.height = frames[0].height()
        # 투명 여백을 뺀 실제 그림 영역. 가장자리에 붙일 때 이 값을 기준으로 삼아야
        # 캔버스 여백만큼 붕 뜨지 않는다. 프레임마다 따로 갖고 있어야 애니메이션이
        # 흔들려도 닿는 지점을 고정할 수 있다.
        whole = (0, 0, self.width, self.height)
        self.boxes = [b or whole for b in boxes] or [whole]
        self.bbox = (min(b[0] for b in self.boxes), min(b[1] for b in self.boxes),
                     max(b[2] for b in self.boxes), max(b[3] for b in self.boxes))

    def frame(self, idx, flip=False):
        if flip and self.flipped:
            return self.flipped[0][idx]
        return self.frames[idx]

    def box(self, idx, flip=False):
        if flip and self.flipped:
            return self.flipped[1][idx]
        return self.boxes[min(idx, len(self.boxes) - 1)]

    def frame_index(self, elapsed_ms):
        if len(self.frames) == 1:
            return 0
        t = elapsed_ms % self.total
        acc = 0
        for i, d in enumerate(self.durations):
            acc += d
            if t < acc:
                return i
        return len(self.frames) - 1


def webp_frame_durations(path):
    """Pillow가 노출하지 않는 WebP ANMF 프레임 지속시간(ms)을 읽는다."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return []
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return []
    durations, pos = [], 12
    while pos + 8 <= len(data):
        kind = data[pos:pos + 4]
        size = int.from_bytes(data[pos + 4:pos + 8], "little")
        payload = pos + 8
        if kind == b"ANMF" and size >= 16 and payload + 15 <= len(data):
            durations.append(int.from_bytes(
                data[payload + 12:payload + 15], "little"))
        pos = payload + size + (size & 1)
    return durations


def load_sprite(stem, max_size, alpha_threshold, make_flipped=False):
    """assets/<stem>.(gif|png|webp|jpg) 를 찾아 키색 배경에 얹은 Sprite로 만든다.

    -transparentcolor 는 정확히 일치하는 색만 뚫으므로, 반투명 픽셀을 키색과
    알파 블렌딩하면 가장자리에 마젠타 테두리가 남는다. 그래서 알파를 임계값으로
    이진화해 합성한다.
    """
    if not HAS_PIL:
        return None
    path = None
    for ext in (".gif", ".png", ".webp", ".jpg", ".jpeg"):
        cand = os.path.join(ASSETS_DIR, stem + ext)
        if os.path.exists(cand):
            path = cand
            break
    if path is None:
        return None

    try:
        im = Image.open(path)
    except Exception:
        return None

    encoded_durations = webp_frame_durations(path) \
        if path.lower().endswith(".webp") else []
    frames, durations, boxes, seat = [], [], [], 1.0
    flip_frames, flip_boxes = [], []
    try:
        while True:
            fr = im.convert("RGBA")
            w, h = fr.size
            scale = min(max_size / max(w, h), 1.0) if max(w, h) else 1.0
            if scale < 1.0:
                fr = resize_rgba(fr, (max(1, int(w * scale)), max(1, int(h * scale))))
            r, g, b, a = fr.split()
            mask = a.point(lambda v: 255 if v >= alpha_threshold else 0)
            bg = Image.new("RGB", fr.size, TRANSPARENT_RGB)
            flat = Image.composite(Image.merge("RGB", (r, g, b)), bg, mask)
            frames.append(ImageTk.PhotoImage(flat))
            frame_no = len(frames) - 1
            duration = encoded_durations[frame_no] \
                if frame_no < len(encoded_durations) else im.info.get("duration", 100)
            durations.append(max(20, int(duration or 100)))
            fb = body_bbox(mask)
            if fb and not boxes:
                seat = seat_ratio(mask, fb)          # 첫 프레임 기준
            boxes.append(fb)
            if make_flipped:
                flip_frames.append(
                    ImageTk.PhotoImage(flat.transpose(Image.FLIP_LEFT_RIGHT)))
                fw = flat.size[0]
                flip_boxes.append((fw - fb[2], fb[1], fw - fb[0], fb[3]) if fb else fb)
            im.seek(im.tell() + 1)
    except EOFError:
        pass
    except Exception:
        if not frames:
            return None

    if not frames:
        return None
    flipped = (flip_frames, flip_boxes) if make_flipped and flip_frames else None
    return Sprite(frames, durations, boxes, seat, flipped)


def prefer_top(boxes):
    """이 동작을 위쪽(머리) 기준으로 맞춰야 하는지 정한다.

    발끝을 고정하면 다리를 흔드는 동작에서 그 움직임이 몸통을 위아래로 밀어 올린다.
    프레임 간 변동이 적은 쪽을 기준으로 삼으면 움직여야 할 곳만 움직인다.
    """
    good = [b for b in boxes if b]
    if len(good) < 2:
        return False
    tops = [b[1] for b in good]
    bottoms = [b[3] for b in good]
    return (max(tops) - min(tops)) < (max(bottoms) - min(bottoms))


def repeat_range(value):
    """`repeat` 값을 (최소, 최대) 횟수로 읽는다. `3`이면 고정, `[2, 5]`면 그 사이 무작위."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            lo, hi = int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return 1, 1
        lo, hi = max(1, min(lo, hi)), max(1, max(lo, hi))
        return lo, min(60, hi)
    try:
        n = max(1, min(60, int(value)))
    except (TypeError, ValueError):
        n = 1
    return n, n


def sequence_variants(items):
    """반복 구간의 가능한 횟수 조합만큼 시퀀스 변형을 만든다.

    재생할 때마다 그중 하나를 골라 쓰므로 같은 행동도 길이가 매번 조금씩 달라진다.
    조합이 너무 많아지지 않게 8가지로 제한한다.
    """
    lo, hi = 1, 1
    for item in items or ():
        if isinstance(item, dict):
            a, b = repeat_range(item.get("repeat", 1))
            lo, hi = min(lo, a) if lo != 1 else a, max(hi, b)
    if hi <= lo:
        return [expand_sequence(items)]
    counts = sorted(set(round(lo + (hi - lo) * i / 7) for i in range(8)))
    return [expand_sequence(items, forced=n) for n in counts]


def expand_sequence(items, depth=0, forced=None):
    """행동 시퀀스를 펼친다.

    ["03.png", 700] 처럼 프레임을 바로 적을 수도 있고,
    {"repeat": 3, "frames": [...]} 로 한 구간을 여러 번 되풀이할 수도 있다.
    `"repeat": [2, 5]` 처럼 범위로 적으면 재생마다 횟수가 달라진다.
    책 읽기·게임처럼 '하는 중'을 길게 보여줄 때 쓴다.
    """
    out = []
    for item in items or ():
        if isinstance(item, dict):
            if depth > 4:                       # 중첩이 지나치면 무시
                continue
            lo, hi = repeat_range(item.get("repeat", 1))
            times = max(lo, min(hi, forced)) if forced else random.randint(lo, hi)
            inner = expand_sequence(item.get("frames", ()), depth + 1, forced)
            out.extend(inner * times)
        else:
            out.append(item)
    return out


def load_sit_actions(max_size, alpha_threshold):
    """sit_actions/actions.json의 PNG 시퀀스를 단발 행동 묶음으로 읽는다."""
    if not HAS_PIL or not os.path.exists(SIT_ACTIONS_CONFIG):
        return {}, (18.0, 40.0)
    try:
        with open(SIT_ACTIONS_CONFIG, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}, (18.0, 40.0)

    raw_interval = manifest.get("interval_seconds", (18, 40))
    try:
        lo, hi = float(raw_interval[0]), float(raw_interval[1])
        interval = (max(3.0, min(lo, hi)), max(3.0, max(lo, hi)))
    except (TypeError, ValueError, IndexError):
        interval = (18.0, 40.0)

    actions = {}
    for name, spec in manifest.get("actions", {}).items():
        if not isinstance(name, str) or not isinstance(spec, dict):
            continue
        action_dir = os.path.join(SIT_ACTIONS_DIR, os.path.basename(name))
        cache = {}

        def load_frame(filename):
            """이미지는 한 번만 읽어 변형끼리 나눠 쓴다."""
            path = os.path.join(action_dir, filename)
            if path not in cache:
                try:
                    fr = Image.open(path).convert("RGBA")
                except (OSError, ValueError):
                    return None
                w, h = fr.size
                scale = min(max_size / max(w, h), 1.0) if max(w, h) else 1.0
                if scale < 1.0:
                    fr = resize_rgba(
                        fr, (max(1, int(w * scale)), max(1, int(h * scale))))
                r, g, b, a = fr.split()
                mask = a.point(lambda v: 255 if v >= alpha_threshold else 0)
                bg = Image.new("RGB", fr.size, TRANSPARENT_RGB)
                flat = Image.composite(Image.merge("RGB", (r, g, b)), bg, mask)
                cache[path] = (ImageTk.PhotoImage(flat), body_bbox(mask))
            return cache[path]

        variants = []
        for sequence in sequence_variants(spec.get("sequence", ())):
            frames, durations, boxes = [], [], []
            for item in sequence:
                try:
                    filename, duration = item
                    filename = os.path.basename(str(filename))
                    duration = max(20, int(duration))
                except (TypeError, ValueError):
                    continue
                got = load_frame(filename)
                if not got:
                    continue
                image, box = got
                frames.append(image)
                durations.append(duration)
                boxes.append(box)
            if frames:
                variants.append(Sprite(frames, durations, boxes,
                                       align_top=prefer_top(boxes)))
        if variants:
            weight = max(0.0, float(spec.get("weight", 1.0)))
            actions[name] = (variants, weight)
    return actions, interval


def assets_stamp():
    """assets 폴더 변경 감지용 지문 — 파일명+mtime+크기."""
    try:
        items = []
        for folder, dirs, files in os.walk(ASSETS_DIR):
            dirs.sort()
            for n in sorted(files):
                p = os.path.join(folder, n)
                st = os.stat(p)
                items.append((os.path.relpath(p, ASSETS_DIR),
                              int(st.st_mtime), st.st_size))
        return tuple(items)
    except OSError:
        return ()


class ClaudePet:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", TRANSPARENT)
        self.root.configure(bg=TRANSPARENT)

        self.config = self._load_config()
        self.sprites = {}
        self._stamp = ()
        self._reload_sprites()

        self.canvas = tk.Canvas(self.root, width=self.W, height=self.H,
                                bg=TRANSPARENT, highlightthickness=0)
        self.canvas.pack()
        self._place_window()
        self.root.update_idletasks()
        try:
            self._hwnd = int(self.root.wm_frame(), 16)
        except Exception:
            self._hwnd = 0

        self.queue = []           # 대기 중인 이벤트 문자열
        self.bubble_text = None
        self.bubble_until = 0.0

        self.t0 = time.time()
        self.bounce_t = -10.0     # 마지막 바운스 시작 시각
        self.blink_until = 0.0
        self.next_blink = time.time() + random.uniform(2, 5)
        self.next_asset_check = time.time() + 3
        self.next_resnap = time.time() + 5
        self.sit_action = None
        self.last_sit_action = None
        self.next_sit_action = time.time() + random.uniform(*self.sit_action_interval)

        self._anim = None         # 스냅 활공 (x0, y0, x1, y1, step)
        self.fall = None          # 낙하 (목표 y, 착지할 창, 현재 속도)
        self.facing = 1           # 바라보는 쪽 (1=오른쪽, -1=왼쪽)
        self.wander_to = None     # 거닐어 갈 목표 x
        self.next_wander = time.time() + random.uniform(*WANDER_EVERY)
        self.perch = None         # 올라앉은 창의 HWND
        self.perch_edge = "top"   # 창의 어느 변에 붙었나 (top=앉기, bottom=매달리기)
        self.perch_dx = 0
        self.last_active = time.time()
        self._press = None
        self._moved = False
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_menu)

        self._open_events()
        self._tick()

    # ---------- 외형 ----------
    def _reload_sprites(self):
        """assets/ 를 다시 읽고 창 크기를 스프라이트에 맞춘다."""
        self._stamp = assets_stamp()
        size = int(self.config.get("sprite_size", 150))
        # 128 = 알파 50%에서 자른다. 낮추면 옅은 그림자/글로우가 불투명 얼룩으로 남고,
        # 높이면 안티에일리어싱 가장자리가 깎여 실루엣이 얇아진다.
        threshold = int(self.config.get("alpha_threshold", 128))
        self.sprites = {}
        for stem in POSES:
            sp = load_sprite(stem, size, threshold, make_flipped=stem in DIRECTIONAL)
            if sp:
                self.sprites[stem] = sp
        if "idle" not in self.sprites:  # pet.png 도 허용
            sp = load_sprite("pet", size, threshold)
            if sp:
                self.sprites["idle"] = sp
        self.sit_actions, self.sit_action_interval = load_sit_actions(size, threshold)
        current = getattr(self, "sit_action", None)
        if current and current[0] not in self.sit_actions:
            self.sit_action = None

        base = self.sprites.get("idle")
        pet_w = base.width if base else VECTOR_SIZE
        pet_h = base.height if base else VECTOR_SIZE
        for sp in self.sprites.values():
            pet_w, pet_h = max(pet_w, sp.width), max(pet_h, sp.height)
        for sp, _ in self.sit_actions.values():
            pet_w, pet_h = max(pet_w, sp.width), max(pet_h, sp.height)
        self.pet_w, self.pet_h = pet_w, pet_h
        self.W = max(330, pet_w + 80)   # 말풍선이 들어갈 폭까지 확보
        # 말풍선 자리를 위아래 양쪽에 둔다. 창 꼭대기에 앉으면 위쪽이 화면 밖으로
        # 나가므로 그때는 아래쪽에 띄운다.
        self.H = BUBBLE_ZONE + pet_h + BUBBLE_ZONE
        self.pet_cx = self.W // 2
        self.pet_cy = BUBBLE_ZONE + pet_h // 2
        self._measure_body()

    def _measure_body(self):
        """캐릭터의 실제 외곽(투명 여백 제외)을 창 좌표로 환산해 둔다.

        기준은 서 있는 자세 하나뿐이다. 포즈마다 bbox를 합치면 눕기처럼 폭이
        다른 그림이 섞일 때 기준선이 밀리므로, 모든 포즈는 같은 캔버스에 같은
        바닥선으로 그려져 있어야 한다.
        """
        base = self.sprites.get("idle") or next(iter(self.sprites.values()), None)
        if base:
            x0, y0, x1, y1 = base.bbox
            sx = self.pet_cx - base.width // 2
            sy = self.pet_cy - base.height // 2
        else:
            x0, y0, x1, y1 = 0, 0, VECTOR_SIZE, VECTOR_SIZE
            sx = self.pet_cx - VECTOR_SIZE // 2
            sy = self.pet_cy - VECTOR_SIZE // 2
        self.body_left = sx + x0
        self.body_right = sx + x1
        self.body_top = sy + y0
        self.body_bottom = sy + y1
        self._base_bbox = (x0, y0, x1, y1)
        self._base_size = (base.width, base.height) if base else (VECTOR_SIZE, VECTOR_SIZE)

        # 걸터앉기: 발끝이 아니라 '앉는 면'이 창 윗변에 닿아야 한다.
        self.seat_line = self.body_bottom
        sit = self.sprites.get("sit")
        if sit:
            override = self.config.get("sit_anchor")
            ratio = float(override) if override is not None else sit.seat
            _, sy0, _, sy1 = sit.boxes[0]
            dx, dy = self._align(sit, 0)
            top = self.pet_cy - sit.height // 2 + sy0 + dy
            self.seat_line = int(top + (sy1 - sy0) * ratio)

    def _align(self, sp, idx=0, from_top=False, flip=False):
        """포즈 그림을 서 있는 자세의 기준선에 맞추는 보정값.

        보통은 발바닥을 맞추지만, 매달리는 자세는 손끝(위쪽)을 맞춘다. 프레임마다
        따로 계산하므로 애니메이션이 흔들려도 닿는 지점은 고정된다 — 매달린 손은
        창에 붙어 있고 몸만 대롱거리게 된다.
        """
        if sp.width != self._base_size[0] or sp.height != self._base_size[1]:
            return 0, 0
        bx0, by0, bx1, by1 = self._base_bbox
        x0, y0, x1, y1 = sp.box(idx, flip)
        dy = (by0 - y0) if from_top else (by1 - y1)
        return ((bx0 + bx1) - (x0 + x1)) // 2, dy

    def _place_window(self):
        x = self.config.get("x")
        y = self.config.get("y")
        if x is None or y is None:
            # 첫 실행: 오른쪽 아래 작업표시줄 위에 세워 둔다
            x = self.root.winfo_screenwidth() - self.W - 24
            y = self.root.winfo_screenheight() - self.H
            self.config["snap_y"] = "bottom"
        x, y = self._resnap(x, y)
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    # ---------- 마그넷 스냅 ----------
    def _edge_positions(self, x, y):
        """현재 모니터 작업영역에 몸을 딱 붙였을 때의 창 좌표."""
        area = work_area_at(x + self.W // 2, y + self.pet_cy)
        if not area:
            return None
        left, top, right, bottom = area
        return {
            "left": left - self.body_left,
            "right": right - self.body_right,
            "top": top - self.body_top,
            "bottom": bottom - self.body_bottom,
        }

    def _resnap(self, x, y):
        """저장된 스냅 방향이 있으면 현재 작업영역 기준으로 다시 붙인다.

        작업표시줄 크기가 바뀌거나 해상도가 달라져도 계속 붙어 있게 한다.
        """
        pos = self._edge_positions(x, y)
        if not pos:
            return x, y
        sx, sy = self.config.get("snap_x"), self.config.get("snap_y")
        if sx in ("left", "right"):
            x = pos[sx]
        if sy in ("top", "bottom"):
            y = pos[sy]
        return x, y

    # ---------- 창에 앉기 / 매달리기 ----------
    def _find_perch(self, x, y):
        """놓은 자리 근처에 창의 위·아랫변이 있으면 (hwnd, edge, 창좌표)를 준다.

        윗변이면 그 위에 올라앉고, 아랫변이면 거기 매달린다.
        """
        area = work_area_at(x + self.W // 2, y + self.pet_cy)
        limit_top = area[1] if area else 0
        seat = y + self.seat_line            # 걸터앉을 때 몸이 닿는 화면 y
        head = y + self.body_top             # 머리끝의 화면 y
        cx = x + (self.body_left + self.body_right) // 2
        for win in perchable_windows(self._hwnd, os.getpid()):
            hwnd, left, top, right, bottom = win
            if not (left - 40 <= cx <= right + 40):
                continue
            if top >= limit_top + 10 and abs(top - seat) <= SNAP_DIST:
                return hwnd, "top", self._perch_pos(x, win, "top")
            if abs(bottom - head) <= SNAP_DIST:
                return hwnd, "bottom", self._perch_pos(x, win, "bottom")
        return None, None, None

    def _perch_pos(self, x, win, edge):
        """창 변에 몸을 붙이는 창 좌표. 캐릭터가 창 밖으로 새지 않게 가둔다."""
        _, left, top, right, bottom = win
        lo = left - self.body_left + 6
        hi = right - self.body_right - 6
        if hi < lo:
            lo = hi = (left + right) // 2 - (self.body_left + self.body_right) // 2
        y = (top - self.seat_line) if edge == "top" else (bottom - self.body_top)
        return max(lo, min(hi, x)), y

    def _sit_on(self, hwnd, edge, pos):
        self.perch = hwnd
        self.perch_edge = edge
        rect = window_rect(hwnd)
        self.perch_dx = pos[0] - rect[0] if rect else 0
        self.config["snap_x"] = self.config["snap_y"] = None

    def _leave_perch(self):
        """앉아 있던 창이 사라지면 바닥으로 내려온다."""
        self.perch = None
        self.config["snap_y"] = "bottom"
        x, y = self._resnap(self.root.winfo_x(), self.root.winfo_y())
        self.config["x"], self.config["y"] = x, y
        self._glide_to(x, y)
        self._save_config()

    def _track_perch(self):
        """앉은 창을 따라 움직인다. 창이 닫히거나 최소화되면 내려온다."""
        rect = window_rect(self.perch)
        if not rect:
            self._leave_perch()
            return
        left, top, right, bottom = rect
        x, y = self._perch_pos(left + self.perch_dx,
                               (self.perch, left, top, right, bottom),
                               self.perch_edge)
        if (x, y) != (self.root.winfo_x(), self.root.winfo_y()):
            self.root.geometry(f"+{x}+{y}")

    def _snap_from_drag(self, x, y):
        """드래그를 놓은 자리에서 가까운 가장자리를 찾아 붙인다."""
        hwnd, edge, pos = self._find_perch(x, y)
        if hwnd:
            self._sit_on(hwnd, edge, pos)
            return pos
        self.perch = None
        pos = self._edge_positions(x, y)
        if not pos:
            return x, y
        best_x = min(("left", "right"), key=lambda k: abs(pos[k] - x))
        best_y = min(("top", "bottom"), key=lambda k: abs(pos[k] - y))
        if abs(pos[best_x] - x) <= SNAP_DIST:
            x, self.config["snap_x"] = pos[best_x], best_x
        else:
            self.config["snap_x"] = None
        if abs(pos[best_y] - y) <= SNAP_DIST:
            y, self.config["snap_y"] = pos[best_y], best_y
        else:
            self.config["snap_y"] = None
        return x, y

    def _glide_to(self, x, y):
        """스냅 위치까지 부드럽게 미끄러져 붙는다."""
        cx = self.root.winfo_x()
        if abs(x - cx) > 6:
            self.facing = 1 if x > cx else -1
        self._anim = (cx, self.root.winfo_y(), x, y, 0)

    # ---------- 공중에서 떨어지기 ----------
    def _landing_spot(self, x, y):
        """이 자리에서 떨어지면 닿는 곳 — (창 y, 창 hwnd). 창이 없으면 바닥."""
        cx = x + (self.body_left + self.body_right) // 2
        best_y, best_hwnd = None, None
        for hwnd, left, top, right, _ in perchable_windows(self._hwnd, os.getpid()):
            if not (left - 20 <= cx <= right + 20):
                continue
            cand = top - self.seat_line          # 그 창에 걸터앉는 높이
            if cand >= y and (best_y is None or cand < best_y):
                best_y, best_hwnd = cand, hwnd
        area = work_area_at(cx, y + self.pet_cy)
        if area:
            floor = area[3] - self.body_bottom   # 작업표시줄 위 바닥
            if best_y is None or floor < best_y:
                if floor >= y:
                    best_y, best_hwnd = floor, None
        return best_y, best_hwnd

    def _start_fall(self, x, y):
        """놓은 자리가 허공이면 떨어뜨린다. 닿을 곳이 없으면 제자리에 둔다."""
        target, hwnd = self._landing_spot(x, y)
        if target is None or target <= y:
            return False
        self.perch = None
        self.wander_to = None
        self.fall = (target, hwnd, 0.0)
        return True

    def _step_fall(self):
        target, hwnd, speed = self.fall
        speed = min(speed + GRAVITY, MAX_FALL)
        y = self.root.winfo_y() + int(speed)
        x = self.root.winfo_x()
        if y >= target:                          # 착지
            self.fall = None
            if hwnd and window_rect(hwnd):
                self._sit_on(hwnd, "top", (x, target))
                self.root.geometry(f"+{x}+{target}")
            else:
                self.config["snap_y"] = "bottom"
                x, ny = self._resnap(x, target)
                self.root.geometry(f"+{x}+{ny}")
                self.config["x"], self.config["y"] = x, ny
            self._save_config()
        else:
            self.fall = (target, hwnd, speed)
            self.root.geometry(f"+{x}+{y}")

    # ---------- 가끔 거닐기 ----------
    def _wander_bounds(self):
        """좌우로 오갈 수 있는 창 x 범위. 서 있는 바닥이나 올라앉은 창의 폭이다."""
        if self.perch:
            rect = window_rect(self.perch)
            if not rect:
                return None
            lo, hi = rect[0] - self.body_left + 6, rect[2] - self.body_right - 6
        else:
            area = work_area_at(self.root.winfo_x() + self.W // 2,
                                self.root.winfo_y() + self.pet_cy)
            if not area:
                return None
            lo, hi = area[0] - self.body_left + 4, area[2] - self.body_right - 4
        return (lo, hi) if hi > lo else None

    def _may_wander(self, now):
        """알림도 없고 눕지도 않은, 서 있거나 앉아 있는 평온한 상태에서만 거닌다."""
        if self._press or self._anim or self.wander_to is not None or self.sit_action:
            return False
        if not self.config.get("wander", True):
            return False
        if (now - self.bounce_t) < 2.0 or self.queue or self.bubble_text:
            return False
        if (now - self.last_active) > IDLE_LIE_SECONDS:   # 누워 있으면 그대로 둔다
            return False
        return self.perch_edge == "top" if self.perch \
            else self.config.get("snap_y") != "top"

    def _start_wander(self, now):
        bounds = self._wander_bounds()
        self.next_wander = now + random.uniform(*WANDER_EVERY)
        if not bounds:
            return
        x = self.root.winfo_x()
        ticks = int(random.uniform(*WANDER_TIME) * 1000 / TICK_MS)
        step = ticks * WANDER_SPEED * random.choice((-1, 1))
        target = max(bounds[0], min(bounds[1], x + step))
        if abs(target - x) >= 12:                # 몇 픽셀 꿈틀대는 건 의미 없다
            self.wander_to = target
            self.facing = 1 if target > x else -1
            self.config["snap_x"] = None         # 가로로 움직였으니 벽 붙임은 해제

    def _step_wander(self, now):
        x = self.root.winfo_x()
        gap = self.wander_to - x
        if abs(gap) <= WANDER_SPEED:
            nx, self.wander_to = self.wander_to, None
            self.next_wander = now + random.uniform(*WANDER_EVERY)
            self._save_config()
        else:
            nx = x + (WANDER_SPEED if gap > 0 else -WANDER_SPEED)
        self.root.geometry(f"+{nx}+{self.root.winfo_y()}")
        if self.perch:
            rect = window_rect(self.perch)
            if rect:
                self.perch_dx = nx - rect[0]     # 창을 따라다닐 기준도 같이 옮긴다
        else:
            self.config["x"] = nx

    def _check_assets(self):
        """이미지를 새로 넣거나 바꾸면 재시작 없이 반영."""
        if assets_stamp() == self._stamp:
            return
        self.config["x"] = self.root.winfo_x()
        self.config["y"] = self.root.winfo_y()
        self._reload_sprites()
        self.canvas.config(width=self.W, height=self.H)
        self._place_window()
        # 창 크기를 바꾸면 Windows가 투명색 키를 놓쳐 창 전체가 사라진다. 다시 걸어준다.
        self.root.update_idletasks()
        self.root.attributes("-transparentcolor", TRANSPARENT)

    # ---------- 앉아서 하는 짧은 행동 ----------
    def _may_sit_action(self, now):
        if not self.config.get("sit_actions", True) or not self.sit_actions:
            return False
        if not self.perch or self.perch_edge != "top":
            return False
        if self._press or self._anim or self.wander_to is not None:
            return False
        if (now - self.bounce_t) < 2.0 or self.queue or self.bubble_text:
            return False
        return (now - self.last_active) < IDLE_SLEEP_SECONDS

    def _start_sit_action(self, now):
        choices = [(name, entry) for name, entry in self.sit_actions.items()
                   if name != self.last_sit_action or len(self.sit_actions) == 1]
        if not choices:
            return
        weights = [entry[1] for _, entry in choices]
        if not any(weights):
            weights = None
        name, (variants, _) = random.choices(choices, weights=weights, k=1)[0]
        pick = random.randrange(len(variants))      # 길이가 매번 조금씩 달라진다
        sprite = variants[pick]
        self.sit_action = (name, now, pick)
        self.last_sit_action = name
        self.next_sit_action = (
            now + sprite.total / 1000.0 + random.uniform(*self.sit_action_interval))

    def _update_sit_action(self, now):
        if self.sit_action:
            name, started, pick = self.sit_action
            entry = self.sit_actions.get(name)
            if (not entry or not self._may_sit_action(now)
                    or (now - started) * 1000 >= entry[0][pick].total):
                self.sit_action = None
        elif now >= self.next_sit_action and self._may_sit_action(now):
            self._start_sit_action(now)
        self.root.attributes("-topmost", True)

    # ---------- 설정 ----------
    def _load_config(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"sound": True}

    def _save_config(self):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------- 이벤트 파일 tail ----------
    # 파일 핸들을 계속 들고 있으면 Windows 텍스트 모드에서 EOF 이후
    # append 분을 못 읽는 경우가 있어, offset 기억 + 매번 재오픈 방식을 쓴다.
    def _open_events(self):
        if not os.path.exists(EVENTS_PATH):
            open(EVENTS_PATH, "a", encoding="utf-8").close()
        self._offset = os.path.getsize(EVENTS_PATH)  # 과거 이벤트는 무시

    def _poll_events(self):
        try:
            size = os.path.getsize(EVENTS_PATH)
        except OSError:
            return
        if size < self._offset:
            self._offset = 0  # 밖에서 파일이 비워짐
        if size == self._offset:
            return
        try:
            with open(EVENTS_PATH, encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                chunk = f.read()
                self._offset = f.tell()
        except OSError:
            return
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            self._notify(self._format(evt))

    @staticmethod
    def _format(evt):
        proj = os.path.basename((evt.get("cwd") or "").rstrip("\\/"))
        name = (evt.get("session_name") or "").strip()
        msg = (evt.get("message") or "").strip()
        etype = evt.get("type", "")
        if not msg:
            if etype == "stop":
                msg = "응답이 끝났어요! 확인해 주세요 ✨"
            elif etype == "notification":
                msg = "Claude가 기다리고 있어요!"
            else:
                msg = "새 알림이 왔어요"
        home = os.path.basename(os.path.expanduser("~").rstrip("\\/"))
        if proj.lower() == home.lower():
            proj = ""  # 홈 디렉토리는 프로젝트명으로 의미 없음
        tag = name or proj
        return f"[{tag}] {msg}" if tag else msg

    def _notify(self, text):
        self.queue.append(text)
        self.bounce_t = self.last_active = time.time()
        self.wander_to = None            # 알림이 왔으면 산책은 멈추고 알린다
        self.sit_action = None
        if self.config.get("sound", True):
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        if self.bubble_text is None:
            self._show_next()

    def _show_next(self):
        if self.queue:
            self.bubble_text = self.queue.pop(0)
            self.bubble_until = time.time() + BUBBLE_SECONDS
        else:
            self.bubble_text = None

    # ---------- 입력 ----------
    def _on_press(self, e):
        self._press = (e.x_root, e.y_root,
                       self.root.winfo_x(), self.root.winfo_y())
        self._moved = False
        self.last_active = time.time()
        self.wander_to = None
        self.sit_action = None
        self.next_sit_action = time.time() + random.uniform(*self.sit_action_interval)

    def _on_drag(self, e):
        if not self._press:
            return
        px, py, wx, wy = self._press
        dx, dy = e.x_root - px, e.y_root - py
        if abs(dx) + abs(dy) > 3:
            self._moved = True
        self.root.geometry(f"+{wx + dx}+{wy + dy}")

    def _on_release(self, e):
        if self._moved:
            cx, cy = self.root.winfo_x(), self.root.winfo_y()
            x, y = self._snap_from_drag(cx, cy)
            if (x, y) == (cx, cy) and not self.perch and self._start_fall(cx, cy):
                self._press = None       # 붙을 곳이 없으면 떨어진다
                return
            self.config["x"], self.config["y"] = x, y
            self._glide_to(x, y)
            self._save_config()
        else:
            if self.bubble_text is not None:
                self._show_next()  # 클릭 = 현재 말풍선 넘기기
            else:
                self.bounce_t = time.time()  # 심심할 때 클릭하면 폴짝
        self._press = None

    def _on_menu(self, e):
        m = tk.Menu(self.root, tearoff=0)
        m.add_command(label="테스트 알림",
                      command=lambda: self._notify("[claude-pet] 안녕하세요! 저 여기 있어요 🐾"))
        sound_on = self.config.get("sound", True)
        m.add_command(label="소리 끄기" if sound_on else "소리 켜기", command=self._toggle_sound)
        walk_on = self.config.get("wander", True)
        m.add_command(label="산책 끄기" if walk_on else "산책 켜기", command=self._toggle_wander)
        actions_on = self.config.get("sit_actions", True)
        m.add_command(label="앉기 모션 끄기" if actions_on else "앉기 모션 켜기",
                      command=self._toggle_sit_actions)
        m.add_command(label="알림 모두 지우기", command=self._clear_all)
        m.add_separator()
        m.add_command(label="이미지 다시 읽기", command=self._force_reload)
        m.add_command(label="종료", command=self._quit)
        m.tk_popup(e.x_root, e.y_root)

    def _toggle_sound(self):
        self.config["sound"] = not self.config.get("sound", True)
        self._save_config()

    def _toggle_wander(self):
        self.config["wander"] = not self.config.get("wander", True)
        self.wander_to = None
        self._save_config()

    def _toggle_sit_actions(self):
        self.config["sit_actions"] = not self.config.get("sit_actions", True)
        self.sit_action = None
        self.next_sit_action = time.time() + random.uniform(*self.sit_action_interval)
        self._save_config()

    def _clear_all(self):
        self.queue.clear()
        self.bubble_text = None

    def _force_reload(self):
        self._stamp = ()
        self._check_assets()

    def _quit(self):
        self._save_config()
        self.root.destroy()

    # ---------- 루프/그리기 ----------
    def _step_anim(self):
        """스냅 활공 한 프레임. 끝에서 감속하는 ease-out."""
        if not self._anim:
            return
        x0, y0, x1, y1, step = self._anim
        step += 1
        k = 1.0 - (1.0 - step / SNAP_FRAMES) ** 3
        nx = int(round(x0 + (x1 - x0) * k))
        ny = int(round(y0 + (y1 - y0) * k))
        self.root.geometry(f"+{nx}+{ny}")
        self._anim = None if step >= SNAP_FRAMES else (x0, y0, x1, y1, step)

    def _tick(self):
        try:
            self._poll_events()
            now = time.time()
            if self.fall:
                if self._press:
                    self.fall = None     # 다시 집으면 낙하 취소
                else:
                    self._step_fall()
            elif self._anim:
                self._step_anim()
            elif self.perch:
                if not self._press:
                    self._track_perch()
                    if self.wander_to is not None:
                        self._step_wander(now)
            elif self.wander_to is not None and not self._press:
                self._step_wander(now)
            elif not self._press and now > self.next_resnap:
                # 작업표시줄 크기 변경·해상도 변경에도 계속 붙어 있도록
                self.next_resnap = now + 5
                cx, cy = self.root.winfo_x(), self.root.winfo_y()
                nx, ny = self._resnap(cx, cy)
                if (nx, ny) != (cx, cy):
                    self.root.geometry(f"+{nx}+{ny}")
                    self.config["x"], self.config["y"] = nx, ny
            self._update_sit_action(now)
            if now > self.next_wander and self._may_wander(now):
                self._start_wander(now)
            if now > self.next_asset_check:
                self.next_asset_check = now + 3
                self._check_assets()
            if now > self.next_blink:
                self.blink_until = now + 0.15
                self.next_blink = now + random.uniform(2.5, 6.0)
            if self.bubble_text is not None and now >= self.bubble_until:
                self._show_next()
            self._draw()
        except Exception:
            # 그리기 한 프레임이 죽어도 펫 자체는 계속 살아 있어야 한다
            import traceback
            try:
                with open(os.path.join(BASE, "pet_error.log"), "a", encoding="utf-8") as f:
                    f.write(traceback.format_exc() + "\n")
            except Exception:
                pass
        self.root.after(TICK_MS, self._tick)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        now = time.time()
        t = now - self.t0

        # 상시 부유는 쓰지 않는다 — 가장자리에 붙어 서 있는 게 기본.
        bounce = 0.0
        bt = now - self.bounce_t
        if 0 <= bt < 1.2:
            bounce = 26 * abs(math.sin(bt * math.pi * 3)) * (1.2 - bt) / 1.2
        cy = self.pet_cy - bounce

        if self.sprites:
            self._draw_sprite(c, cy, t, now)
        else:
            self._draw_vector(c, cy, t, now)

        # 미확인 알림 뱃지
        if self.queue:
            bx = self.pet_cx + self.pet_w // 2 - 8
            by = cy - self.pet_h // 2 + 8
            c.create_oval(bx - 11, by - 11, bx + 11, by + 11,
                          fill=BADGE, outline="white", width=2)
            c.create_text(bx, by, text=str(min(len(self.queue), 9)),
                          fill="white", font=("Malgun Gothic", 9, "bold"))

        if self.bubble_text is not None:
            area = work_area_at(self.root.winfo_x() + self.W // 2,
                                self.root.winfo_y() + self.pet_cy)
            below = bool(area) and self.root.winfo_y() < area[1]
            self._draw_bubble(c, cy, below)

    def _pick(self, *names):
        """앞에서부터 있는 스프라이트를 (이름, 그림)으로 고른다. 없으면 뒤 것으로 대체."""
        for n in names:
            if n in self.sprites:
                return n, self.sprites[n]
        if "idle" in self.sprites:
            return "idle", self.sprites["idle"]
        return next(iter(self.sprites.items()))

    def _pose(self, now):
        """지금 상황에 맞는 포즈 이름을 순위대로 나열한다.

        앞의 이름부터 찾아 있는 것을 쓰므로, 없는 포즈는 뒤 것으로 대체된다.
        """
        if self.fall:
            return ("fall", "drag", "idle")
        if self._anim or self.wander_to is not None:
            return ("walk", "idle")
        if self._press and self._moved:
            return ("drag", "idle")
        if self.perch:
            hold = ("hang", "idle") if self.perch_edge == "bottom" else ("sit", "idle")
        elif self.config.get("snap_y") == "top":
            hold = ("hang", "idle")
        else:
            hold = ("idle",)
        if (now - self.bounce_t) < 1.2:
            # 알림이 온 순간. 그 자세로 놀라는 그림이 있으면 그걸 쓰고, 없으면 서 있는
            # 놀란 그림으로 대신한다 — 알림은 눈에 띄는 편이 우선이다.
            surprise = NOTIFY_OF.get(hold[0])
            return ((surprise,) if surprise else ()) + ("notify",) + hold
        idle_for = now - self.last_active
        # 눕는 건 바닥에 서 있을 때만. 매달리거나 걸터앉은 채로 누우면 허공에 드러눕는다.
        grounded = not self.perch and self.config.get("snap_y") != "top"
        if grounded and idle_for > IDLE_SLEEP_SECONDS:
            hold = ("sleep", "prone", "lie") + hold
        elif grounded and idle_for > IDLE_LIE_SECONDS:
            hold = ("lie", "prone") + hold
        elif idle_for > IDLE_SLEEP_SECONDS and SLEEP_OF.get(hold[0]):
            hold = (SLEEP_OF[hold[0]],) + hold   # 앉거나 매달린 채로 졸기
        if now >= self.blink_until:
            return hold
        # 깜빡이는 중: 자세마다 그 자세의 눈감은 그림을 먼저 찾는다. 없으면 눈 뜬
        # 같은 자세를 쓴다 — 자세가 맞는 편이 눈을 감는 것보다 중요하다.
        chain = []
        for h in hold:
            if BLINK_OF.get(h):
                chain.append(BLINK_OF[h])
            chain.append(h)
        return tuple(chain)

    def _draw_sprite(self, c, cy, t, now):
        """사용자 이미지 모드 — 상황에 맞는 포즈를 골라 그린다."""
        if self.sit_action:
            action_name, started, pick = self.sit_action
            entry = self.sit_actions.get(action_name)
            if entry and pick < len(entry[0]):
                sp = entry[0][pick]
                idx = sp.frame_index(int((now - started) * 1000))
                # 행동 그림은 프레임마다 캐릭터가 다른 자리에 그려져 있다. 한 장을
                # 기준으로 고정하면 재생 내내 좌우로 흔들리므로 프레임마다 맞춘다.
                dx, dy = self._align(sp, idx, sp.align_top)
                c.create_image(self.pet_cx + dx, cy + dy, image=sp.frames[idx],
                               anchor="center")
                return
        name, sp = self._pick(*self._pose(now))
        idx = sp.frame_index(int(t * 1000))
        # 걷는 그림은 오른쪽을 향해 그려져 있다. 왼쪽으로 갈 땐 뒤집어야 뒷걸음질로
        # 보이지 않는다.
        flip = name in DIRECTIONAL and self.facing < 0
        dx, dy = self._align(sp, idx, name in TOP_ALIGNED, flip)
        c.create_image(self.pet_cx + dx, cy + dy, image=sp.frame(idx, flip),
                       anchor="center")

    def _draw_vector(self, c, cy, t, now):
        """내장 벡터 펫 — assets/ 가 비었을 때의 기본 외형."""
        n = 9
        R = 52
        r = 40
        rot = t * 0.35
        pts = []
        for i in range(n * 2):
            ang = math.pi * i / n + rot
            rad = R if i % 2 == 0 else r
            pts.append(self.pet_cx + rad * math.cos(ang))
            pts.append(cy + rad * math.sin(ang))
        c.create_polygon(pts, fill=CLAY, outline=CLAY_DARK, width=2, smooth=True)
        fr = 33  # 얼굴판은 회전하지 않게 위에 고정
        c.create_oval(self.pet_cx - fr, cy - fr, self.pet_cx + fr, cy + fr,
                      fill=CLAY, outline="")

        eyy = cy - 4
        if now < self.blink_until:
            for dx in (-12, 12):
                c.create_line(self.pet_cx + dx - 5, eyy, self.pet_cx + dx + 5, eyy,
                              fill=INK, width=2, capstyle="round")
        else:
            for dx in (-12, 12):
                c.create_oval(self.pet_cx + dx - 4, eyy - 6, self.pet_cx + dx + 4, eyy + 6,
                              fill=INK, outline="")
                c.create_oval(self.pet_cx + dx - 2, eyy - 4, self.pet_cx + dx + 1, eyy - 1,
                              fill="white", outline="")
        c.create_arc(self.pet_cx - 7, cy + 2, self.pet_cx + 7, cy + 14,
                     start=200, extent=140, style="arc", outline=INK, width=2)
        for dx in (-23, 23):
            c.create_oval(self.pet_cx + dx - 6, cy + 4, self.pet_cx + dx + 6, cy + 11,
                          fill=BLUSH, outline="")

    def _draw_bubble(self, c, cy, below=False):
        # 창 끝이 아니라 몸을 기준으로 잡아 짧은 문구도 머리 바로 옆에 붙는다.
        # 폴짝 뛸 때도 같은 간격을 유지하도록 펫이 움직인 만큼 같이 옮긴다.
        shift = cy - self.pet_cy
        font = ("Malgun Gothic", 9)
        if below:
            top = self.body_bottom + shift + BUBBLE_GAP + 12
            tid = c.create_text(self.W // 2, top + 10, text=self.bubble_text,
                                anchor="n", width=self.W - 56, font=font,
                                fill=INK, justify="center")
        else:
            bottom = self.body_top + shift - BUBBLE_GAP - 12
            tid = c.create_text(self.W // 2, bottom - 10, text=self.bubble_text,
                                anchor="s", width=self.W - 56, font=font,
                                fill=INK, justify="center")
            # 말풍선이 창 위로 넘치면 들어오게 밀어 준다
            over = 4 - (c.bbox(tid)[1] - 10)
            if over > 0:
                c.move(tid, 0, over)
        pad = 10
        # 긴 문구가 창 밖으로 잘리지 않게 좌우로 밀어 넣는다. 꼬리는 펫 위에 그대로 둔다.
        b = c.bbox(tid)
        nudge = 0
        if b[0] - pad < 4:
            nudge = 4 - (b[0] - pad)
        elif b[2] + pad > self.W - 4:
            nudge = (self.W - 4) - (b[2] + pad)
        if nudge:
            c.move(tid, nudge, 0)
        x1, y1, x2, y2 = c.bbox(tid)
        x1, y1, x2, y2 = x1 - pad, y1 - pad, x2 + pad, y2 + pad
        self._round_rect(c, x1, y1, x2, y2, 12, fill=CREAM, outline=CLAY_DARK, width=2)
        tx = self.pet_cx
        if below:   # 꼬리를 위로 향하게
            c.create_polygon(tx - 8, y1 + 1, tx + 8, y1 + 1, tx, y1 - 12,
                             fill=CREAM, outline=CLAY_DARK, width=2)
            c.create_line(tx - 7, y1 + 1, tx + 7, y1 + 1, fill=CREAM, width=3)
        else:
            c.create_polygon(tx - 8, y2 - 1, tx + 8, y2 - 1, tx, y2 + 12,
                             fill=CREAM, outline=CLAY_DARK, width=2)
            c.create_line(tx - 7, y2 - 1, tx + 7, y2 - 1, fill=CREAM, width=3)
        c.tag_raise(tid)

    @staticmethod
    def _round_rect(c, x1, y1, x2, y2, rr, **kw):
        pts = [x1 + rr, y1, x2 - rr, y1, x2, y1, x2, y1 + rr,
               x2, y2 - rr, x2, y2, x2 - rr, y2, x1 + rr, y2,
               x1, y2, x1, y2 - rr, x1, y1 + rr, x1, y1]
        return c.create_polygon(pts, smooth=True, **kw)


def main():
    # 중복 실행 방지
    guard = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        guard.bind(("127.0.0.1", SINGLETON_PORT))
    except OSError:
        return
    pet = ClaudePet()
    pet.root.mainloop()
    guard.close()


if __name__ == "__main__":
    main()
