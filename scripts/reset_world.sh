#!/bin/sh
# reset_world.sh — 重置世界到「创建完成态」（纯 .md 静态骨架·零 yaml）
# 用法: sh scripts/reset_world.sh <世界名>
# 破坏性操作（重置前自动存档·可回滚）：
#   删除 scenes/ 整个目录、CHAR_*_state.yaml、conflicts.yaml、world_state.yaml、
#        world_map.yaml、off_focus/pending_actions.yaml
#   保留 CHAR_*.md / SETTING.md / LOOPS.md / CROSS_NARRATIVES.md / CONFLICTS_SEED.md / snaps/
# 重置后世界回到未启动状态——用『启动世界』重新物化（见 references/session_recovery.md 第二章）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORLDSIM_DIR="${WORLDSIM_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

WORLD="$1"
[ -z "$WORLD" ] && { echo "用法: sh scripts/reset_world.sh <世界名>" >&2; exit 1; }

WORLD_DIR="$WORLDSIM_DIR/worlds/$WORLD"
[ -d "$WORLD_DIR" ] || { echo "错误: 世界 '$WORLD' 不存在: $WORLD_DIR" >&2; exit 1; }

# 安全网：自动存档（可回滚）
SNAP_OUTPUT=$(sh "$SCRIPT_DIR/snap.sh" "$WORLD" save "_before_reset_$(date +%Y%m%d-%H%M%S)" 2>&1)
echo "$SNAP_OUTPUT"

# 删除动态状态与场景
if [ -d "$WORLD_DIR/scenes" ]; then
  rm -rf "$WORLD_DIR/scenes"
  echo "  删除: scenes/"
fi
for f in "$WORLD_DIR"/CHAR_*_state.yaml; do
  [ -f "$f" ] || continue
  rm -f "$f"
  echo "  删除: $(basename "$f")"
done
for f in conflicts.yaml world_state.yaml world_map.yaml off_focus/pending_actions.yaml; do
  if [ -f "$WORLD_DIR/$f" ]; then
    rm -f "$WORLD_DIR/$f"
    echo "  删除: $f"
  fi
done

echo ""
echo "已重置世界 '$WORLD' 到创建完成态（仅 .md·零 yaml）"
echo "下一步: 用『启动世界』进入首次启动（重新物化 conflicts/world_state/world_map/pending_actions）"
exit 0
