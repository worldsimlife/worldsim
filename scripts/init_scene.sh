#!/usr/bin/env sh
# init_scene.sh — 创建新场景目录及模板文件
# 用法: init_scene.sh <世界名> <场景ID> <场景名> [--from <旧场景ID>] [--place <档案路径>] [--type <类型>] [--time <时间>] [--cast <出场角色>]
#   --from <旧场景ID|旧场景目录名>: 继承旧场景 scene_state 的物理锚点/道具清单
#     （同物理地点切换必用——同一栋建筑的空间元素不因时间区间变化而消失，防止从零重建导致漏继承）
#   --place <档案路径>: 区域静态档案指针（相对世界目录，如 regions/甜水镇/REGION.md）——无 --from 时
#     作为 scene_state 物理锚点基线来源（首次到达·初始设定）；只校验存在性，内容由场记读档案生成

WORLD="$1"
SCENE_ID="$2"
SCENE_NAME="$3"
shift 3
SCENE_TYPE=""
SCENE_TIME=""
SCENE_CAST=""
INHERIT_FROM=""
PLACE_ARCHIVE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) INHERIT_FROM="$2"; shift 2 ;;
    --place) PLACE_ARCHIVE="$2"; shift 2 ;;
    --type) SCENE_TYPE="$2"; shift 2 ;;
    --time) SCENE_TIME="$2"; shift 2 ;;
    --cast) SCENE_CAST="$2"; shift 2 ;;
    *) echo "[ERR] 未知参数: $1（支持: --from <旧场景ID> / --place <档案路径> / --type <类型> / --time <时间> / --cast <出场角色>）"; exit 1 ;;
  esac
done

if [ -z "$WORLD" ] || [ -z "$SCENE_ID" ] || [ -z "$SCENE_NAME" ]; then
  echo "用法: init_scene.sh <世界名> <场景ID> <场景名> [--from <旧场景ID>] [--place <档案路径>] [--type <类型>] [--time <时间>] [--cast <出场角色>]"
  echo "示例: init_scene.sh 遗弃之地 S07 追踪血迹 --type EXT --time '第3日 09:00' --cast 'Guest, Maeve'"
  echo "示例: init_scene.sh 遗弃之地 S08 追踪血迹 --from S07 --type INT --time '第3日 12:00'"
  echo "示例: init_scene.sh 遗弃之地 S09 首次入镇 --place regions/甜水镇/REGION.md --type EXT"
  exit 1
fi

# 世界名校验：只禁路径分隔符/穿越（允许中文·如「遗弃之地」）
case "$WORLD" in
  ''|*/*|*\\*|*..*) echo "[ERR] 非法世界名 '$WORLD'（禁止路径分隔符/../相对路径穿越）" >&2; exit 1 ;;
esac

# 场景名是目录名的一部分——禁止含路径分隔符（/）或反斜杠（\），防止破坏 scenes/ 目录结构
case "$SCENE_NAME" in
  */*|*\\) echo "[ERR] 场景名不能含 / 或 \\（场景名=目录名，含分隔符会破坏目录结构）: $SCENE_NAME" >&2; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORLDS_ROOT="${WORLDSIM_WORLDS_DIR:-$SKILL_DIR/worlds}"
WORLD_DIR="$WORLDS_ROOT/$WORLD"
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

# ── --place 预检：档案指针必须存在（相对世界目录·如 regions/甜水镇/REGION.md）──
if [ -n "$PLACE_ARCHIVE" ]; then
  PLACE_FP="$WORLD_DIR/$PLACE_ARCHIVE"
  if [ ! -f "$PLACE_FP" ]; then
    echo "[ERR] --place 档案不存在（$PLACE_FP）——检查 regions/ 路径或补建档案（模板: templates/REGION.md）" >&2
    exit 1
  fi
  echo "[OK] 物理基线来源: $PLACE_ARCHIVE（场记据档案生成 scene_state 物理锚点·对照全局标记覆盖不可逆变更）"
  echo "[区域] scene_card 区域行（场记生成 scene_card.md 时照抄）: | 区域 | $PLACE_ARCHIVE |"
else
  # 未传 --place：从当前焦点场景区域档案的相邻/子区域自动扫描候选（脚本核对·LLM 照抄）
  echo "[候选] 未传 --place——从当前焦点场景区域档案扫描相邻/子区域候选（已有 region 必须引用·禁止新建）:"
  CUR_SCENE=$(grep -m1 '^焦点场景:' "$WORLD_DIR/states/world_state.yaml" 2>/dev/null | awk '{print $2}' | tr -d "'\" ")
  CUR_CARD=""
  if [ -n "$CUR_SCENE" ]; then
    CUR_CARD=$(ls "$WORLD_DIR/scenes/${CUR_SCENE}-"*/scene_card.md 2>/dev/null | head -1)
  fi
  if [ -n "$CUR_CARD" ] && [ -f "$CUR_CARD" ]; then
    CUR_ARCH=$(grep -m1 '^| 区域 |' "$CUR_CARD" | sed 's/^| 区域 | *//; s/ *|$//' | sed 's/^ *//; s/ *$//')
    if [ -n "$CUR_ARCH" ] && [ -f "$WORLD_DIR/$CUR_ARCH" ]; then
      echo "  当前场景区域档案: $CUR_ARCH"
      grep -E '^- ' "$WORLD_DIR/$CUR_ARCH" 2>/dev/null | sed 's/^- //; s/（.*//; s/(.*//' | while IFS= read -r name; do
        [ -z "$name" ] && continue
        match=$(find "$WORLD_DIR/regions" -type d -name "$name" 2>/dev/null | head -1)
        if [ -n "$match" ]; then
          rel="${match#$WORLD_DIR/}"
          echo "  - $name → $rel/REGION.md"
        fi
      done
    else
      echo "  （当前焦点场景无区域档案·检查 regions/ 目录树）"
    fi
  else
    echo "  （当前焦点场景无 scene_card/区域行·检查 regions/ 目录树）"
  fi
