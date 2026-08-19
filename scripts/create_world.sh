#!/bin/sh
# create_world.sh — 创建新世界脚手架（只生成 .md 静态骨架·零 yaml）
# 用法: sh scripts/create_world.sh <世界名>
# 动态文件（states/ 下 yaml）由启动世界 init-states 物化生成（见 references/session_recovery.md 第二章）
# 创作填充顺序见 references/session_recovery.md 第一章

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORLDS_ROOT="${WORLDSIM_WORLDS_DIR:-$SKILL_DIR/worlds}"

WORLD="$1"
[ -z "$WORLD" ] && { echo "用法: sh scripts/create_world.sh <世界名>" >&2; exit 1; }

# 世界名校验：仅字母/数字/下划线/连字符（防路径穿越）
case "$WORLD" in
  */*|*..*|*[!a-zA-Z0-9_-]*)
    echo "错误: 世界名只能包含字母/数字/下划线/连字符" >&2
    exit 1
    ;;
esac

WORLD_DIR="$WORLDS_ROOT/$WORLD"
[ -d "$WORLD_DIR" ] && { echo "错误: 世界 '$WORLD' 已存在: $WORLD_DIR" >&2; exit 1; }

mkdir -p "$WORLD_DIR" "$WORLD_DIR/characters" "$WORLD_DIR/states" "$WORLD_DIR/story_architecture"

for f in SETTING.md; do
  if [ -f "$SKILL_DIR/templates/$f" ]; then
    cp "$SKILL_DIR/templates/$f" "$WORLD_DIR/$f"
    echo "  生成: $f"
  else
    echo "  警告: 模板缺失 templates/$f" >&2
  fi
done
if [ -f "$SKILL_DIR/templates/CONFLICTS_SEED.md" ]; then
  cp "$SKILL_DIR/templates/CONFLICTS_SEED.md" "$WORLD_DIR/story_architecture/CONFLICTS_SEED.md"
  echo "  生成: story_architecture/CONFLICTS_SEED.md"
else
  echo "  警告: 模板缺失 templates/CONFLICTS_SEED.md" >&2
fi

echo ""
echo "已创建世界 '$WORLD': $WORLD_DIR（仅 .md 静态骨架·零 yaml）"
echo ""
echo "【待填清单】创作填充顺序（见 references/session_recovery.md 第一章）:"
echo "  1. SETTING.md                世界观/地理/势力/规则/核心高压法则/故事弧线(可选·顶层唯一文件)"
echo "  2. characters/CHAR_*.md      每角色一个档案（从 templates/CHAR_.md 复制改名填写）"
echo "  3. story_architecture/        故事架构（CONFLICTS_SEED.md 2-5 条冲突种子·LOOPS.md 循环世界必填·CROSS_NARRATIVES.md 可选）"
echo "  4. regions/                   可选·区域静态档案（见 templates/REGION.md）"
echo ""
echo "动态文件（states/ 下 yaml）由『启动世界』init-states 物化生成。"
exit 0
