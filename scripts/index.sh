#!/usr/bin/env sh
# index.sh — 场景索引管理
#
# 用法:
#   index.sh <世界名> add      <场景ID> <名称> [类型] [时间] [出场] [状态]
#   index.sh <世界名> update   <场景ID> [--type 值] [--time 值] [--cast 值] [--status 值]
#   index.sh <世界名> activate <场景ID>
#   index.sh <世界名> remove   <场景ID>
#   index.sh <世界名> show
#
# 示例:
#   index.sh malena add S05 菜市场 EXT "1941年6月，下午4:00" "Malèna, Renato"
#   index.sh malena update S03 --status COMPLETED --type INT
#   index.sh malena activate S04

set -e

# 参数顺序兼容（2026-08-06）：`index.sh <世界名> <action>`（原）与 `index.sh <action> <世界名>`（LLM 直觉：动作→对象）都支持
case "$1" in
  add|update|activate|remove|show)
    ACTION="$1"
    WORLD="$2"
    ;;
  *)
    WORLD="$1"
    ACTION="$2"
    ;;
esac
[ -z "$WORLD" ] && echo "用法: index.sh <世界名> <add|update|activate|remove|show> [...]" && exit 1
[ -z "$ACTION" ] && echo "用法: index.sh <世界名> <add|update|activate|remove|show> [...]" && exit 1

