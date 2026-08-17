#!/usr/bin/env sh
# reset_scene.sh — 场景级回退（L3）：重置指定场景到「start_snapshot 状态」（清空场景内动态叙事·不撤销世界进度）
# 用法: sh scripts/reset_scene.sh <世界名> [<场景ID>] [--force]
#   <场景ID> 缺省 = 当前焦点场景（world_state.焦点场景）；支持短 ID（S05）或完整目录名
# 回退体系：L1 世界级 snap.sh load（快照·主动存档）/ L2 场景级本脚本 / L3 手工重建（详见 references/rollback.md）
# 破坏性操作（重置前自动存档·可回滚）：
#   - narrative.md → 轮转归档为 narrative.r{轮次}.<时间戳>.md（保留历史叙事·轮次=叙事内容首行或 world_state 顶层轮次·无轮次时纯时间戳），新 narrative.md 置空
#   - scene_state.yaml：场景时间线 → ''；核心状态 → 待填充占位（按 start_snapshot.md 恢复开场状态）
#   - 静态基线保留：物理锚点/道具/关键场景信息/出场角色摘要（场景物理定义，不因重置销毁）
#   - world_state 时间/轮次回退至场景开场（start_snapshot 冻结时间/开场轮次）——「时间只增不减」只约束正常推进·显式重置是主动回退例外
# 重置后：按 start_snapshot.md 重新填充 scene_state 核心状态并继续叙事（世界时间/轮次已与场景开场一致）
# 确认：交互终端提示 [y/N]（默认拒绝）；非交互环境（stdin 非 tty）需追加 --force 标志，否则拒绝执行。

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORLDS_ROOT="${WORLDSIM_WORLDS_DIR:-$SKILL_DIR/worlds}"

WORLD="$1"
SCENE_ID="$2"
[ -z "$WORLD" ] && { echo "用法: sh scripts/reset_scene.sh <世界名> [<场景ID>] [--force]" >&2; exit 1; }

# 世界名校验：只禁路径分隔符/穿越（允许中文·如「遗弃之地」）
case "$WORLD" in
  ''|*/*|*\\*|*..*) echo "[ERR] 非法世界名 '$WORLD'（禁止路径分隔符/../相对路径穿越）" >&2; exit 1 ;;
esac

WORLD_DIR="$WORLDS_ROOT/$WORLD"
[ -d "$WORLD_DIR" ] || { echo "[ERR] 世界 '$WORLD' 不存在: $WORLD_DIR" >&2; exit 1; }

# ── 解析场景目录（缺省=焦点场景；短 ID 前缀匹配完整目录名）──
SCENE_DIR=""
if [ -n "$SCENE_ID" ]; then
  case "$SCENE_ID" in
    */*|*\\*|*..*) echo "[ERR] 非法场景 ID '$SCENE_ID'（禁止路径分隔符）" >&2; exit 1 ;;
  esac
  if [ -d "$WORLD_DIR/scenes/$SCENE_ID" ]; then
    SCENE_DIR="$WORLD_DIR/scenes/$SCENE_ID"
  else
    SCENE_DIR=$(ls -d "$WORLD_DIR/scenes/${SCENE_ID}-"* 2>/dev/null | head -1)
  fi
else
  if [ -f "$WORLD_DIR/states/world_state.yaml" ]; then
    FOCUS=$(grep -m1 '^焦点场景:' "$WORLD_DIR/states/world_state.yaml" | sed 's/^焦点场景:[[:space:]]*//')
    [ -n "$FOCUS" ] && SCENE_DIR=$(ls -d "$WORLD_DIR/scenes/${FOCUS}-"* 2>/dev/null | head -1)
  fi
fi
[ -z "$SCENE_DIR" ] || [ ! -d "$SCENE_DIR" ] && { echo "[ERR] 场景不存在: ${SCENE_ID:-<焦点场景>}（检查 scenes/ 目录与 world_state.焦点场景）" >&2; exit 1; }
SCENE_BASE=$(basename "$SCENE_DIR")

# 破坏性操作确认：--force 直过；交互终端提示 [y/N]（默认拒绝）；非交互且无 --force → 拒绝执行
FORCE=0
for _a in "$@"; do [ "$_a" = "--force" ] && FORCE=1; done
if [ "$FORCE" != "1" ]; then
  if [ ! -t 0 ]; then
    echo "错误: 非交互环境执行场景重置需显式 --force 标志（sh scripts/reset_scene.sh $WORLD $SCENE_ID --force）" >&2
    exit 1
  fi
  printf "重置场景 '$SCENE_BASE' 到 start_snapshot 状态（清空动态叙事·自动存档可回滚）[y/N] "
  read _answer
  case "$_answer" in y|Y|yes|YES) ;; *) echo "已取消"; exit 0 ;; esac
fi

