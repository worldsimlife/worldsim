#!/bin/sh
# snap.sh — 状态快照存档（V2）
# 备份范围（全量）：
#   - 动态状态: world_state.yaml conflicts.yaml off_focus/pending_actions.yaml world_map.yaml(可选)
#   - 角色状态: CHAR_*_state.yaml
#   - 场景: scenes/ 全目录（INDEX.md + 每个场景的 scene_state/narrative/scene_card/start_snapshot）
# 焦点场景唯一权威源 = world_state.yaml 顶层「焦点场景」（不再使用 .active 文件）
# 用法:
#   sh scripts/snap.sh <世界名> save [快照名]
#   sh scripts/snap.sh <世界名> load <快照名>
#   sh scripts/snap.sh <世界名> list
#   sh scripts/snap.sh <世界名> delete <快照名>
# 破坏性操作（load/delete）确认：交互终端提示 [y/N]（默认拒绝）；非交互环境（stdin 非 tty）需追加 --force 标志，否则拒绝执行。

WORLD="$1"
ACTION="$2"
SNAPNAME="$3"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WORLDS_ROOT="${WORLDSIM_WORLDS_DIR:-$SKILL_DIR/worlds}"
WORLD_DIR="$WORLDS_ROOT/$WORLD"
SNAP_DIR="$WORLD_DIR/snaps"
ARCHIVE_DIR="$WORLD_DIR/archive/scenes"

# 名称校验：世界名/快照名只禁路径分隔符/穿越（允许中文·如「遗弃之地」/「甜水镇」——自动生成名含中文场景名同理）
validate_name() {
  case "$1" in
    ''|*/*|*\\*|*..*) echo "错误: 非法名称 '$1'（禁止路径分隔符/../相对路径穿越）" >&2; exit 1 ;;
  esac
}

# 破坏性操作确认：--force 直过；交互终端提示 [y/N]（默认拒绝）；非交互且无 --force → 拒绝执行
FORCE=0
for _a in "$@"; do [ "$_a" = "--force" ] && FORCE=1; done
confirm_destructive() {
  [ "$FORCE" = "1" ] && return 0
  if [ ! -t 0 ]; then
    echo "错误: 非交互环境执行破坏性操作需显式 --force 标志（sh scripts/snap.sh $WORLD $ACTION $SNAPNAME --force）" >&2
    exit 1
  fi
  printf "%s [y/N] " "$1"
  read _answer
  case "$_answer" in y|Y|yes|YES) return 0 ;; *) echo "已取消"; exit 0 ;; esac
}

validate_name "$WORLD"
[ -d "$WORLD_DIR" ] || { echo "ERROR: world '$WORLD' not found"; exit 1; }
mkdir -p "$SNAP_DIR"

# 需要备份的动态状态文件（焦点场景在 world_state.yaml 内，无独立 .active）
# world_map.yaml 为可选增强层——缺失时 copy_if_exists 自动跳过
STATE_FILES="world_state.yaml conflicts.yaml off_focus/pending_actions.yaml world_map.yaml"

# 获取焦点场景短 ID（唯一权威源 = world_state.yaml 顶层「焦点场景」）
get_focus_scene() {
  grep -E "^焦点场景:" "$WORLD_DIR/world_state.yaml" 2>/dev/null | head -1 | sed 's/^焦点场景:[[:space:]]*//' | tr -d '[:space:]'
}

# 获取焦点场景目录名（短 ID 前缀匹配）
get_focus_scene_name() {
  SCENE_ID=$(get_focus_scene)
  [ -n "$SCENE_ID" ] && ls -d "$WORLD_DIR/scenes/${SCENE_ID}-"* 2>/dev/null | head -1 | sed 's/.*\/scenes\///' || echo ""
}

# 拷贝单个文件（如果存在）
copy_if_exists() {
  src="$1"; dst_dir="$2"
  [ -f "$src" ] && cp "$src" "$dst_dir/"
}

