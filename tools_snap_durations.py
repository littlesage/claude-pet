# -*- coding: utf-8 -*-
"""행동 프레임의 지속시간을 화면 갱신 주기(TICK_MS)의 배수로 맞춘다.

어긋나면 어떤 프레임만 한 틱 더 머물러 떨리는 것처럼 보인다.
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "assets", "sit_actions", "actions.json")
TICK = 25


def snap(items, changed):
    out = []
    for item in items:
        if isinstance(item, dict):
            item = dict(item)
            item["frames"] = snap(item.get("frames", []), changed)
            out.append(item)
            continue
        name, dur = item
        fixed = max(TICK, int(round(dur / TICK)) * TICK)
        if fixed != dur:
            changed.append((name, dur, fixed))
        out.append([name, fixed])
    return out


data = json.load(open(CONFIG, encoding="utf-8"))
changed = []
for action in data.get("actions", {}).values():
    action["sequence"] = snap(action["sequence"], changed)

with open(CONFIG, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")

if changed:
    print(f"{len(changed)}개 프레임 지속시간을 {TICK}ms 배수로 맞췄습니다:")
    for name, before, after in changed:
        print(f"  {name}: {before} → {after}ms")
else:
    print("이미 모두 맞습니다")
