#!/bin/sh
# create_world.sh — 创建新世界脚手架（只生成 .md 静态骨架·零 yaml）
# 用法: sh scripts/create_world.sh <世界名>
# 动态文件（conflicts.yaml / world_state.yaml / world_map.yaml / off_focus/pending_actions.yaml）
# 由首次启动流程物化生成（见 references/session_recovery.md 第二章）
# 创作填充顺序见 references/session_recovery.md 第一章

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORLDSIM_DIR="${WORLDSIM_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

WORLD="$1"
[ -z "$WORLD" ] && { echo "用法: sh scripts/create_world.sh <世界名>" >&2; exit 1; }

# 世界名校验：仅字母/数字/下划线/连字符（防路径穿越）
case "$WORLD" in
  */*|*..*|*[!a-zA-Z0-9_-]*)
    echo "错误: 世界名只能包含字母/数字/下划线/连字符" >&2
    exit 1
    ;;
esac

WORLD_DIR="$WORLDSIM_DIR/worlds/$WORLD"
[ -d "$WORLD_DIR" ] && { echo "错误: 世界 '$WORLD' 已存在: $WORLD_DIR" >&2; exit 1; }

mkdir -p "$WORLD_DIR"

for f in SETTING.md CONFLICTS_SEED.md; do
  if [ -f "$WORLDSIM_DIR/templates/$f" ]; then
    cp "$WORLDSIM_DIR/templates/$f" "$WORLD_DIR/$f"
    echo "  生成: $f"
  else
    echo "  警告: 模板缺失 templates/$f" >&2
  fi
done

echo ""
echo "已创建世界 '$WORLD': $WORLD_DIR（仅 .md 静态骨架·零 yaml）"
echo ""
echo "【待填清单】创作填充顺序（见 references/session_recovery.md 第一章）:"
echo "  1. SETTING.md          世界观/地理/势力/规则/核心高压法则/故事弧线(可选)"
echo "  2. CHAR_*.md           每角色一个档案（从 templates/CHAR_.md 复制改名填写）"
echo "  3. CONFLICTS_SEED.md   2-5 条冲突种子（每条核心高压法则至少覆盖一条）"
echo "  4. LOOPS.md            可选·循环世界必填（声明循环机制与角色默认循环）"
echo "     CROSS_NARRATIVES.md 可选·隐藏交叉线"
echo ""
echo "动态文件（conflicts/world_state/world_map/pending_actions）由『启动世界』首次启动时物化生成。"
exit 0
