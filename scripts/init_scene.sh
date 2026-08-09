#!/usr/bin/env sh
# init_scene.sh — 创建新场景目录及模板文件
# 用法: init_scene.sh <世界名> <场景ID> <场景名> [--from <旧场景ID>]
#   --from <旧场景ID|旧场景目录名>: 继承旧场景 scene_state 的物理锚点/道具清单
#     （同物理地点切换必用——同一栋建筑的空间元素不因时间区间变化而消失，防止从零重建导致漏继承）

WORLD="$1"
SCENE_ID="$2"
SCENE_NAME="$3"
shift 3
SCENE_TYPE=""
SCENE_TIME=""
SCENE_CAST=""
INHERIT_FROM=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) INHERIT_FROM="$2"; shift 2 ;;
    --type) SCENE_TYPE="$2"; shift 2 ;;
    --time) SCENE_TIME="$2"; shift 2 ;;
    --cast) SCENE_CAST="$2"; shift 2 ;;
    *) echo "[ERR] 未知参数: $1（支持: --from <旧场景ID> / --type <类型> / --time <时间> / --cast <出场角色>）"; exit 1 ;;
  esac
done

if [ -z "$WORLD" ] || [ -z "$SCENE_ID" ] || [ -z "$SCENE_NAME" ]; then
  echo "用法: init_scene.sh <世界名> <场景ID> <场景名> [--from <旧场景ID>] [--type <类型>] [--time <时间>] [--cast <出场角色>]"
  echo "示例: init_scene.sh 遗弃之地 S07 追踪血迹 --type EXT --time '第3日 09:00' --cast 'Guest, Maeve'"
  echo "示例: init_scene.sh 遗弃之地 S08 追踪血迹 --from S07 --type INT --time '第3日 12:00'"
  exit 1
fi