case "$ACTION" in
  save)
    ACTIVE=$(get_focus_scene)
    if [ -z "$SNAPNAME" ]; then
      ACTIVE_NAME="$(get_focus_scene_name)"
      ROUND=$(grep -E "^轮次:" "$WORLD_DIR/world_state.yaml" 2>/dev/null | head -1 | sed 's/^轮次:[[:space:]]*//' | tr -d "[:space:]'\"")
      if [ -n "$ROUND" ]; then
        SNAPNAME="r${ROUND}-${ACTIVE_NAME}-$(date +%Y%m%d-%H%M%S)"
      else
        SNAPNAME="${ACTIVE_NAME}-$(date +%Y%m%d-%H%M%S)"
      fi
      SNAPNAME=$(echo "$SNAPNAME" | sed 's/--*/-/g; s/^-//; s/-$//')
      echo "未指定存档名，自动生成: $SNAPNAME"
    fi
    validate_name "$SNAPNAME"
    OUTDIR="$SNAP_DIR/$SNAPNAME"
    rm -rf "$OUTDIR"
    mkdir -p "$OUTDIR"

    file_count=0

    # 1. 顶层动态状态文件
    for f in $STATE_FILES; do
      copy_if_exists "$WORLD_DIR/$f" "$OUTDIR" && file_count=$((file_count + 1))
    done

    # 2. 所有角色动态状态
    for f in "$WORLD_DIR"/CHAR_*_state.yaml; do
      [ -f "$f" ] || continue
      cp "$f" "$OUTDIR/" && file_count=$((file_count + 1))
    done

    # 3. scenes/ 全量备份（INDEX.md + 每个场景目录全部文件）
    if [ -d "$WORLD_DIR/scenes" ]; then
      cp -r "$WORLD_DIR/scenes" "$OUTDIR/scenes"
      SCENE_FILE_COUNT=$(find "$OUTDIR/scenes" -type f | wc -l | tr -d ' ')
      file_count=$((file_count + SCENE_FILE_COUNT))
    fi

    # 4. 生成 manifest（纯文本清单，可读可恢复校验）
    MANIFEST="$OUTDIR/MANIFEST.md"
    {
      echo "# 存档清单: $SNAPNAME"
      echo ""
      echo "创建时间: $(date '+%Y-%m-%d %H:%M:%S')"
      echo "来源世界: $WORLD"
      if [ -n "$ACTIVE" ]; then
        echo "焦点场景: ${ACTIVE} ($(get_focus_scene_name))"
      fi
      echo ""
      echo "## 文件列表"
      echo ""
      find "$OUTDIR" -type f ! -name 'MANIFEST.md' | sort | while read -r f; do
        rel="${f#$OUTDIR/}"
        size=$(wc -c < "$f")
        echo "- \`$rel\` ($size B)"
      done
    } > "$MANIFEST"
    file_count=$((file_count + 1))

    echo "已保存快照: $SNAPNAME ($file_count 个文件，scenes 已全量备份)"
    ;;

  load)
    [ -z "$SNAPNAME" ] && { echo "ERROR: 需要快照名称"; exit 1; }
    validate_name "$SNAPNAME"
    SRCDIR="$SNAP_DIR/$SNAPNAME"
    [ -d "$SRCDIR" ] || { echo "ERROR: 快照 '$SNAPNAME' 不存在"; exit 1; }
    confirm_destructive "载入快照 '$SNAPNAME' 将覆盖当前世界状态（当前状态会自动备份到 _before_）"

    # 加载前自动备份当前状态
    BAKDIR="$SNAP_DIR/_before_$(date +%s)"
    mkdir -p "$BAKDIR"
    for f in $STATE_FILES; do
      copy_if_exists "$WORLD_DIR/$f" "$BAKDIR"
    done
    for f in "$WORLD_DIR"/CHAR_*_state.yaml; do
      [ -f "$f" ] && cp "$f" "$BAKDIR/"
    done
    if [ -d "$WORLD_DIR/scenes" ]; then
      cp -r "$WORLD_DIR/scenes" "$BAKDIR/scenes"
    fi
    echo "当前状态已备份到: _before_$(date +%s)"

    restored=0

    # 恢复顶层动态状态文件
    for f in $STATE_FILES; do
      fname=$(basename "$f")
      if [ -f "$SRCDIR/$fname" ]; then
        cp "$SRCDIR/$fname" "$WORLD_DIR/$f" && restored=$((restored + 1)) && echo "  恢复: $f"
      fi
    done

    # 恢复角色状态（存档中的覆盖；磁盘有而存档无的保留——角色状态以存档为准，多余文件不删）
    for f in "$SRCDIR"/CHAR_*_state.yaml; do
      [ -f "$f" ] || continue
      fname=$(basename "$f")
      cp "$f" "$WORLD_DIR/"
      restored=$((restored + 1))
      echo "  恢复: $fname"
    done

    # ── 场景目录差异恢复 ──
    if [ -d "$SRCDIR/scenes" ]; then
      mkdir -p "$WORLD_DIR/scenes"
      TMP_ARC=$(mktemp); TMP_DISK=$(mktemp)
      (cd "$SRCDIR/scenes" && find . -type f | sort) > "$TMP_ARC"
      (cd "$WORLD_DIR/scenes" && find . -type f | sort) > "$TMP_DISK"

      # 1. 存档有（磁盘无或已有）→ 覆盖恢复
      while IFS= read -r rel; do
        [ -z "$rel" ] && continue
        mkdir -p "$(dirname "$WORLD_DIR/scenes/$rel")"
        if [ -f "$SRCDIR/scenes/$rel" ]; then
          cp "$SRCDIR/scenes/$rel" "$WORLD_DIR/scenes/$rel"
          restored=$((restored + 1))
          echo "  恢复: scenes/$rel"
        fi
      done < "$TMP_ARC"

      # 2. 磁盘有而存档无 → 移入 archive（保留不删）
      TS=$(date +%Y%m%d-%H%M%S)
      while IFS= read -r rel; do
        [ -z "$rel" ] && continue
        if ! grep -qxF "$rel" "$TMP_ARC"; then
          mkdir -p "$ARCHIVE_DIR/$TS/$(dirname "$rel")"
          mv "$WORLD_DIR/scenes/$rel" "$ARCHIVE_DIR/$TS/$rel"
          echo "  归档(存档无此文件): scenes/$rel"
        fi
      done < "$TMP_DISK"

      # 3. 清理空目录（磁盘上被整体归档后留下的空壳）
      find "$WORLD_DIR/scenes" -type d -empty -not -path "$WORLD_DIR/scenes" -delete 2>/dev/null

      rm -f "$TMP_ARC" "$TMP_DISK"
    fi

    # 4. 清理遗留的 .active（已废弃——焦点场景唯一权威源 = world_state.yaml）
    if [ -f "$WORLD_DIR/.active" ]; then
      mkdir -p "$ARCHIVE_DIR/legacy_active_$(date +%s)"
      mv "$WORLD_DIR/.active" "$ARCHIVE_DIR/legacy_active_$(date +%s)/.active"
      echo "  已归档废弃文件: .active（焦点场景现由 world_state.yaml 顶层「焦点场景」管理）"
    fi

    echo "已恢复快照: $SNAPNAME ($restored 个文件)"
    echo "建议执行: python3 $SCRIPT_DIR/worldctl.py $WORLD validate"
    ;;

  list)
    echo "== $WORLD 的快照列表 =="
    for d in "$SNAP_DIR"/*/; do
      [ -d "$d" ] || continue
      name=$(basename "$d")
      cnt=$(find "$d" -type f | wc -l)
      focus=$(grep -E "^焦点场景:" "$d/world_state.yaml" 2>/dev/null | head -1 | sed 's/^焦点场景:[[:space:]]*//' | tr -d '[:space:]')
      echo "  $name ($cnt 文件)${focus:+ [焦点: $focus]}"
    done
    ;;

  delete)
    [ -z "$SNAPNAME" ] && { echo "ERROR: 需要快照名称"; exit 1; }
    validate_name "$SNAPNAME"
    TARGET="$SNAP_DIR/$SNAPNAME"
    [ -d "$TARGET" ] || { echo "ERROR: 快照 '$SNAPNAME' 不存在"; exit 1; }
    confirm_destructive "删除快照 '$SNAPNAME' 不可恢复"
    rm -rf "$TARGET"
    echo "已删除快照: $SNAPNAME"
    ;;

  *)
    echo "用法: snap.sh <世界名> save|load|delete [快照名]"
    exit 1
    ;;
esac

exit 0
