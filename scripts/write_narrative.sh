#!/usr/bin/env sh
# write_narrative.sh — 写入叙事正文，存在则自动轮转（改名为 narrative.{时间戳}.md）
# 用法:
#   sh scripts/write_narrative.sh <世界名> <场景ID> [content_file]
#   cat content.md | sh scripts/write_narrative.sh <世界名> <场景ID>
#
# 示例:
#   sh scripts/write_narrative.sh westworld S01-甜水镇主街 narrative.txt
#   cat narrative.txt | sh scripts/write_narrative.sh westworld S01-甜水镇主街
#
# 注意: 本脚本只负责落盘轮转——W4 锚点核对已在阶段2 推送前由 gate writer --check 执行（SKILL.md 执行顺序）。
#       移除 W4 的核心理由：叙事先 message 推送用户后才核对=防幻觉失效（坏叙事已到用户手中）；
#       W4 检查前移到推送前，此处不再重复（单点检查，避免双份逻辑漂移）。

WORLD="$1"
SCENE_ID="$2"
CONTENT_FILE="$3"

[ -z "$WORLD" ] && echo "用法: write_narrative.sh <世界名> <场景ID> [content_file]" && exit 1
[ -z "$SCENE_ID" ] && echo "用法: write_narrative.sh <世界名> <场景ID> [content_file]" && exit 1

# 世界名校验：只禁路径分隔符/穿越（允许中文·如「遗弃之地」）；场景ID 同样禁分隔符
case "$WORLD" in
  ''|*/*|*\\*|*..*) echo "[ERR] 非法世界名 '$WORLD'（禁止路径分隔符/../相对路径穿越）" >&2; exit 1 ;;
esac
case "$SCENE_ID" in
  */*|*\\*|*..*) echo "[ERR] 非法场景ID '$SCENE_ID'（禁止路径分隔符）" >&2; exit 1 ;;
esac

# WorldSim 根目录：可被环境变量 WORLDSIM_DIR 覆写
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORLDSIM_DIR="${WORLDSIM_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
SCENE_DIR="$WORLDSIM_DIR/worlds/$WORLD/scenes/$SCENE_ID"

# 支持短 ID（如 S05）→ 前缀匹配完整目录名（如 S05-Sweetwater-MainStreet-Guide）
if [ ! -d "$SCENE_DIR" ]; then
  MATCH=$(ls -d "$WORLDSIM_DIR/worlds/$WORLD/scenes/${SCENE_ID}-"* 2>/dev/null | head -1)
  if [ -n "$MATCH" ]; then
    SCENE_DIR="$MATCH"
  else
    echo "[ERR] 场景目录不存在: $SCENE_DIR"
    exit 1
  fi
fi

NARRATIVE_FILE="$SCENE_DIR/narrative.md"

# 内容先入临时文件（原子写入：避免直接覆盖时中断留下半截文件）
TMP_NARRATIVE="$SCENE_DIR/.narrative.check.$$.md"
if [ -n "$CONTENT_FILE" ] && [ -f "$CONTENT_FILE" ]; then
  cp "$CONTENT_FILE" "$TMP_NARRATIVE"
else
  cat > "$TMP_NARRATIVE"
fi

# 落盘：已存在则改名归档（精确到秒），再写入
if [ -f "$NARRATIVE_FILE" ]; then
  TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
  mv "$NARRATIVE_FILE" "$SCENE_DIR/narrative.$TIMESTAMP.md"
fi
mv "$TMP_NARRATIVE" "$NARRATIVE_FILE"

echo "[OK] 叙事已写入: $WORLD / $SCENE_ID"
