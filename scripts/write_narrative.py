#!/usr/bin/env python3
# write_narrative.py — 前置 gate writer --check 通过才写入叙事正文，存在则自动轮转（改名为 narrative.{时间戳}.md）
# 用法:
#   python3 scripts/write_narrative.py <世界名> <场景ID> [content_file] [--target 大约数] [--style sepia|dialogue|explicit]
#   python3 scripts/write_narrative.py <世界名> <场景ID> --file content.md [--target N] [--style S]
#   cat content.md | python3 scripts/write_narrative.py <世界名> <场景ID> [--target N] [--style S]
#   python3 scripts/write_narrative.py <世界名> <场景ID> --force [content_file]（维护/回退落盘·跳过前置 gate）
#
# 示例:
#   python3 scripts/write_narrative.py westworld S01-甜水镇主街 narrative.txt --target 1200 --style dialogue
#   python3 scripts/write_narrative.py westworld S01-甜水镇主街 --file worlds/westworld/tmp/narrative_r3.md
#   cat narrative.txt | python3 scripts/write_narrative.py westworld S01-甜水镇主街
#
# 注意: 落盘前默认先调 worldctl gate writer --check（stdin 传同一候选字节·--target/--style 透传）——
#       gate 未通过则中止不落盘（单源·验的即落的）。W4 逻辑仍只在 worldctl 一份，本脚本只做调用+落盘
#       （单点检查，避免双份逻辑漂移）。维护/回退等须绕检场景显式加 --force（与 write-raw --force 同约定）。
#
# 编码（硬性）：内容经原始字节写入（content_file cp / stdin.buffer.read）——UTF-8 字节原样保留，
#       与 write-raw --batch 同款，避免 CLI 参数/文本 stdin 的 locale 解码损坏。
import os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if _s and _s.encoding and _s.encoding.lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import assert_no_links, resolve_world, validate_name


def _extract_round(text: str) -> str:
    """首行「第N轮/轮次N」→ 数字；无则空。"""
    first = text.splitlines()[0] if text.strip() else ""
    for pat in (r"第\s*(\d+)\s*轮", r"轮次\s*(\d+)"):
        m = re.search(pat, first)
        if m:
            return m.group(1)
    return ""


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
    positional = []
    content_file = ""
    force = False
    target = ""
    style = ""
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--file":
            if i + 1 >= len(argv):
                print("[ERR] --file 需要跟一个内容文件路径", file=sys.stderr)
                sys.exit(1)
            content_file = argv[i + 1]
            i += 2
        elif a == "--force":
            force = True
            i += 1
        elif a == "--target":
            if i + 1 >= len(argv):
                print("[ERR] --target 需要跟一个大约目标数", file=sys.stderr)
                sys.exit(1)
            target = argv[i + 1]
            i += 2
        elif a.startswith("--target="):
            target = a[len("--target="):]
            i += 1
        elif a == "--style":
            if i + 1 >= len(argv):
                print("[ERR] --style 需要跟一个风格路径（sepia/dialogue/explicit）", file=sys.stderr)
                sys.exit(1)
            style = argv[i + 1]
            i += 2
        elif a.startswith("--style="):
            style = a[len("--style="):]
            i += 1
        elif a.startswith("--file="):
            content_file = a[len("--file="):]
            i += 1
        else:
            positional.append(a)
            i += 1
    world = positional[0] if len(positional) >= 1 else ""
    scene_id = positional[1] if len(positional) >= 2 else ""
    if not content_file and len(positional) >= 3:
        content_file = positional[2]

    if not world or not scene_id:
        print("用法: write_narrative.py <世界名> <场景ID> [content_file | --file content.md]", file=sys.stderr)
        sys.exit(1)
    validate_name(scene_id, "场景ID")

    world_dir = resolve_world(world)
    scenes_root = world_dir / "scenes"
    assert_no_links(scenes_root)
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

    # 内容先读入内存校验（文件/stdin 为空=拦截退出·防空叙事覆盖+旧叙事被误归档）——原始字节，UTF-8 无损
    if content_file:
        src = Path(content_file)
        if not src.is_file():
            print(f"[ERR] 内容文件不存在: {content_file}", file=sys.stderr)
            sys.exit(1)
        data = src.read_bytes()
    else:
        data = sys.stdin.buffer.read()
    if not data.strip():
        print("[ERR] 叙事内容为空（文件/stdin 无有效内容），已拦截不写入", file=sys.stderr)
        sys.exit(1)
    # 前置 gate（默认）：同一候选字节调 worldctl gate writer --check——未通过则中止不落盘；--force 跳检（维护/回退）
    if not force:
        _wctl = Path(__file__).resolve().parent / "worldctl.py"
        _cmd = [sys.executable, str(_wctl), world, "gate", "writer", "--check"]
        if target:
            _cmd += ["--target", target]
        if style:
            _cmd += ["--style", style]
        _r = subprocess.run(_cmd, input=data)
        if _r.returncode != 0:
            print("[ERR] gate writer 未通过——叙事未落盘", file=sys.stderr)
            sys.exit(1)
    tmp.write_bytes(data)

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