# 世界名校验：只禁路径分隔符/穿越（允许中文·如「遗弃之地」）
case "$WORLD" in
  ''|*/*|*\\*|*..*) echo "[ERR] 非法世界名 '$WORLD'（禁止路径分隔符/../相对路径穿越）" >&2; exit 1 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORLDS_ROOT="${WORLDSIM_WORLDS_DIR:-$SKILL_DIR/worlds}"
WORLD_DIR="$WORLDS_ROOT/$WORLD"
FILEPATH="$WORLD_DIR/scenes/INDEX.md"

[ -d "$WORLD_DIR" ] || { echo "[ERR] 世界 '$WORLD' 不存在"; exit 1; }

# ---- Helpers ----
sed_escape() {
  echo "$1" | sed 's/[\/&\\]/\\&/g'
}

ensure_index() {
  if [ ! -f "$FILEPATH" ]; then
    mkdir -p "$WORLD_DIR/scenes"
    cat > "$FILEPATH" << 'EOF'
# 场景索引

| ID | 场景名称 | 类型 | 基准时间 | 出场 | 状态 |
|----|------|------|------|------|------|
EOF
  fi
}

case "$ACTION" in
  add)
    SCENE_ID="$3"
    SCENE_NAME="$4"
    SCENE_TYPE="${5:-}"
    SCENE_TIME="${6:-}"
    SCENE_CAST="${7:-}"
    SCENE_STATUS="${8:-ACTIVE}"

    [ -z "$SCENE_ID" ] && { echo "[ERR] 缺少场景ID (如 S05)"; exit 1; }
    [ -z "$SCENE_NAME" ] && { echo "[ERR] 缺少场景名"; exit 1; }

    ensure_index

    if grep -q "^| ${SCENE_ID} |" "$FILEPATH" 2>/dev/null; then
      echo "[WARN] 场景 ${SCENE_ID} 已存在于索引中"
      exit 0
    fi

    NAME_E=$(sed_escape "$SCENE_NAME")
    TYPE_E=$(sed_escape "$SCENE_TYPE")
    TIME_E=$(sed_escape "$SCENE_TIME")
    CAST_E=$(sed_escape "$SCENE_CAST")
    STATUS_E=$(sed_escape "$SCENE_STATUS")

    LAST_ROW=$(grep -n "^| [A-Z][0-9][0-9]* |" "$FILEPATH" | tail -1 | cut -d: -f1)
    if [ -n "$LAST_ROW" ]; then
      sed -i "${LAST_ROW}a\\\\| ${SCENE_ID} | ${NAME_E} | ${TYPE_E} | ${TIME_E} | ${CAST_E} | ${STATUS_E} |" "$FILEPATH"
    else
      echo "| ${SCENE_ID} | ${NAME_E} | ${TYPE_E} | ${TIME_E} | ${CAST_E} | ${STATUS_E} |" >> "$FILEPATH"
    fi
    echo "[OK] 索引 +${SCENE_ID} ${SCENE_NAME}"
    ;;

  update)
    SCENE_ID="$3"
    [ -z "$SCENE_ID" ] && { echo "[ERR] 缺少场景ID"; exit 1; }
    [ -f "$FILEPATH" ] || { echo "[ERR] INDEX.md 不存在"; exit 1; }
    grep -q "^| ${SCENE_ID} |" "$FILEPATH" || { echo "[ERR] 场景 ${SCENE_ID} 不在索引中"; exit 1; }

    # 安全更新列：sed 替换后必须验证行确实变化，否则报错退出（防假 OK——畸形行匹配失败时 sed 静默返回 0）
    update_col() {
      # $1=列号(2-6)，$2=显示名，$3=新值
      local col="$1" pname="$2" newval="$3"
      local S before after col_val
      S=$(sed_escape "$newval")
      before=$(grep "^| ${SCENE_ID} |" "$FILEPATH")
      # 幂等：对应列已含目标值 → 直接成功（不执行 sed，避免 before==after 被误判为"行格式异常"）
      col_val=$(printf '%s' "$before" | awk -F'|' -v c="$((col+1))" '{gsub(/^[ \t]+|[ \t]+$/, "", $c); print $c}')
      if [ "$col_val" = "$newval" ]; then
        echo "[OK] ${SCENE_ID} ${pname}=${newval}（幂等跳过）"
        return 0
      fi
      case "$col" in
        2) sed -i "/^| ${SCENE_ID} |/s/^\\(| [^|]* |\\) [^|]* |/\\1 ${S} |/" "$FILEPATH" ;;
        3) sed -i "/^| ${SCENE_ID} |/s/^\\(| [^|]* | [^|]* |\\) [^|]* |/\\1 ${S} |/" "$FILEPATH" ;;
        4) sed -i "/^| ${SCENE_ID} |/s/^\\(| [^|]* | [^|]* | [^|]* |\\) [^|]* |/\\1 ${S} |/" "$FILEPATH" ;;
        5) sed -i "/^| ${SCENE_ID} |/s/^\\(| [^|]* | [^|]* | [^|]* | [^|]* |\\) [^|]* |/\\1 ${S} |/" "$FILEPATH" ;;
        6) sed -i "/^| ${SCENE_ID} |/s/^\\(| [^|]* | [^|]* | [^|]* | [^|]* | [^|]* |\\) [^|]* |/\\1 ${S} |/" "$FILEPATH" ;;
      esac
      after=$(grep "^| ${SCENE_ID} |" "$FILEPATH")
      if [ -z "$after" ] || [ "$before" = "$after" ]; then
        echo "[ERR] ${SCENE_ID} ${pname} 更新失败：索引行未变化（行格式异常），请手动修复 INDEX.md 该行" >&2
        exit 1
      fi
      echo "[OK] ${SCENE_ID} ${pname}=${newval}"
    }

    shift 3
    while [ $# -gt 0 ]; do
      case "$1" in
        --type)   update_col 3 "类型" "$2"; shift 2 ;;
        --time)   update_col 4 "时间" "$2"; shift 2 ;;
        --cast)   update_col 5 "出场" "$2"; shift 2 ;;
        --status) update_col 6 "状态" "$2"; shift 2 ;;
        --name)   update_col 2 "名称" "$2"; shift 2 ;;
        *) echo "[ERR] 未知参数: $1"; exit 1 ;;
      esac
    done
    ;;

  activate)
    SCENE_ID="$3"
    [ -z "$SCENE_ID" ] && { echo "[ERR] 缺少场景ID"; exit 1; }
    [ -f "$FILEPATH" ] || { echo "[ERR] INDEX.md 不存在"; exit 1; }

    # 将该场景状态改为 ACTIVE
    sed -i "/^| ${SCENE_ID} |/s/| [^|]* |$/| ACTIVE |/" "$FILEPATH"

    # 其他场景（以 | S 开头）改为 COMPLETED（排除表头/分割线/目标场景）
    sed -i "/^| S/{
      /^| ${SCENE_ID} |/!{
        s/| [^|]* |$/| COMPLETED |/
      }
    }" "$FILEPATH"

    # 同步 world_state.焦点场景（唯一权威源）——旧世界无 world_state.yaml 则跳过
    WS_FILE="$WORLD_DIR/world_state.yaml"
    if [ -f "$WS_FILE" ]; then
      if grep -q "^焦点场景:" "$WS_FILE" 2>/dev/null; then
        sed -i "s/^焦点场景:.*/焦点场景: $SCENE_ID/" "$WS_FILE"
      else
        sed -i "1i\\焦点场景: $SCENE_ID" "$WS_FILE"
      fi
      echo "[OK] world_state.焦点场景 已更新为 $SCENE_ID"
    fi

    echo "[OK] ${SCENE_ID} 设为 ACTIVE，其余标记 COMPLETED"
    ;;

  remove)
    SCENE_ID="$3"
    [ -z "$SCENE_ID" ] && { echo "[ERR] 缺少场景ID"; exit 1; }
    [ -f "$FILEPATH" ] || { echo "[ERR] INDEX.md 不存在"; exit 1; }
    sed -i "/^| ${SCENE_ID} |/d" "$FILEPATH"
    echo "[OK] 索引已移除: ${SCENE_ID}"
    ;;

  show)
    [ -f "$FILEPATH" ] && cat "$FILEPATH" || echo "(INDEX.md 不存在)"
    ;;

  *)
    echo "[ERR] 未知操作: $ACTION (支持: add/update/activate/remove/show)"
    exit 1
    ;;
esac
exit 0