fi

mkdir -p "$SCENE_DIR"


# scene_card.md / start_snapshot.md / CHAR_state：按 templates/ 直接生成完整文件（脚本不生成内容骨架）
# scene_state.yaml（新键表，见 references/keys.md §scene_state.yaml；脚本只建空值骨架，字段值随剧情轮 change set 注册自然累积）
# 元素随剧情轮注册自然累积（物理锚点/道具/核心状态/关键场景信息/出场角色摘要）。
# 场景时间线【禁止预写】——剧情事件一律由每轮 change set ###APPEND: 追加（预写=把计划当记录·会与 change set 双写重复）。
cat > "$SCENE_DIR/scene_state.yaml" << 'STATE'
核心状态: ''
场景时间线: ''
物理锚点: ''
道具: ''
关键场景信息: ''
出场角色摘要: ''
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
src_name = source_path.split('/')[-2]
for key in ('物理锚点', '道具'):
    src_block = block(source, key)
    if not src_block:
        print(f"[WARN] 旧场景缺字段 {key}，跳过继承")
        continue
    pattern = rf'^(# 道具清单继承自[^\n]*\n)?{re.escape(key)}:.*?(?=\n[^ \t#\n]|\Z)'
    # P6: 去掉 src_block.replace('\\','\\\\')——re.sub 对 callable 返回值不再解析转义，加倍反斜杠反而污染数据
    if key == '道具':
        # 时间感知提醒（仅继承场景）：道具状态随时间流逝自然变化——倒了的酒隔几天会干涸；位置一般不变
        def repl_prop(m):
            return f'# 道具清单继承自 {src_name}：状态随时间流逝自然变化，请按当前时间更新（位置一般不变）\n' + src_block
        target = re.sub(pattern, repl_prop, target, count=1, flags=re.M | re.S)
    else:
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

# narrative.md（空文件——每轮由 write_narrative.sh 轮转写入，创建时留空为设计）
touch "$SCENE_DIR/narrative.md"

# INDEX 行转义变量（场景名/时间/类型含 / & \ 时经 sed_escape 防破坏 sed——P7）
[ -n "$SCENE_TYPE" ] || SCENE_TYPE="待填"
[ -n "$SCENE_TIME" ] || SCENE_TIME="待填"
[ -n "$SCENE_CAST" ] || SCENE_CAST="待填"
SCENE_ID_E=$(sed_escape "$SCENE_ID")
SCENE_NAME_E=$(sed_escape "$SCENE_NAME")
SCENE_TYPE_E=$(sed_escape "$SCENE_TYPE")
SCENE_TIME_E=$(sed_escape "$SCENE_TIME")
SCENE_CAST_E=$(sed_escape "$SCENE_CAST")

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
WS_FILE="$WORLD_DIR/states/world_state.yaml"
if [ -f "$WS_FILE" ]; then
  if grep -q "^焦点场景:" "$WS_FILE" 2>/dev/null; then
    sed -i "s/^焦点场景:.*/焦点场景: $SCENE_ID/" "$WS_FILE"
  else
    sed -i "1i\\焦点场景: $SCENE_ID" "$WS_FILE"
  fi
  echo "[OK] world_state.焦点场景 已更新为 $SCENE_ID"
fi

# ── 待填清单输出（脚本只建基础设施——内容文件按 templates/ 直接生成，禁止带模板占位运行）──
echo ""
echo "【注意】本目录已生成 scene_state.yaml / narrative.md（骨架·已存在）——后续用 Write/覆盖写前必须先 Read 该文件再改（写入工具拒绝未读覆盖）。"
echo ""
echo "【场景待填清单·创建后立即填充·禁止带模板占位（[字段定义]/(例:) 残留）运行】:"
echo "  1. scene_card.md      按 templates/scene_card.md 生成：焦外/在场 · 场景目标 · 前情钩子"
echo "  2. scene_state.yaml   已建空值骨架——元素随剧情轮 change set 注册自然累积（入场帧已涉及的元素随 change set 正常记录）"
echo "  3. start_snapshot.md  按 templates/start_snapshot.md 生成：角色姿态 / 道具位置 / 开场心理态 / 开场 conflicts 节拍态 / 开场 world_state 附加态 / 焦外待揭示"
echo "  4. CHAR_state         出场角色按 templates/CHAR_state.yaml 生成状态文件（核心状态/情绪/位置/压力水平/防御有效性等）"
exit 0