# 场景名是目录名的一部分——禁止含路径分隔符（/）或反斜杠（\），防止破坏 scenes/ 目录结构
case "$SCENE_NAME" in
  */*|*\\) echo "[ERR] 场景名不能含 / 或 \\（场景名=目录名，含分隔符会破坏目录结构）: $SCENE_NAME" >&2; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORLDSIM_DIR="${WORLDSIM_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
WORLD_DIR="$WORLDSIM_DIR/worlds/$WORLD"
SCENE_DIR="$WORLD_DIR/scenes/$SCENE_ID-$SCENE_NAME"

# sed 转义（防场景名/时间/类型含 / & \ 破坏 sed——P7）
sed_escape() {
  echo "$1" | sed 's/[\/&\\]/\\&/g'
}

# ── 继承预检：--from 源场景必须存在且 YAML 可解析（在任何文件创建之前检查，失败即退出·不留半成品）──
if [ -n "$INHERIT_FROM" ]; then
  SRC_DIR=""
  if [ -d "$WORLD_DIR/scenes/$INHERIT_FROM" ]; then
    SRC_DIR="$WORLD_DIR/scenes/$INHERIT_FROM"
  else
    SRC_DIR=$(ls -d "$WORLD_DIR/scenes/${INHERIT_FROM}-"* 2>/dev/null | head -1)
  fi
  if [ -z "$SRC_DIR" ] || [ ! -f "$SRC_DIR/scene_state.yaml" ]; then
    echo "[ERR] --from 场景不存在或缺 scene_state.yaml（检查: $INHERIT_FROM）" >&2
    exit 1
  fi
  if ! python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "$SRC_DIR/scene_state.yaml" 2>/dev/null; then
    echo "[ERR] 源场景 scene_state.yaml 无法解析（$SRC_DIR/scene_state.yaml）——拒绝继承坏格式，请先修复源文件再重跑" >&2
    exit 1
  fi
fi

mkdir -p "$SCENE_DIR"

# scene_card.md（字段名与 templates/scene_card.md 对齐：类型(INT/EXT)/基准时间；非替换字段用 <!-- --> 注释占位，不生成"空提示文本"）
cat > "$SCENE_DIR/scene_card.md" << 'CARD'
# 场景卡片

| 字段 | 值 |
|------|-----|
| 场景ID | __SCENE_ID__ |
| 场景名 | __SCENE_NAME__ |
| 类型(INT/EXT) | __SCENE_TYPE__ |
| 基准时间 | __SCENE_TIME__ |
| 出场角色 | __SCENE_CAST__ |
| 焦外/在场 | <!-- 待填充：焦外角色及其位置 --> |
| 场景目标 | <!-- 待填充：一句话目标 --> |
| 前情钩子 | <!-- 待填充：上一场结束时的最后一个画面或台词 --> |
CARD

# scene_state.yaml（新键表，见 references/keys.md §scene_state.yaml）
# 创建时只写静态基线（核心状态快照/物理锚点/道具/关键场景信息/出场角色）。
# 场景时间线【禁止预写】——剧情事件一律由每轮 change set ###APPEND: 追加（预写=把计划当记录·会与 change set 双写重复）。
# 占位一律 <!-- --> 注释体系且【不含冒号/破折号格式】——防止 extract_anchor_names 把占位注释误提取为真实锚点（P2）。
cat > "$SCENE_DIR/scene_state.yaml" << 'STATE'
核心状态: '<!-- 待填充 -->'
场景时间线: ''
物理锚点: '<!-- 待填充 物理锚点清单（至少5条） -->'
道具: '<!-- 待填充 道具清单 -->'
关键场景信息: '<!-- 待填充 线索清单 -->'
出场角色摘要: '<!-- 待填充 角色摘要 -->'
STATE

# ── INHERIT: --from 继承旧场景物理锚点/道具（同物理地点切换必用；源存在性+可解析性已在创建前预检）──
if [ -n "$INHERIT_FROM" ]; then
    python3 - "$SCENE_DIR/scene_state.yaml" "$SRC_DIR/scene_state.yaml" << 'PYEOF'
import re, sys
target_path, source_path = sys.argv[1], sys.argv[2]
target = open(target_path).read()
source = open(source_path).read()

def block(text, key):
    # 从 key: 起，到下一个顶层键（行首非空白非#非换行）或结尾
    # 注意: 前瞻必须排除 \n——否则源文件单引号折叠字符串内部的空行（\n\n）会被误判为顶层键边界
    #       （旧版 (?=\n^[^ \t#]|\Z) 中 [^ \t#] 会匹配换行符，导致继承块在空行处截断、引号未闭合→坏 YAML）
    m = re.search(rf'^{re.escape(key)}:.*?(?=\n[^ \t#\n]|\Z)', text, re.M | re.S)
    return m.group(0) if m else ''

inherited = []
for key in ('物理锚点', '道具'):
    src_block = block(source, key)
    if not src_block:
        print(f"[WARN] 旧场景缺字段 {key}，跳过继承")
        continue
    pattern = rf'^{re.escape(key)}:.*?(?=\n[^ \t#\n]|\Z)'
    # P6: 去掉 src_block.replace('\\','\\\\')——re.sub 对 callable 返回值不再解析转义，加倍反斜杠反而污染数据
    target = re.sub(pattern, lambda m: src_block, target, count=1, flags=re.M | re.S)
    inherited.append(key)
open(target_path, 'w').write(target)
print(f"[OK] 场景继承: {source_path.split('/')[-2]} -> {target_path.split('/')[-2]} ({'、'.join(inherited)})")
PYEOF
    # 继承后立即校验新场景 YAML 可解析（防坏格式静默通过）
    if ! python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "$SCENE_DIR/scene_state.yaml" 2>/dev/null; then
      echo "[ERR] 继承后 $SCENE_DIR/scene_state.yaml 无法解析（源格式非标准）——请手动修复该文件（如改用 '名称: 描述' 冒号格式），不要继续使用坏文件" >&2
      exit 1
    fi
fi

# start_snapshot.md（角色姿态/道具位置用 <!-- --> 注释占位，与 templates/start_snapshot.md 对齐——不生成空列表）
cat > "$SCENE_DIR/start_snapshot.md" << 'SNAP'
# 场景起点快照 — __SCENE_NAME__

## 冻结时间
第X日 HH:MM

## 角色姿态（此场景开场时的位置/姿势/状态）
- <!-- 角色名：站立/坐/靠位置+正在做什么 -->
- <!-- 角色名：同上 -->

## 道具位置（此场景开场时的物品位置）
- <!-- 道具名(ID)：位置，状态 -->
- <!-- 道具名(ID)：位置，状态 -->
SNAP

# narrative.md（空文件——每轮由 write_narrative.sh 轮转写入，创建时留空为设计）
touch "$SCENE_DIR/narrative.md"

# 替换占位符（scene_card + start_snapshot；缺省类型/时间/出场给「待填」，避免模板示例误导为真实数据）
# P7: 所有 sed 替换经 sed_escape 转义——场景名/时间/类型含 / & \ 不再破坏 sed
SCENE_ID_E=$(sed_escape "$SCENE_ID")
SCENE_NAME_E=$(sed_escape "$SCENE_NAME")
[ -n "$SCENE_TYPE" ] || SCENE_TYPE="待填"
[ -n "$SCENE_TIME" ] || SCENE_TIME="待填"
[ -n "$SCENE_CAST" ] || SCENE_CAST="待填"
SCENE_TYPE_E=$(sed_escape "$SCENE_TYPE")
SCENE_TIME_E=$(sed_escape "$SCENE_TIME")
SCENE_CAST_E=$(sed_escape "$SCENE_CAST")
sed -i "s/__SCENE_ID__/$SCENE_ID_E/g" "$SCENE_DIR/scene_card.md"
sed -i "s/__SCENE_NAME__/$SCENE_NAME_E/g" "$SCENE_DIR/scene_card.md"
sed -i "s/__SCENE_NAME__/$SCENE_NAME_E/g" "$SCENE_DIR/start_snapshot.md"
sed -i "s/__SCENE_TYPE__/$SCENE_TYPE_E/g" "$SCENE_DIR/scene_card.md"
sed -i "s/__SCENE_TIME__/$SCENE_TIME_E/g" "$SCENE_DIR/scene_card.md"
sed -i "s/__SCENE_CAST__/$SCENE_CAST_E/g" "$SCENE_DIR/scene_card.md"
sed -i "s/第X日 HH:MM/$SCENE_TIME_E/g" "$SCENE_DIR/start_snapshot.md"

# ── CHAR_state 骨架补建（防线：write-raw 要求状态文件已存在——出场角色缺状态文件则当场建骨架）──
if [ -n "$SCENE_CAST" ]; then
  OLD_IFS="$IFS"; IFS=','
  for c in $SCENE_CAST; do
    name=$(echo "$c" | sed 's/(.*//' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    [ -z "$name" ] && continue
    state_file="$WORLD_DIR/CHAR_${name}_state.yaml"
    if [ ! -f "$state_file" ]; then
      if [ -f "$WORLDSIM_DIR/templates/CHAR_state.yaml" ]; then
        cp "$WORLDSIM_DIR/templates/CHAR_state.yaml" "$state_file"
        echo "[OK] CHAR_state 骨架已补建: $name"
      else
        echo "[WARN] 模板缺失，跳过 CHAR_state 骨架补建: $name" >&2
      fi
    fi
  done
  IFS="$OLD_IFS"
