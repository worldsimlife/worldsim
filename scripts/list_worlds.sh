#!/bin/sh
# list_worlds.sh — 列出所有世界（当前 .yaml 体系）
# 用法: sh scripts/list_worlds.sh

# worlds 根：可被环境变量 WORLDSIM_WORLDS_DIR 覆写（用户自己的存储）；skill 根恒由脚本自身位置推导，不依赖 picoclaw
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORLDS_ROOT="${WORLDSIM_WORLDS_DIR:-$SKILL_DIR/worlds}"

for d in "$WORLDS_ROOT"/*/; do
  [ -d "$d" ] || continue
  name=$(basename "$d")
  # 跳过非世界目录（如 snaps 归档目录）
  [ "$name" = "snaps" ] && continue
  [ -d "$d/scenes" ] || continue

  focus=$(grep -E "^焦点场景:" "$d/states/world_state.yaml" 2>/dev/null | head -1 | sed 's/^焦点场景:[[:space:]]*//' | tr -d '[:space:]')
  if [ -z "$focus" ] && [ -f "$d/.active" ]; then
    focus="$(cat "$d/.active")（旧格式）"
  fi
  if [ -n "$focus" ]; then
    echo "🟢 $name（焦点场景: $focus）"
  else
    echo "⚪ $name"
  fi
  chars=$(ls "$d"/characters/CHAR_*.md 2>/dev/null | wc -l)
  states=$(ls "$d"/states/CHAR_*_state.yaml 2>/dev/null | wc -l)
  scenes=$(ls -d "$d"/scenes/S*/ 2>/dev/null | wc -l)
  echo "   角色: $chars | 状态文件: $states | 场景: $scenes"
done

exit 0
