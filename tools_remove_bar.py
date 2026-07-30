# -*- coding: utf-8 -*-
"""매달리기 그림에서 봉(가로 막대)만 지우고 손은 남긴다.

봉은 몸통보다 훨씬 옆으로 뻗은 가로줄이라 폭으로 알아낼 수 있다. 봉이 있는 줄에서는
바로 아래 줄의 몸 실루엣만 남기면, 봉은 사라지고 그 자리를 잡고 있던 손은 그대로 남는다.
프레임마다 봉의 두께와 높이가 달라 깜빡이던 문제도 함께 사라진다.
"""
import glob
import os
import sys
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
WIDE = 1.4          # 몸통 폭의 이 배를 넘으면 봉으로 본다
BRIDGE = 12         # 봉 위아래에서 이 거리 안에 몸이 이어지면 원본 픽셀 복원


def strip_bar(im):
    arr = np.array(im.convert("RGBA"))
    original = arr.copy()
    alpha = arr[..., 3] >= 128
    widths = alpha.sum(axis=1)
    rows = np.nonzero(widths)[0]
    if len(rows) == 0:
        return im, 0
    body = np.median(widths[rows])
    bar_rows = [y for y in rows if widths[y] > body * WIDE]
    if not bar_rows:
        return im, 0

    # 먼저 봉 행을 비우고, 그 행을 가로질러 위아래 실루엣이 이어지는 곳만 원본에서
    # 복원한다. 봉은 세로 연결이 없지만 귀·손·머리카락은 위아래 픽셀이 이어진다.
    for y in bar_rows:
        arr[y, :, 3] = 0
    kept = arr[..., 3] >= 128
    for y in bar_rows:
        top = kept[max(0, y - BRIDGE):y].any(axis=0)
        bottom = kept[y + 1:min(kept.shape[0], y + BRIDGE + 1)].any(axis=0)
        restore = alpha[y] & top & bottom
        arr[y, restore] = original[y, restore]
    return Image.fromarray(arr), len(bar_rows)


def main():
    targets = sorted(glob.glob(os.path.join(ASSETS, "hang_*.png")))
    if not targets:
        raise SystemExit("assets에 hang_*.png가 없습니다")
    out_dir = os.path.join(ASSETS, "_hang_nobar")
    os.makedirs(out_dir, exist_ok=True)
    for f in targets:
        im, n = strip_bar(Image.open(f))
        dst = os.path.join(out_dir, os.path.basename(f))
        im.save(dst)
        print(f"{os.path.basename(f)}: 봉 {n}줄 제거 → {dst}")


if __name__ == "__main__":
    main()