fi

# 更新场景索引（用 printf 避免 POSIX echo 不解释 \n；表头与 templates/INDEX.md 对齐：场景名称/基准时间——P5）
INDEX_FILE="$WORLD_DIR/scenes/INDEX.md"
if [ ! -f "$INDEX_FILE" ]; then
  printf '# 场景索引\n\n| ID | 场景名称 | 类型 | 基准时间 | 出场 | 状态 |\n|----|------|------|------|------|------|\n' > "$INDEX_FILE"
fi
# P8: 追加插入——场景 ID 按空间/时间递增规则生成（S01→S02→…），追加即自然有序，无需按 ID 重排
# P1: 插入行用 --type/--time/--cast 实值（不再写死空列与「第X日 HH:MM」占位）
if grep -q "^| ${SCENE_ID} |" "$INDEX_FILE" 2>/dev/null; then
  echo "[WARN] 场景 ${SCENE_ID} 已存在于索引中，跳过索引更新"
else
  LAST_ROW=$(grep -n "^| [A-Z][0-9][0-9]* |" "$INDEX_FILE" | tail -1 | cut -d: -f1)
  if [ -n "$LAST_ROW" ]; then
    sed -i "${LAST_ROW}a\\| ${SCENE_ID} | ${SCENE_NAME_E} | ${SCENE_TYPE_E} | ${SCENE_TIME_E} | ${SCENE_CAST_E} | ACTIVE |" "$INDEX_FILE"
  else
    # printf 分支用原始值（sed_escape 只服务于 sed 命令，printf %s 不解释转义——传 _E 会把 \& 字面写入）
    printf '| %s | %s | %s | %s | %s | ACTIVE |\n' "$SCENE_ID" "$SCENE_NAME" "$SCENE_TYPE" "$SCENE_TIME" "$SCENE_CAST" >> "$INDEX_FILE"
  fi
fi

echo "[OK] 场景已创建: $SCENE_DIR"
echo "[OK] 索引文件已更新: $INDEX_FILE"

# 同步 world_state.焦点场景（唯一权威源，顶层第一行）——旧世界无 world_state.yaml 则跳过
WS_FILE="$WORLD_DIR/world_state.yaml"
if [ -f "$WS_FILE" ]; then
  if grep -q "^焦点场景:" "$WS_FILE" 2>/dev/null; then
    sed -i "s/^焦点场景:.*/焦点场景: $SCENE_ID/" "$WS_FILE"
  else
    sed -i "1i\\焦点场景: $SCENE_ID" "$WS_FILE"
  fi
  echo "[OK] world_state.焦点场景 已更新为 $SCENE_ID"
fi
