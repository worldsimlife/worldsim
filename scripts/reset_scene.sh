#!/usr/bin/env sh
# reset_scene.sh — 重置指定场景到「start_snapshot 状态」（清空场景内动态叙事）
# 用法: sh scripts/reset_scene.sh <世界名> [<场景ID>]
#   <场景ID> 缺省 = 当前焦点场景（world_state.焦点场景）；支持短 ID（S05）或完整目录名
# 破坏性操作（重置前自动存档·可回滚）：
#   - narrative.md → 轮转归档为 narrative.<时间戳>.md（保留历史叙事），新 narrative.md 置空
#   - scene_state.yaml：场景时间线 → ''；核心状态 → 待填充占位（按 start_snapshot.md 恢复开场状态）
#   - 静态基线保留：物理锚点/道具/关键场景信息/出场角色摘要（场景物理定义，不因重置销毁）
#   - world_state 时间/轮次不动（时间只增不减是硬规则——重置后戏剧家按 start_snapshot 决定是否回退）
# 重置后：按 start_snapshot.md 重新填充 scene_state 核心状态并继续叙事

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORLDSIM_DIR="${WORLDSIM_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

WORLD="$1"
SCENE_ID="$2"
[ -z "$WORLD" ] && { echo "用法: sh scripts/reset_scene.sh <世界名> [<场景ID>]" >&2; exit 1; }

WORLD_DIR="$WORLDSIM_DIR/worlds/$WORLD"
[ -d "$WORLD_DIR" ] || { echo "[ERR] 世界 '$WORLD' 不存在: $WORLD_DIR" >&2; exit 1; }

# ── 解析场景目录（缺省=焦点场景；短 ID 前缀匹配完整目录名）──
SCENE_DIR=""
if [ -n "$SCENE_ID" ]; then
  if [ -d "$WORLD_DIR/scenes/$SCENE_ID" ]; then
    SCENE_DIR="$WORLD_DIR/scenes/$SCENE_ID"
  else
    SCENE_DIR=$(ls -d "$WORLD_DIR/scenes/${SCENE_ID}-"* 2>/dev/null | head -1)
  fi
else
  if [ -f "$WORLD_DIR/world_state.yaml" ]; then
    FOCUS=$(grep -m1 '^焦点场景:' "$WORLD_DIR/world_state.yaml" | sed 's/^焦点场景:[[:space:]]*//')
    [ -n "$FOCUS" ] && SCENE_DIR=$(ls -d "$WORLD_DIR/scenes/${FOCUS}-"* 2>/dev/null | head -1)
  fi
fi
[ -z "$SCENE_DIR" ] || [ ! -d "$SCENE_DIR" ] && { echo "[ERR] 场景不存在: ${SCENE_ID:-<焦点场景>}（检查 scenes/ 目录与 world_state.焦点场景）" >&2; exit 1; }
SCENE_BASE=$(basename "$SCENE_DIR")

# ── 安全网：自动存档（可回滚）──
SNAP_OUTPUT=$(sh "$SCRIPT_DIR/snap.sh" "$WORLD" save "_before_reset_scene_${SCENE_BASE}_$(date +%Y%m%d-%H%M%S)" 2>&1)
echo "$SNAP_OUTPUT"

# ── 1. narrative.md 轮转归档 + 置空 ──
NARR_FILE="$SCENE_DIR/narrative.md"
if [ -f "$NARR_FILE" ] && [ -s "$NARR_FILE" ]; then
  TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
  mv "$NARR_FILE" "$SCENE_DIR/narrative.$TIMESTAMP.md"
  echo "  归档: narrative.md -> narrative.$TIMESTAMP.md"
fi
touch "$NARR_FILE"
echo "  清空: narrative.md"

# ── 2. scene_state.yaml：场景时间线置空 + 核心状态待填充（保留静态基线）──
SS_FILE="$SCENE_DIR/scene_state.yaml"
if [ -f "$SS_FILE" ]; then
  python3 - "$SS_FILE" << 'PYEOF'
import sys, yaml
fp = sys.argv[1]
with open(fp, encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}
if isinstance(data, dict):
    changed = []
    if data.get("场景时间线"):
        data["场景时间线"] = ""
        changed.append("场景时间线")
    if data.get("核心状态"):
        data["核心状态"] = "<!-- 已重置：待按 start_snapshot.md 恢复开场状态 -->"
        changed.append("核心状态")
    with open(fp, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)
    if changed:
        print(f"  重置: {'/'.join(changed)}")
    else:
        print("  无变化: scene_state.yaml（场景时间线/核心状态已为空）")
else:
    print("[WARN] scene_state.yaml 顶层非映射，跳过重置", file=sys.stderr)
PYEOF
else
  echo "[WARN] scene_state.yaml 不存在，跳过场景状态重置" >&2
fi

# ── 3. start_snapshot.md 确认存在（恢复依据）──
SNAP_FILE="$SCENE_DIR/start_snapshot.md"
if [ -f "$SNAP_FILE" ]; then
  echo "  恢复依据: start_snapshot.md（按此重新填充核心状态/道具/角色姿态）"
else
  echo "[WARN] start_snapshot.md 不存在——重置后无恢复依据，建议补写" >&2
fi

echo ""
echo "已重置场景 '$SCENE_BASE' 到 start_snapshot 状态（静态基线保留·动态叙事清空）"
echo "下一步: 戏剧家按 start_snapshot.md 重新填充 scene_state 核心状态，继续叙事"
exit 0