# ── 安全网：自动存档（可回滚）──
SNAP_OUTPUT=$(sh "$SCRIPT_DIR/snap.sh" "$WORLD" save "_before_reset_scene_${SCENE_BASE}_$(date +%Y%m%d-%H%M%S)" 2>&1)
echo "$SNAP_OUTPUT"

# ── 1. narrative.md 轮转归档 + 置空 ──
NARR_FILE="$SCENE_DIR/narrative.md"
if [ -f "$NARR_FILE" ] && [ -s "$NARR_FILE" ]; then
  TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
  # 轮次提取：①narrative 首行「轮次 N」→ ②world_state 顶层 轮次 → ③空（纯时间戳）
  ROUND=$(sed -n '1p' "$NARR_FILE" | grep -o '轮次[[:space:]]*[0-9]\+' | grep -o '[0-9]\+' | head -1)
  if [ -z "$ROUND" ]; then
    ROUND=$(grep -E '^轮次:' "$WORLDS_ROOT/$WORLD/states/world_state.yaml" 2>/dev/null | head -1 | grep -o '[0-9]\+' | head -1)
  fi
  if [ -n "$ROUND" ]; then
    mv "$NARR_FILE" "$SCENE_DIR/narrative.r${ROUND}.$TIMESTAMP.md"
    echo "  归档: narrative.md -> narrative.r${ROUND}.$TIMESTAMP.md"
  else
    mv "$NARR_FILE" "$SCENE_DIR/narrative.$TIMESTAMP.md"
    echo "  归档: narrative.md -> narrative.$TIMESTAMP.md"
  fi
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

# ── 4. world_state 时间/轮次回退至场景开场（重置=场景重开·「时间只增不减」只约束正常推进，不约束显式重置）──
WS_FILE="$WORLD_DIR/states/world_state.yaml"
START_TIME=""
START_ROUND=""
if [ -f "$SNAP_FILE" ]; then
  # 兼容两种格式：`冻结时间：值`（模板·冒号单行）/ `## 冻结时间`+下一行（旧版标题）
  START_TIME=$(grep -E "^冻结时间[:：]" "$SNAP_FILE" | head -1 | sed -E 's/^冻结时间[:：][[:space:]]*//')
  [ -z "$START_TIME" ] && START_TIME=$(grep -A1 "^## 冻结时间" "$SNAP_FILE" | tail -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
  START_ROUND=$(grep -E "^开场轮次[:：]" "$SNAP_FILE" | head -1 | sed -E 's/^开场轮次[:：][[:space:]]*//' | tr -d "'\"")
  [ -z "$START_ROUND" ] && START_ROUND=$(grep -A1 "^## 开场轮次" "$SNAP_FILE" | tail -1 | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | tr -d "'\"")
fi
if [ -f "$WS_FILE" ]; then
  if [ -n "$START_TIME" ]; then
    sed -i "s/^  具体时间:.*/  具体时间: $START_TIME/" "$WS_FILE"
    sed -i "s/^  基准时间:.*/  基准时间: $START_TIME/" "$WS_FILE"
    echo "  回退: world_state 时间 → $START_TIME（场景开场）"
  else
    echo "[WARN] start_snapshot.md 无冻结时间，跳过 world_state 时间回退（请补填 start_snapshot「## 冻结时间」）" >&2
  fi
  if [ -n "$START_ROUND" ]; then
    sed -i "s/^轮次:.*/轮次: '$START_ROUND'/" "$WS_FILE"
    echo "  回退: world_state 轮次 → $START_ROUND（场景开场）"
  else
    echo "[WARN] start_snapshot.md 无开场轮次，跳过 world_state 轮次回退（请补填 start_snapshot「## 开场轮次」）" >&2
  fi
fi

echo ""
echo "已重置场景 '$SCENE_BASE' 到 start_snapshot 状态（静态基线保留·动态叙事清空·世界时间/轮次已回退至开场）"
echo "下一步: 戏剧家按 start_snapshot.md 重新填充 scene_state 核心状态，继续叙事"
echo ""
echo "【回退后必查·脚本不自动处理·LLM 按 references/rollback.md 涉及文件清单逐项核对】:"
echo "  1. conflicts.yaml        CT 当前节拍回退/覆盖（或删除回退期间推进的节拍）"
echo "  2. CHAR_*_state.yaml     核心状态/情绪/位置恢复开场形态；记忆锚点/反应轨迹含回退后'未来'条目需裁剪"
echo "                            （外部者如 Guest 必须裁剪未来记忆·Host 可保留作既视感/碎片素材）"
echo "  3. world_state.yaml      前情描述/外部倒计时/全局标记（脚本只回退了时间/轮次·其余仍可能是回退前状态）"
echo "  4. scene_state.yaml      核心状态/出场角色摘要恢复开场形态（脚本只清了时间线·静态基线保留）"
echo "  5. states/pending_actions.yaml     焦外条目回退（最易漏）"
echo "  6. world_map.yaml        回退期间新登记的区域（如有）"
exit 0
