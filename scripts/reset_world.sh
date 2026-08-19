#!/bin/sh
# reset_world.sh — 重置世界到「创建完成态」（纯 .md 静态骨架·零 yaml）
# 用法: sh scripts/reset_world.sh <世界名> [--force]
# 破坏性操作（重置前自动存档·可回滚）：
#   删除 scenes/ 整个目录、states/ 下全部 yaml
#   保留 SETTING.md / characters/ / story_architecture/ / regions/ / snaps/
# 重置后世界回到未启动状态——用『启动世界』走 init-states 重新物化（见 references/session_recovery.md 第二章）
# 确认：交互终端提示 [y/N]（默认拒绝）；非交互环境（stdin 非 tty）需追加 --force 标志，否则拒绝执行。

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORLDS_ROOT="${WORLDSIM_WORLDS_DIR:-$SKILL_DIR/worlds}"

WORLD="$1"
[ -z "$WORLD" ] && { echo "用法: sh scripts/reset_world.sh <世界名> [--force]" >&2; exit 1; }

# 世界名校验：只禁路径分隔符/穿越（允许中文·如「遗弃之地」）
case "$WORLD" in
  ''|*/*|*\\*|*..*) echo "错误: 非法世界名 '$WORLD'（禁止路径分隔符/../相对路径穿越）" >&2; exit 1 ;;
esac

WORLD_DIR="$WORLDS_ROOT/$WORLD"
[ -d "$WORLD_DIR" ] || { echo "错误: 世界 '$WORLD' 不存在: $WORLD_DIR" >&2; exit 1; }

# 破坏性操作确认：--force 直过；交互终端提示 [y/N]（默认拒绝）；非交互且无 --force → 拒绝执行
FORCE=0
for _a in "$@"; do [ "$_a" = "--force" ] && FORCE=1; done
if [ "$FORCE" != "1" ]; then
  if [ ! -t 0 ]; then
    echo "错误: 非交互环境执行重置需显式 --force 标志（sh scripts/reset_world.sh $WORLD --force）" >&2
    exit 1
  fi
  printf "重置世界 '$WORLD' 到创建完成态（删除全部动态状态·自动存档可回滚）[y/N] "
  read _answer
  case "$_answer" in y|Y|yes|YES) ;; *) echo "已取消"; exit 0 ;; esac
fi

# 安全网：自动存档（可回滚）
SNAP_OUTPUT=$(sh "$SCRIPT_DIR/snap.sh" "$WORLD" save "_before_reset_$(date +%Y%m%d-%H%M%S)" 2>&1)
echo "$SNAP_OUTPUT"

# 删除动态状态与场景
if [ -d "$WORLD_DIR/scenes" ]; then
  rm -rf "$WORLD_DIR/scenes"
  echo "  删除: scenes/"
fi
for f in "$WORLD_DIR"/states/CHAR_*_state.yaml; do
  [ -f "$f" ] || continue
  rm -f "$f"
  echo "  删除: $(basename "$f")"
done
for f in states/world_state.yaml states/conflicts.yaml states/world_map.yaml states/pending_actions.yaml states/foreshadow.yaml states/knowledge_index.yaml; do
  if [ -f "$WORLD_DIR/$f" ]; then
    rm -f "$WORLD_DIR/$f"
    echo "  删除: $f"
  fi
done

echo ""
echo "已重置世界 '$WORLD' 到创建完成态（仅 .md·零 yaml）"
echo "下一步: 用『启动世界』进入第二章（init-states 重新物化 conflicts/world_state/world_map/pending_actions）"
exit 0
