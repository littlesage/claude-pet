# -*- coding: utf-8 -*-
"""actions.json을 사람이 읽기 좋게 다시 쓴다 (프레임 한 줄에 한 개)."""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "assets", "sit_actions", "actions.json")


def frame_line(item, indent):
    pad = " " * indent
    if isinstance(item, dict):
        inner = ",\n".join(frame_line(f, indent + 4) for f in item.get("frames", []))
        rep = item.get("repeat", 1)
        rep = (f"[{int(rep[0])}, {int(rep[1])}]"
               if isinstance(rep, (list, tuple)) else str(int(rep)))
        return (f'{pad}{{"repeat": {rep}, "frames": [\n'
                f'{inner}\n{pad}]}}')
    name, dur = item
    return f'{pad}["{name}", {int(dur)}]'


data = json.load(open(CONFIG, encoding="utf-8"))
lo, hi = data.get("interval_seconds", [18, 40])
lines = ["{", f'  "interval_seconds": [{int(lo)}, {int(hi)}],', '  "actions": {']
names = list(data["actions"])
for i, name in enumerate(names):
    spec = data["actions"][name]
    lines.append(f'    "{name}": {{')
    lines.append(f'      "weight": {spec.get("weight", 1.0)},')
    lines.append('      "sequence": [')
    seq = ",\n".join(frame_line(f, 8) for f in spec["sequence"])
    lines.append(seq)
    lines.append('      ]')
    lines.append('    }' + ("," if i < len(names) - 1 else ""))
lines += ['  }', '}']
open(CONFIG, "w", encoding="utf-8").write("\n".join(lines) + "\n")

json.load(open(CONFIG, encoding="utf-8"))      # 다시 읽혀야 정상
print(f"정리 완료: {CONFIG}")
print(f"  행동 {len(names)}종: {', '.join(names)}")
