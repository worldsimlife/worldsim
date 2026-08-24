#!/usr/bin/env python3
# reset_world.py — 重置世界到「创建完成态」（纯 .md 静态骨架·零 yaml）
# 用法: python3 scripts/reset_world.py <世界名> [--force]
# 破坏性操作（重置前自动存档·可回滚）：
#   删除 scenes/ 整个目录、states/ 下全部文件（运行期产物·不按文件名枚举·含隐藏文件）
#   保留 SETTING.md / characters/ / story_architecture/ / regions/ / snaps/
# 重置后世界回到未启动状态——用『启动世界』走 init-states 重新物化（见 references/session_recovery.md 第二章：
# conflicts/world_state/world_map/storylines/direction ← 模板与 SEED·CHAR_{名}_state.yaml ← 骨架）
# 确认：交互终端提示 [y/N]（默认拒绝）；非交互环境（stdin 非 tty）需追加 --force 标志，否则拒绝执行。
import os, re, shutil, subprocess, sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        if _s and _s.encoding and _s.encoding.lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
WORLDS_ROOT = Path(os.environ.get("WORLDSIM_WORLDS_DIR", SKILL_DIR / "worlds"))


def main():
    argv = sys.argv[1:]
    world = argv[0] if len(argv) >= 1 else ""
    force = "--force" in argv[1:]

    if not world:
        print("用法: python3 scripts/reset_world.py <世界名> [--force]", file=sys.stderr)
        sys.exit(1)
    if "/" in world or "\\" in world or ".." in world:
        print(f"错误: 非法世界名 '{world}'（禁止路径分隔符/../相对路径穿越）", file=sys.stderr)
        sys.exit(1)
    world_dir = WORLDS_ROOT / world
    if not world_dir.is_dir():
        print(f"错误: 世界 '{world}' 不存在: {world_dir}", file=sys.stderr)
        sys.exit(1)

    # 破坏性操作确认：--force 直过；交互终端提示 [y/N]（默认拒绝）；非交互且无 --force → 拒绝执行
    if not force:
        if not sys.stdin.isatty():
            print(f"错误: 非交互环境执行重置需显式 --force 标志（python3 scripts/reset_world.py {world} --force）", file=sys.stderr)
            sys.exit(1)
        print(f"重置世界 '{world}' 到创建完成态（删除全部动态状态·自动存档可回滚）[y/N] ", end="", flush=True)
        ans = sys.stdin.buffer.readline().decode("utf-8").strip()
        if ans.lower() not in ("y", "yes"):
            print("已取消")
            sys.exit(0)

    # 安全网：自动存档（可回滚）
    snapname = f"_before_reset_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    p = subprocess.run([sys.executable, str(SCRIPT_DIR / "snap.py"), world, "save", snapname], capture_output=True)
    print((p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace"), end="")

    # 删除动态状态与场景
    if (world_dir / "scenes").is_dir():
        shutil.rmtree(world_dir / "scenes")
        print("  删除: scenes/")
    states_dir = world_dir / "states"
    if states_dir.is_dir():
        for f in sorted(states_dir.iterdir()):
            if f.is_file():
                f.unlink()
                print(f"  删除: states/{f.name}")

    print("")
    print(f"已重置世界 '{world}' 到创建完成态（仅 .md·零 yaml）")
    print("下一步: 用『启动世界』进入第二章（init-states 重新物化 conflicts/world_state/world_map/storylines/direction + CHAR_state 骨架）")
    sys.exit(0)


if __name__ == "__main__":
    main()
