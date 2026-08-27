#!/usr/bin/env python3
# write_narrative.py — 写入叙事正文，存在则自动轮转（改名为 narrative.{时间戳}.md）
# 用法:
#   python3 scripts/write_narrative.py <世界名> <场景ID> [content_file]
#   cat content.md | python3 scripts/write_narrative.py <世界名> <场景ID>
#
# 示例:
#   python3 scripts/write_narrative.py westworld S01-甜水镇主街 narrative.txt
#   cat narrative.txt | python3 scripts/write_narrative.py westworld S01-甜水镇主街
#
# 注意: 本脚本只负责落盘轮转——W4 锚点核对已在阶段2 推送前由 gate writer --check 执行（SKILL.md 执行顺序）。
#       移除 W4 的核心理由：叙事先 message 推送用户后才核对=防幻觉失效（坏叙事已到用户手中）；
#       W4 检查前移到推送前，此处不再重复（单点检查，避免双份逻辑漂移）。
#
# 编码（硬性）：内容经原始字节写入（content_file cp / stdin.buffer.read）——UTF-8 字节原样保留，
#       与 write-raw --batch 同款，避免 CLI 参数/文本 stdin 的 locale 解码损坏。
import os, re, shutil, sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if _s and _s.encoding and _s.encoding.lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SKILL_DIR = Path(__file__).resolve().parent.parent
WORLDS_ROOT = Path(os.environ.get("WORLDSIM_WORLDS_DIR", SKILL_DIR / "worlds"))


def _extract_round(text: str) -> str:
    """首行「轮次 N」→ 数字；无则空。"""
    first = text.splitlines()[0] if text.strip() else ""
    m = re.search(r"轮次\s*(\d+)", first)
    return m.group(1) if m else ""


def _world_state_round(world_dir: Path) -> str:
    """world_state.yaml 顶层 轮次 → 数字；无则空。"""
    ws = world_dir / "states" / "world_state.yaml"
    try:
        for line in ws.read_text(encoding="utf-8").splitlines():
            if line.startswith("轮次:"):
                m = re.search(r"(\d+)", line)
                if m:
                    return m.group(1)
                break
    except Exception:
        pass
    return ""


def main():
    argv = sys.argv[1:]
    world = argv[0] if len(argv) >= 1 else ""
    scene_id = argv[1] if len(argv) >= 2 else ""
    content_file = argv[2] if len(argv) >= 3 else ""

    if not world or not scene_id:
        print("用法: write_narrative.py <世界名> <场景ID> [content_file]", file=sys.stderr)
        sys.exit(1)
    if "/" in world or "\\" in world or ".." in world:
        print(f"[ERR] 非法世界名 '{world}'（禁止路径分隔符/../相对路径穿越）", file=sys.stderr)
        sys.exit(1)
    if "/" in scene_id or "\\" in scene_id or ".." in scene_id:
        print(f"[ERR] 非法场景ID '{scene_id}'（禁止路径分隔符）", file=sys.stderr)
        sys.exit(1)

    world_dir = WORLDS_ROOT / world
    scenes_root = world_dir / "scenes"
    scene_dir = scenes_root / scene_id
    if not scene_dir.is_dir():
        matches = sorted(scenes_root.glob(scene_id + "-*")) if scenes_root.is_dir() else []
        if matches:
            scene_dir = matches[0]
        else:
            print(f"[ERR] 场景目录不存在: {scene_dir}", file=sys.stderr)
            sys.exit(1)

    narrative = scene_dir / "narrative.md"
    tmp = scene_dir / f".narrative.check.{os.getpid()}.md"

    # 内容先入临时文件（原子写入：避免直接覆盖时中断留下半截文件）——原始字节，UTF-8 无损
    if content_file and Path(content_file).is_file():
        shutil.copy2(content_file, tmp)
    else:
        tmp.write_bytes(sys.stdin.buffer.read())

    # 落盘：已存在且非空则改名归档（带轮次号·精确到秒）；空占位（init_scene 骨架）直接覆盖·不留伪归档
    if narrative.exists() and narrative.stat().st_size > 0:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        round_no = ""
        try:
            round_no = _extract_round(narrative.read_text(encoding="utf-8"))
        except Exception:
            pass
        if not round_no:
            round_no = _world_state_round(world_dir)
        if round_no:
            os.replace(str(narrative), str(scene_dir / f"narrative.r{round_no}.{ts}.md"))
        else:
            os.replace(str(narrative), str(scene_dir / f"narrative.{ts}.md"))

    os.replace(str(tmp), str(narrative))
    print(f"[OK] 叙事已写入: {world} / {scene_id}")


if __name__ == "__main__":
    main()
