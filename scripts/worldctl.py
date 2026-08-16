#!/usr/bin/env python3
"""
worldctl.py — WorldSim 批量状态管理 V2

用法:
  worldctl.py <世界名> read                ← 读取所有 .yaml 状态文件 → stdout（合并 YAML）
  worldctl.py <世界名> read --files a,b,c  ← 限读指定文件
  worldctl.py <世界名> write              ← 从 stdin 读 YAML diff → 合并写入
  worldctl.py <世界名> write --full       ← 从 stdin 读完整 YAML → 覆写
  worldctl.py <世界名> write-raw <文件key> <YAML键> [内容]
                                         ← 原始文本直写（无YAML解析）
  worldctl.py <世界名> write-raw --batch  ← 批量原始文本直写，stdin 用 ###FILE/###KEY 记录格式
                                         ⚠ 非幂等：###APPEND: 重复执行会重复追加累积字段——同一批次只执行一次·验证用 read/validate/--dry-run·禁止重放 write 命令
  worldctl.py <世界名> append-raw <文件key> <YAML键> [内容]
                                         ← 追加模式原始文本直写（列表/累积字段追加·--batch 同 write-raw）
  worldctl.py <世界名> delete <文件key> <键路径>
                                         ← 删整条 CT / pending 条目（批量流支持 ###DELETE:）
  worldctl.py <世界名> convert            ← 将 .md 状态文件转为 .yaml（按章节存 block scalar）
  worldctl.py <世界名> validate           ← 验证 YAML 格式（键表/枚举/联动检查·非阻塞告警）
  worldctl.py <世界名> audit             ← 校验 stdin 的 change set 草案（###FILE/###KEY 格式），不落盘
                                         （语义不变量：代价行/载体/记忆上限/轮次单调/落点一致）
  worldctl.py <世界名> grep <关键词>      ← 全仓（含所有场景 scene_state）搜索元素注册原文
  worldctl.py <世界名> scan [--live]      ← 扫描世界状态摘要（默认含历史轮转/archive·--live 仅当前）
  worldctl.py <世界名> gate dramatist|writer [--check]
                                         ← 流程闸门（--check=从 stdin 读 change set/叙事跑代码化核验·不合格 exit 1）
  worldctl.py <世界名> beatsheet <子命令> ← 节拍表维护（show/add/stay/advance/rewrite/clear·子命令帮助 beatsheet --help）
  worldctl.py <世界名> reset-cycle [--force]
                                         ← 循环世界周期重置（全员机械重置+登记+重建倒计时）
  worldctl.py <世界名> tmp-clean         ← 清理该世界 tmp/ 下过程临时文件（跨会话恢复时自动执行）

文件格式约定:
  - 所有状态文件使用 .yaml 扩展名
  - 每个顶级章节用 YAML 映射键存储，内容为 block scalar (|)
  - 结构化的表（如 conflicts）用 mapping of mappings，键为项目ID
  - 角色状态用自由键值对 + 多行 prose 值
  
核心优化：read = 1 次 exec 获取所有状态；write = 1 次 exec 更新所有变更。
"""
import sys, os, yaml, re, shutil, argparse
from pathlib import Path

# skill 根 = 脚本自身位置推导（不可被环境变量覆写——SKILL.md/脚本/模板必须同源）
SKILL_DIR = Path(__file__).resolve().parent.parent
# worlds 根 = 可被环境变量 WORLDSIM_WORLDS_DIR 覆写（用户自己的存储）；缺省 = {skill_dir}/worlds
WORLDS_ROOT = Path(os.environ.get("WORLDSIM_WORLDS_DIR", SKILL_DIR / "worlds"))
CHAR_STATE_PREFIX = "CHAR_"
CHAR_STATE_SUFFIX = "_state.yaml"

# 节拍表（conflicts.yaml 顶层·脚本维护·LLM 不直接改）
BEAT_TOP_KEY = "节拍表"
BEAT_ENUM = ("铺垫", "接触", "升级", "顶点", "余波")

# 顶点落点（戏剧目标声明·出线核验=冲突双方关键状态变化）
CLIMAX_FORMS = ("死局两难被逼出选择", "防御当众失效", "关系不可逆断裂", "代价已付出")
CLIMAX_KEY_FIELDS = ("压力水平", "防御有效性", "核心状态", "决策状态", "人际动态", "记忆锚点", "信念演化")
CLIMAX_LIST_FIELDS = ("记忆锚点", "信念演化")
CLIMAX_BASELINE_KEY = "基准值"
# 出线形态-字段族联动：声明形态对应字段族至少一字段须发生实质变化（收束证明）
CLIMAX_FORM_FIELDS = {
    "死局两难被逼出选择": ("决策状态",),
    "防御当众失效": ("防御有效性", "核心状态"),
    "关系不可逆断裂": ("人际动态",),
    "代价已付出": ("核心状态", "记忆锚点", "信念演化"),
}

# ── 文件发现 ──────────────────────────────────────────────────────
def get_world_dir(world: str) -> Path:
    # 世界名校验：只禁路径分隔符/穿越（允许中文·如「遗弃之地」）
    if not world or "/" in world or "\\" in world or ".." in world:
        print(f"[ERR] 非法世界名 '{world}'（禁止路径分隔符/../相对路径穿越）", file=sys.stderr); sys.exit(1)
    wd = WORLDS_ROOT / world
    if not wd.is_dir():
        print(f"[ERR] 世界 '{world}' 不存在: {wd}", file=sys.stderr); sys.exit(1)
    return wd

def get_scene_dir(world_dir: Path) -> Path | None:
    """从 world_state.yaml 顶层「焦点场景」（唯一权威源）定位当前场景目录。

    兼容旧键：优先读顶层 焦点场景；找不到时回退 地点.焦点场景 / 地点.当前焦点场景。
    """
    ws_fp = world_dir / "world_state.yaml"
    if not ws_fp.exists():
        return None
    try:
        ws = yaml.safe_load(ws_fp.read_text())
    except Exception:
        return None
    if not isinstance(ws, dict):
        return None
    scene_id = str(ws.get("焦点场景", "") or "").strip()
    if not scene_id:
        loc = ws.get("地点") or {}
        scene_id = str(loc.get("焦点场景", loc.get("当前焦点场景", "")) or "").strip()
    if not scene_id:
        # 旧格式兼容（ol 型：无 world_state.yaml / 无焦点场景）→ 回退 .active
        active_file = world_dir / ".active"
        if active_file.exists():
            scene_id = active_file.read_text().strip()
    if not scene_id:
        return None
    scenes_dir = world_dir / "scenes"
    if not scenes_dir.is_dir():
        return None
    for d in scenes_dir.iterdir():
        if d.is_dir() and d.name.startswith(scene_id):
            return d
    return None

def discover_files(world_dir: Path, scene_dir: Path | None) -> dict[str, Path]:
    files = {}
    # 固定文件
    for fname in ["world_state.yaml", "conflicts.yaml", "world_map.yaml"]:
        fp = world_dir / fname
        if fp.exists(): files[fp.stem] = fp
    # 角色状态
    for fp in world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}"):
        files[fp.stem] = fp
    # 场景状态
    if scene_dir:
        ssp = scene_dir / "scene_state.yaml"
        if ssp.exists(): files["scene_state"] = ssp
    # 焦外
    ofp = world_dir / "off_focus" / "pending_actions.yaml"
    if ofp.exists(): files["pending_actions"] = ofp
    # 伏笔登记（可选·触发式）
    ffp = world_dir / "foreshadow.yaml"
    if ffp.exists(): files["foreshadow"] = ffp
    return files

# ── CHAR key 命名归一化 ──────────────────────────────────────────
def resolve_char_file(existing: dict, key: str, world_dir: Path):
    """解析 CHAR_* 写入目标。已存在→直接映射；不存在→检查空格/下划线互换及缺失 _state 后缀的相似 key，
    命中则映射到已有文件并警告（杜绝同一角色产生两份状态文件）；否则→按 key 新建。"""
    if key in existing:
        return existing[key], None
    if key.startswith(CHAR_STATE_PREFIX):
        variants = []
        if key.endswith("_state"):
            stem = key[len(CHAR_STATE_PREFIX):-len("_state")]  # 仅角色名部分做空格/下划线互换
            variants = [CHAR_STATE_PREFIX + stem.replace(" ", "_") + "_state",
                        CHAR_STATE_PREFIX + stem.replace("_", " ") + "_state"]
        else:
            variants.append(key + "_state")  # 缺失 _state 后缀
        for v in variants:
            if v in existing:
                return existing[v], f"[WARN] key '{key}' 与已有文件 '{existing[v].name}' 命名不一致(空格/下划线/_state)，已映射到已有文件，避免产生重复"
        return world_dir / f"{key}.yaml", None
    return None, None

# ── 深层合并 ──────────────────────────────────────────────────────
def deep_merge(base: dict, delta: dict) -> dict:
    for k, v in delta.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base

def write_yaml(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)

# ── CONVERT 核心 ──────────────────────────────────────────────────
def markdown_sections_to_yaml(text: str) -> dict:
    """
    将 markdown 文本按 ## 章节拆分，每个章节内容作为 block scalar。
    顶级 # 标题忽略或作为文件元。
    返回 {section_title: content_string} 的 dict。
    """
    lines = text.split("\n")
    sections = {}
    current_title = None
    current_lines = []

    def flush():
        if current_title:
            content = "\n".join(current_lines).strip()
            if content:
                # 清理标题序号（"1. ", "2. "）
                clean_title = re.sub(r"^\d+\.\s*", "", current_title).strip()
                # 清理多余的标记
                clean_title = clean_title.replace("**", "").strip()
                sections[clean_title] = content

    for line in lines:
        if line.startswith("## "):
            flush()
            current_title = line[3:].strip()
            current_lines = []
        elif line.startswith("# ") and not line.startswith("##"):
            continue  # 忽略一级标题
        else:
            current_lines.append(line)
    flush()
    return sections

def sections_to_yaml(text: str) -> dict:
    """按 ## 拆分并转为 YAML 友好结构"""
    sections = markdown_sections_to_yaml(text)
    result = {}
    for title, content in sections.items():
        # 尝试按二级子弹拆分
        result[title] = content
    return result

def convert_md_to_yaml(text: str, source_name: str) -> dict:
    """通用 .md → YAML 转换"""
    # 检查是否是表格格式
    if "|" in text and "---" in text:
        # 可能是冲突表或其他表格式 → 尝试结构化解
        return convert_table_format(text, source_name)
    # 默认：按章节 block scalar
    return sections_to_yaml(text)

def convert_table_format(text: str, source_name: str) -> dict:
    """
    处理表格格式 md（如 conflicts.md）。
    产出：{CT-ID: {field: value, ...}} 结构
    """
    result = {}
    # 按 ## CT- 拆分
    ct_blocks = re.split(r"^## (CT-\d+[^\n]*)", text, flags=re.MULTILINE)
    
    # 跳过标题行，从 CT 块开始
    i = 1 if ct_blocks and not ct_blocks[0].startswith("CT-") else 0
    while i + 1 < len(ct_blocks):
        ct_title = ct_blocks[i].strip().replace("：", ":").split("：")[0].split(" ")[0]  # "CT-01"
        ct_body = ct_blocks[i + 1]
        
        ct_data = {}
        # 在 block 内找表格行
        in_table = False
        current_field = None
        current_value = []
        
        for line in ct_body.split("\n"):
            if line.strip().startswith("|") and line.strip().endswith("|"):
                if "---" in line:
                    in_table = True
                    continue
                if in_table:
                    cells = [c.strip() for c in line.strip("|").split("|")]
                    if len(cells) >= 2:
                        field = cells[0].replace("**", "").strip()
                        value = cells[1].strip()
                        if field:
                            ct_data[field] = value
            else:
                in_table = False
                # 非表格行可能包含额外的内容
                if line.strip() and "**" in line and "：" in line:
                    parts = line.split("：", 1)
                    ct_data["_" + parts[0].replace("**", "").strip()[:20]] = parts[1].strip()
        
        if ct_data:
            result[ct_title] = ct_data
        else:
            # 退化为 block scalar
            result[ct_title] = ct_body.strip()
        
        i += 2
    
    # 如果没有解析出任何 CT
    if not result:
        return sections_to_yaml(text)
    return result

def convert_world_state(text: str) -> dict:
    """world_state.md 特殊处理"""
    sections = markdown_sections_to_yaml(text)
    result = {}
    for title, content in sections.items():
        # 尝试解析子弹列表
        items = {}
        for line in content.split("\n"):
            m = re.match(r"^- (\*\*)?(.+?)(\*\*)?:\s*(.*)", line)
            if m:
                key = m.group(2).strip()
                val = m.group(4).strip()
                items[key] = val
        if items:
            result[title] = items
        else:
            result[title] = content
    return result

def convert_char_state(text: str) -> dict:
    """CHAR_state.md — key=value 格式"""
    result = {}
    for line in text.split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            result[k.strip()] = v.strip()
        elif line.strip() and not line.startswith("#"):
            # 可能是多行值的续行
            pass
    # 如果 key=value 解析失败，fallback 到 sections
    if not result:
        return sections_to_yaml(text)
    return result

def cmd_convert(world_dir: Path):
    """批量转换 .md → .yaml"""
    scene_dir = get_scene_dir(world_dir)

    # 定义转换映射：{md_path: yaml_path}
    md_to_yaml = {
        world_dir / "world_state.md":      world_dir / "world_state.yaml",
        world_dir / "conflicts.md":        world_dir / "conflicts.yaml",
    }
    # 角色状态
    for fp in world_dir.glob(f"{CHAR_STATE_PREFIX}*_state.md"):
        yaml_name = fp.stem + ".yaml"
        md_to_yaml[fp] = world_dir / yaml_name
    
    # 场景状态
    if scene_dir:
        ssmd = scene_dir / "scene_state.md"
        ssym = scene_dir / "scene_state.yaml"
        if ssmd.exists():
            md_to_yaml[ssmd] = ssym
    
    # 焦外
    ofmd = world_dir / "off_focus" / "pending_actions.md"
    ofym = world_dir / "off_focus" / "pending_actions.yaml"
    if ofmd.exists():
        md_to_yaml[ofmd] = ofym

    # 处理函数映射：(函数, 额外参数)
    handlers = {
        "world_state": (convert_world_state, False),
    }

    for src, dst in md_to_yaml.items():
        if not src.exists():
            continue
        text = src.read_text()
        name = src.stem

        if name == "conflicts":
            data = convert_table_format(text, name)
        elif "CHAR_" in name and name.endswith("_state"):
            data = convert_char_state(text)
        elif name in handlers:
            data = handlers[name][0](text)
        else:
            data = sections_to_yaml(text)

        # 备份 .md
        bak = src.with_suffix(".md.bak")
        if not bak.exists():
            shutil.copy2(src, bak)

        write_yaml(dst, data)
        print(f"[OK] {src.name} → {dst.name}  ({len(text)}b → {len(str(data))} keys)")

# ── READ ──────────────────────────────────────────────────────────
def cmd_read(world_dir: Path, files_filter: list[str] | None = None):
    scene_dir = get_scene_dir(world_dir)
    files = discover_files(world_dir, scene_dir)
    results = {}
    for key, fp in sorted(files.items()):
        if files_filter and key not in files_filter:
            continue
        try:
            with open(fp) as f:
                data = yaml.safe_load(f)
            results[key] = data if data else {}
        except Exception as e:
            print(f"[WARN] 读取 {key} 失败: {e}", file=sys.stderr)
            results[key] = {"_error": str(e)}
    if scene_dir:
        results["_scene_dir"] = scene_dir.name
    yaml.dump(results, sys.stdout, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)

# ── WRITE ─────────────────────────────────────────────────────────
def cmd_write(world_dir: Path, full_replace: bool = False):
    scene_dir = get_scene_dir(world_dir)
    existing = discover_files(world_dir, scene_dir)

    if full_replace:
        print("[WARN] --full 全量覆写：只保留 stdin 提供的键，未提及的键将被清除。确认无遗漏后再继续。", file=sys.stderr)

    delta = yaml.safe_load(sys.stdin)
    if delta is None:
        print("[ERR] stdin 为空", file=sys.stderr); sys.exit(1)

    written = []
    for key, new_data in delta.items():
        if key.startswith("_"):
            continue
        filepath, note = resolve_char_file(existing, key, world_dir)
        if filepath is None:
            print(f"[WARN] 未知 key: {key}, 跳过", file=sys.stderr)
            continue
        if note:
            print(note, file=sys.stderr)

        if filepath.exists() and not full_replace:
            try:
                with open(filepath) as f:
                    existing_data = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"[ERR] {key} 解析失败，拒绝写入（防止静默清空）: {e}", file=sys.stderr)
                continue
            merged = deep_merge(existing_data, new_data)
        else:
            merged = new_data

        write_yaml(filepath, merged)
        written.append(key)

    print(f"[OK] 已更新 {len(written)} 个文件: {', '.join(written)}")

# ── 语义不变量（audit）─────────────────────────────────────────
# 脚本校验线（与 SKILL.md §记忆维护/§场记 一致）
ANCHOR_LIMIT_TOTAL = 3000
ANCHOR_LIMIT_ENTRY = 100           # 写作线（audit 写前提醒·整理以 100 为准）
ANCHOR_LIMIT_ENTRY_VALIDATE = 150  # validate 宽松校验线（防强制压缩·写作线仍按 100）
REACTION_WINDOW = 5                # 反应轨迹窗口（最近 N 轮·APPEND 后脚本自动裁剪·LLM 零操作）

def trim_reaction_window(text: str, max_blocks: int = REACTION_WINDOW) -> str:
    """反应轨迹窗口裁剪：保留最近 max_blocks 个「第N轮(」块，删除更旧块。
    块前的非块行（如模板占位符）保留；块数不超窗口时原样返回。"""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^\s*第\s*\d+\s*轮\(", ln)]
    if len(starts) <= max_blocks:
        return text
    keep_from = starts[len(starts) - max_blocks]
    return "\n".join(lines[:starts[0]] + lines[keep_from:])

def _parse_world_time(text: str):
    """解析世界时间 '第N日 HH:MM' → (day:int, minutes:int)；无法解析返回 (None, None)。
    供重置点机械拦截（④b）与 reset-cycle 重建到期时刻使用。"""
    m = re.match(r"第\s*(\d+)\s*日\s*(\d{1,2}):(\d{2})", str(text).strip())
    if not m:
        return None, None
    try:
        day = int(m.group(1))
        minutes = int(m.group(2)) * 60 + int(m.group(3))
        return day, minutes
    except ValueError:
        return None, None


def parse_batch_entries(lines):
    """解析 ###FILE/###KEY/###APPEND/###DELETE/###META/###BEATSHEET 行到操作列表。
    返回 (ops, errors, meta_lines, beatsheet_lines)。ops 元素: (kind, file_key, key_path, content, append)
    kind ∈ {"write", "delete"}。空值 KEY 覆盖在此阶段即拒绝。
    ###META: 是批次级元数据（静默自查锚点）——不产生写入 ops，单独收集返回，不落盘。
    ###BEATSHEET: 是事件线动作元数据——不产生写入 ops，单独收集返回，不落盘；
    add/rewrite 后跟事件线 YAML 块（直到下一个 ### 行·write-raw 自动执行时作 stdin 传入）。
    beatsheet_lines 元素: (动作行, payload行列表|None)——add/rewrite 带 payload。"""
    ops = []
    errors = []
    meta_lines = []
    beatsheet_lines = []
    current_file = None
    current_key = None
    current_append = False
    current_content = []
    bs_payload = None

    def flush():
        nonlocal current_file, current_key, current_append, current_content
        if current_file and current_key:
            content = "\n".join(current_content).rstrip("\n")
            if not current_append and content == "":
                errors.append(f"空值覆盖已拒绝: {current_file}.{current_key}（###KEY: 值不能为空；追加请用 ###APPEND:，覆盖需带完整值）")
            else:
                ops.append(("write", current_file, current_key, content, current_append))
        current_key = None
        current_append = False
        current_content = []

    for line in lines:
        if line.startswith("###META:"):
            bs_payload = None
            meta_lines.append(line[8:].strip())
        elif line.startswith("###BEATSHEET:"):
            action = line[len("###BEATSHEET:"):].strip()
            first = action.split()[0] if action else ""
            if first in ("add", "rewrite"):
                bs_payload = []
                beatsheet_lines.append((action, bs_payload))
            else:
                bs_payload = None
                beatsheet_lines.append((action, None))
        elif line.startswith("###FILE:"):
            bs_payload = None
            flush()
            current_file = line[8:].strip()
        elif line.startswith("###KEY:"):
            bs_payload = None
            flush()
            current_key = line[7:].strip()
            current_append = False
        elif line.startswith("###APPEND:"):
            bs_payload = None
            flush()
            current_key = line[10:].strip()
            current_append = True
        elif line.startswith("###DELETE:"):
            bs_payload = None
            flush()
            rest = line[10:].strip()
            parts = rest.split(None, 1)
            if len(parts) == 2:
                ops.append(("delete", parts[0], parts[1], "", False))
            else:
                errors.append("###DELETE 格式: ###DELETE: <文件key> <YAML键路径>")
        elif bs_payload is not None:
            # ###BEATSHEET: add/rewrite 的事件线 YAML 块（收集到下一个 ### 行）
            bs_payload.append(line)
        elif current_file and current_key:
            # 内容行内嵌标记检测（防拼接 bug）：行内出现 ###FILE:/###KEY:/###APPEND: 但不在行首 = 上一字段内容被拼接
            for marker in ("###FILE:", "###KEY:", "###APPEND:", "###DELETE:", "###BEATSHEET:"):
                if marker in line and not line.lstrip().startswith(marker):
                    errors.append(
                        f"内容行内嵌标记 {marker.strip(':')}（行首无标记）：'{line[:60]}'——疑似上一字段内容与标记拼接（如缺少换行）。"
                        f"位置: {current_file}.{current_key}"
                    )
                    break
            current_content.append(line)
    flush()
    return ops, errors, meta_lines, beatsheet_lines


def check_batch(ops, world_dir, beatsheet_lines=None, meta_lines=None):
    """语义不变量检查（change set 草案→硬性违规/软性警告分类）。
    硬性违规（hard）：结构性/机械性错误——关键字段缺失、载体核验、轮次回归、落点错误。写入时**单字段顶回**。
    软性警告（soft）：内容质量类——记忆锚点超限等。写入时**不拦截**，仅记录（validate 汇总）。
    返回 (hard, soft)，元素为 (op_index, message)。"""
    hard = []
    soft = []
    scene_dir = get_scene_dir(world_dir)
    existing = discover_files(world_dir, scene_dir)

    # 预读当前值（用于对比型检查：轮次单调、锚点总量）
    current = {}
    for key, fp in existing.items():
        try:
            current[key] = yaml.safe_load(fp.read_text()) or {}
        except Exception:
            current[key] = {}

    # 重置豁免预扫描（2026-08-12 加入）：批次内登记了角色重置（world_state.重置记录.{角色} KEY 写入）→
    # 该角色按 loop_machinery §4 联动表清空/压缩 记忆锚点/反应轨迹（脚本档全清·漂移压缩·觉醒/变质保留）。
    # ⑬b 反应轨迹覆盖写检查对此豁免——重置清空是机制执行（联动表），不是丢失历史
    reset_chars = set()
    for _i, (_k, _fk, _kp, _c, _a) in enumerate(ops):
        if _k == "write" and _fk == "world_state" and _kp.startswith("重置记录."):
            _name = _kp[len("重置记录."):].strip()
            if _name:
                reset_chars.add(_name)

    # 批次整体必含项标记（完整推进轮·查询轮豁免）
    has_ct_op = False
    has_ws_time = False
    has_ws_round = False
    has_ws_summary = False
    has_scene_timeline = False
    has_beatsheet = bool(beatsheet_lines)

    for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
        if kind != "write":
            continue
        key_path = key_path_str.split(".")

        # 批次整体必含项标记
        if file_key == "conflicts" and key_path and key_path[0].startswith("CT-"):
            has_ct_op = True
        if file_key == "world_state" and key_path == ["时间", "具体时间"]:
            has_ws_time = True
        if file_key == "world_state" and key_path == ["轮次"]:
            has_ws_round = True
        if file_key == "world_state" and key_path == ["时间", "前情描述"]:
            has_ws_summary = True
        if file_key == "scene_state" and key_path == ["场景时间线"]:
            has_scene_timeline = True

        # conflicts.yaml 路径归一化：去掉多余的 `conflicts.` 根前缀
        if file_key == "conflicts" and key_path and key_path[0] == "conflicts":
            key_path = key_path[1:]

        # ① 角色反应四件套 + 代价非空（CT 推进的硬性格式）
        if (file_key == "conflicts" and len(key_path) >= 3
                and key_path[0].startswith("CT-") and key_path[1] == "当前节拍" and key_path[2] == "角色反应"):
            for token in ("驱动:", "情绪:", "强度:", "代价:"):
                if token not in content:
                    hard.append((idx, f"{file_key}.{key_path_str}: 角色反应缺「{token}」"))
                    break
            m = re.search(r"代价:\s*(\S+)", content)
            if m and not m.group(1).strip():
                hard.append((idx, f"{file_key}.{key_path_str}: 代价: 后为空（任一方无变化=本轮无冲突）"))
            # ①b 代价可核验性（硬性——D2① 代码化）：{...} 内无载体抽象词=不可核验=撤回级
            COST_BLACKLIST = ("幻想", "安全感", "预期", "确定性", "耐性", "错觉", "安宁", "掌控感", "主动权", "节奏", "局面", "从容")
            cost_m = re.search(r"代价:\s*(.+)", content)
            if cost_m:
                braces = re.findall(r"\{([^}]*)\}", cost_m.group(1))
                hit = [w for w in COST_BLACKLIST if any(w in b for b in braces)]
                if hit:
                    hard.append((idx, f"{file_key}.{key_path_str}: 代价含不可核验抽象词 {hit}——内部认知描述/无载体抽象词不算可核验变化（D2① 可核验枚举: 资源易主/载体状态变化/新增伤害/控制权易手/被迫选择/被迫承认/关系档位变化）"))

        # ② 被争夺资源必须写明载体/持有者（实体写持有者·抽象写载体）
        if (file_key == "conflicts" and key_path and key_path[0].startswith("CT-")
                and key_path[-1] == "被争夺资源"):
            if "当前载体=" not in content and "当前持有者=" not in content:
                hard.append((idx, f"{file_key}.{key_path_str}: 被争夺资源缺「当前载体=/当前持有者=」（抽象写载体·实体写持有者·写不出=不合格）"))

        # ③ 记忆锚点：单条 ≤100 / 写入后总量 ≤3000（软性警告·不拦截——内容质量类，validate 汇总）
        if file_key.startswith(CHAR_STATE_PREFIX) and key_path == ["记忆锚点"]:
            filepath, _ = resolve_char_file(existing, file_key, world_dir)
            if append:
                # 结构化列表：每条内容字段 ≤100；旧字符串：按 [ 切条
                if bool(re.match(r"^\s*-\s*(?:轮次|时间)[:：]", content)):
                    try:
                        items = yaml.safe_load(content) or []
                    except Exception:
                        items = []
                    entries = [str(it.get("内容", "")) for it in items if isinstance(it, dict) and it.get("内容")]
                else:
                    entries = re.split(r"\n\s*(?:·\s*)?(?=\[)", content)
                for ent in entries:
                    ent = ent.strip()
                    if len(ent) > ANCHOR_LIMIT_ENTRY:
                        soft.append((idx, f"{file_key}.记忆锚点: 新条目 {len(ent)} 字 > {ANCHOR_LIMIT_ENTRY} 上限（应压为事实一句+定性一句）"))
                total = len(content)
                if filepath and filepath.exists():
                    try:
                        old = (yaml.safe_load(filepath.read_text()) or {}).get("记忆锚点", "")
                        if isinstance(old, list):
                            total += sum(len(str(it.get("内容", ""))) for it in old if isinstance(it, dict))
                        elif isinstance(old, str) and old:
                            total += len(old)
                    except Exception:
                        pass
                if total > ANCHOR_LIMIT_TOTAL:
                    soft.append((idx, f"{file_key}.记忆锚点: 写入后总量 {total} 字 > {ANCHOR_LIMIT_TOTAL} 校验线——建议执行 §记忆淘汰 整理"))
            else:
                if len(content) > ANCHOR_LIMIT_TOTAL:
                    soft.append((idx, f"{file_key}.记忆锚点: 覆盖写入总量 {len(content)} 字 > {ANCHOR_LIMIT_TOTAL} 校验线"))

        # ④ 轮次单调（时间只增不减）
        if file_key == "world_state" and key_path == ["轮次"]:
            try:
                new_val = int(content.strip())
                old_val = int((current.get("world_state", {}).get("轮次") or 0))
                if new_val <= old_val:
                    hard.append((idx, f"world_state.轮次: {new_val} 必须 > 当前值 {old_val}（时间只增不减）"))
            except ValueError:
                hard.append((idx, f"world_state.轮次: 非整数 '{content.strip()}'"))

        # ④b 重置点机械拦截（循环世界·周期倒计时管道）：写 时间.具体时间 越过 重置类周期到期时刻
        #     且 重置记录 无覆盖新时间日期的记录 → 硬性顶回（防跨天漏重置/回退重放；执行=worldctl.py reset-cycle）
        if file_key == "world_state" and key_path == ["时间", "具体时间"]:
            try:
                ws_cur = current.get("world_state", {}) or {}
                new_day, new_min = _parse_world_time(content)
                if new_day is not None:
                    cds = ws_cur.get("外部倒计时") or {}
                    due_hit = None
                    if isinstance(cds, dict):
                        for cd in cds.values():
                            # 仅重置类周期倒计时（威胁含 周期/重置/循环 关键字）触发重置拦截；
                            # 非周期倒计时即使误带「到期时刻」字段也不参与（2026-08-13 修复）
                            if isinstance(cd, dict) and str(cd.get("到期时刻", "")).strip() and (
                                    "周期" in str(cd.get("威胁", "")) or "重置" in str(cd.get("威胁", "")) or "循环" in str(cd.get("威胁", ""))):
                                dd, dm = _parse_world_time(str(cd.get("到期时刻", "")))
                                if dd is not None and (dd, dm) <= (new_day, new_min):
                                    due_hit = cd.get("到期时刻", "")
                                    break
                    if due_hit:
                        reset_rec = ws_cur.get("重置记录") or {}
                        covered = False
                        day_label = f"第{new_day}日"
                        if isinstance(reset_rec, dict):
                            for rspec in reset_rec.values():
                                if isinstance(rspec, dict) and str(rspec.get("重置日期", "")) == day_label:
                                    covered = True
                                    break
                        if not covered:
                            hard.append((idx, f"world_state.时间.具体时间: 越过周期重置到期时刻 {due_hit}·但 重置记录 无覆盖 {day_label} 的记录——重置未执行（执行: worldctl.py {world_dir.name} reset-cycle 后重写）"))
            except Exception:
                pass


        # ⑤ scene_state 落点：必须有焦点场景目录（防止写错场景）
        if file_key == "scene_state" and scene_dir is None:
            hard.append((idx, "scene_state 落点错误: 无法定位当前焦点场景目录——先确认 world_state.焦点场景 后再写入"))

        # ⑥ 时间线事件写语义提示（软性·不拦截）：world_state.时间线.*.事件 默认 APPEND 追加；
        #    ###KEY 覆盖仅用于 validate 告警后的压缩维护（读旧值+压缩合并+补新）
        if (file_key == "world_state" and len(key_path) >= 3
                and key_path[0] == "时间线" and key_path[-1] == "事件" and not append):
            soft.append((idx, f"{file_key}.{key_path_str}: 时间线事件默认 ###APPEND 追加；###KEY 覆盖仅在 validate 告警后的压缩维护时使用（读旧值+压缩合并+补新）"))

        # ⑦ world_state 键表外字段（软性警告——无语义定义的漂移字段）
        if file_key == "world_state" and key_path:
            WS_TOP_KEYS = {"焦点场景", "轮次", "时间", "地点", "外部倒计时", "全局标记", "时间线", "重置记录", "叙事约定"}
            WS_TIME_KEYS = {"基准时间", "具体时间", "时间流速比", "前情描述"}
            WS_LOC_KEYS = {"当前区域", "已探索区域"}
            if key_path[0] not in WS_TOP_KEYS:
                soft.append((idx, f"world_state.{key_path_str}: 未知顶层键（键表: 焦点场景/轮次/时间/地点/外部倒计时/全局标记/时间线/重置记录/叙事约定）"))
            elif len(key_path) >= 2 and key_path[0] == "时间" and key_path[1] not in WS_TIME_KEYS:
                soft.append((idx, f"world_state.{key_path_str}: 未知时间子键（键表: 基准时间/具体时间/时间流速比/前情描述）"))
            elif len(key_path) >= 2 and key_path[0] == "地点" and key_path[1] not in WS_LOC_KEYS:
                soft.append((idx, f"world_state.{key_path_str}: 未知地点子键（键表: 当前区域/已探索区域）"))

        # ⑧ 自主性枚举 + 升级路径（硬性：非法枚举；软性：非标准路径——唯一入口=§变质判定/§记忆提炼管道B）
        if file_key.startswith(CHAR_STATE_PREFIX) and key_path == ["自主性"]:
            AUTO_LEVELS = {"脚本", "漂移", "觉醒", "变质"}
            new_auto = content.strip()
            if new_auto not in AUTO_LEVELS:
                hard.append((idx, f"{file_key}.自主性: 非法值 '{new_auto}'（枚举: 脚本/漂移/觉醒/变质）"))
            else:
                old_data = current.get(file_key, {})
                old_auto = old_data.get("自主性", "") if isinstance(old_data, dict) else ""
                if old_auto and old_auto != new_auto:
                    valid = (old_auto in ("脚本", "漂移") and new_auto == "觉醒") or (old_auto == "觉醒" and new_auto == "变质")
                    if not valid:
                        soft.append((idx, f"{file_key}.自主性: 升级路径 {old_auto}→{new_auto} 非标准（标准入口: §变质判定 脚本/漂移→觉醒→变质；§记忆提炼管道B 弱入口）——禁止无规则改动"))

        # ⑨ 角色反应前缀角色名必须有档案（硬性——档案未加载=禁止推导该角色反应）
        if (file_key == "conflicts" and len(key_path) >= 3
                and key_path[0].startswith("CT-") and key_path[1] == "当前节拍" and key_path[2] == "角色反应"):
            m = re.match(r"^(?:角色反应:\s*)?([^:：|]+)[:：]", content)
            if m:
                char_name = m.group(1).strip()
                md_fp = world_dir / f"CHAR_{char_name}.md"
                state_fp = world_dir / f"CHAR_{char_name}_state.yaml"
                if not md_fp.exists() and not state_fp.exists():
                    # 简称→全名映射：扫现有 CHAR_ 档案，找以该简称为前缀/后缀/包含该简称的文件
                    resolved = None
                    try:
                        for fp in world_dir.glob("CHAR_*.md"):
                            full = fp.stem[len("CHAR_"):]
                            if char_name in full or full in char_name or full.replace(" ", "") == char_name.replace(" ", ""):
                                resolved = full
                                break
                    except Exception:
                        pass
                    if resolved:
                        soft.append((idx, f"{file_key}.{key_path_str}: 反应角色 '{char_name}' 是简称，档案全名为 '{resolved}'——请用全名（audit 硬性检查按全名匹配）"))
                    else:
                        hard.append((idx, f"{file_key}.{key_path_str}: 反应角色 '{char_name}' 无档案（缺 CHAR_{char_name}.md / CHAR_{char_name}_state.yaml——档案缺失=禁止推导该角色反应；若为简称请用档案全名）"))

        # ⑬ FILE 归属校验（硬性——防 FILE 标记错位导致字段写入错误文件）
        if key_path:
            if file_key == "conflicts":
                if not key_path[0].startswith("CT-"):
                    hard.append((idx, f"{file_key}.{key_path_str}: conflicts 顶层键必须是 CT-XX（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))
            elif file_key.startswith(CHAR_STATE_PREFIX):
                CHAR_STATE_KEYS = {"自主性", "位置", "已知地点", "核心状态", "情绪", "压力水平", "防御有效性", "防御形态", "崩溃表现", "偏离登记", "人际动态", "决策状态", "信念演化", "记忆锚点", "反应轨迹", "名字"}
                if key_path[0] not in CHAR_STATE_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: CHAR_state 顶层键必须在键表内（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))
            elif file_key == "scene_state":
                SCENE_STATE_KEYS = {"核心状态", "场景时间线", "物理锚点", "道具", "关键场景信息", "出场角色摘要"}
                if key_path[0] not in SCENE_STATE_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: scene_state 顶层键必须在键表内（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))

        # ⑬b 反应轨迹覆盖写检测（硬性——防覆盖写丢失历史：覆盖写必须保留旧值首末轮次标记·窗口由脚本自动裁剪·禁止手动删块）
        # 重置豁免：该角色已登记重置（world_state.重置记录.{角色}）→ 按 loop_machinery §4 联动表清空/压缩重建，不拦
        if (file_key.startswith(CHAR_STATE_PREFIX) and key_path == ["反应轨迹"] and not append):
            _fp_r, _ = resolve_char_file(existing, file_key, world_dir)
            if _fp_r is not None:
                _stem = _fp_r.stem[len(CHAR_STATE_PREFIX):]
                if _stem.endswith("_state"):
                    _stem = _stem[:-len("_state")]
                if _stem in reset_chars:
                    continue
            old_val = (current.get(file_key, {}) or {}).get("反应轨迹", "")
            if isinstance(old_val, str) and old_val.strip():
                old_marks = re.findall(r"第\s*\d+\s*轮\(", old_val)
                if old_marks:
                    first, last = old_marks[0], old_marks[-1]
                    if first not in content or last not in content:
                        hard.append((idx, f"{file_key}.反应轨迹: 覆盖写丢失历史——新内容必须保留旧值首末轮次标记（{first}…/{last}…）·窗口由脚本自动裁剪·禁止手动删块"))

    # ⑩⑪⑫ 批次整体必含项（软性·完整推进轮——查询轮豁免；批次为空不检查）
    if ops:
        if not has_ct_op:
            soft.append((-1, "完整推进轮 change set 应含 ≥1 条 CT 推进/注册（conflicts.CT-XX）——查询轮豁免"))
        if not has_ws_time:
            soft.append((-1, "完整推进轮 change set 应含 world_state.时间.具体时间 推进（查询轮豁免）"))
        if not has_ws_round:
            soft.append((-1, "完整推进轮 change set 应含 world_state.轮次 +1（查询轮豁免）"))
        if not has_ws_summary:
            soft.append((-1, "完整推进轮 change set 应含 world_state.前情描述（≤100字状态短语·查询轮豁免）"))
        if not has_scene_timeline:
            soft.append((-1, "完整推进轮 change set 应含 scene_state.场景时间线 追加（查询轮豁免）"))

    # ⑬c 节拍表事件线动作（软性——完整推进轮必含；gate --check 将其升级为硬性拦截）
    if has_ct_op and has_ws_time and has_ws_round and has_ws_summary and has_scene_timeline and not has_beatsheet:
        soft.append((-1, "完整推进轮 change set 应含 ###BEATSHEET: 事件线动作（add/stay N/advance N 拍名/rewrite N/clear N）——查询轮/维护轮豁免"))

    # ⑭ 跨叙事提醒（软性——CROSS_NARRATIVES.md 存在时，完整推进轮应核对深匹配）
    if (world_dir / "CROSS_NARRATIVES.md").exists() and has_ct_op:
        soft.append((-1, "CROSS_NARRATIVES.md 存在——完整推进轮应核对跨叙事深匹配（SKILL ④: 浅匹配=登记不操作；深匹配=注入可写行为偏移；激活=注册新 CT；每轮最多激活一条·同线间隔≥3轮）"))
    # ⑮ 行为偏移落地提醒（软性——change set 含「行为偏移」标记 → 叙事阶段必须落地）
    if any("行为偏移" in content for _, _, _, content, _ in ops):
        soft.append((-1, "change set 含「行为偏移」标记——叙事阶段必须如实落地该偏移（W3 核验·可观察行为·不解释来源）"))

    # ⑯ 记忆留痕逐角色对照（硬性·批次级）：###META 记忆✓ 后跟逐角色同类计数留痕
    # （格式 `记忆✓ {角色}:{计数}·{已触发|未达}`·空格分隔·角色名以下划线代空格）
    # 批次写了 CHAR_state 的角色必须出现在留痕中——防「扫旧同类计数只做主线角色」的注意力遗漏
    # （Angela 案例：轮次 16-19 管道B 计数只对 Guest 发生·贴线角色同类链从未进入计数视野）；
    # 留痕标「已触发」→ 批次必须含该角色信念演化 APPEND（认知决策与落盘一致性）。
    char_roles = set()
    for _i, (_k, _fk, _kp, _c, _a) in enumerate(ops):
        if _k != "write" or not _fk.startswith(CHAR_STATE_PREFIX) or not _fk.endswith("_state"):
            continue
        _fp, _ = resolve_char_file(existing, _fk, world_dir)
        if _fp is not None:
            char_roles.add(_fp.stem[len(CHAR_STATE_PREFIX):-len("_state")])
    if char_roles:
        meta_text = meta_lines[0] if meta_lines else ""
        traced = {}  # 角色 → 判定（已触发/未达）
        m = re.search(r"记忆✓\s*(.*)$", meta_text)
        if m:
            for tok in m.group(1).split():
                mm = re.match(r"^(.+?):(\d+)(?:·(已触发|未达))?$", tok)
                if mm:
                    traced[mm.group(1).replace("_", " ")] = mm.group(3) or "未达"
        for role in sorted(char_roles):
            if role not in traced:
                hard.append((-1, f"###META 记忆✓ 留痕缺角色: {role}（逐角色同类计数必列·格式 `记忆✓ {{角色}}:{{计数}}·{{已触发|未达}}`·角色名以下划线代空格·查询轮豁免）"))
            elif traced[role] == "已触发":
                has_belief = any(
                    _k == "write" and _fk.startswith(CHAR_STATE_PREFIX) and _fk.endswith("_state")
                    and _kp == "信念演化"
                    and resolve_char_file(existing, _fk, world_dir)[0] is not None
                    and resolve_char_file(existing, _fk, world_dir)[0].stem[len(CHAR_STATE_PREFIX):-len("_state")] == role
                    for _k, _fk, _kp, _c, _a in ops
                )
                if not has_belief:
                    hard.append((-1, f"###META 记忆✓ 留痕标 {role}:已触发·但批次缺该角色 ###APPEND: 信念演化"))

    return hard, soft


def cmd_audit(world_dir):
    """audit: 校验 stdin 的 change set 草案（###FILE/###KEY/###APPEND 格式），不落盘。
    硬性违规 → 列出全部并 exit 1（草案不合格）；仅软性警告 → 打印警告，exit 0（可写入）。"""
    raw_stdin = sys.stdin.buffer.read().decode("utf-8")
    ops, parse_errors, meta_lines, beatsheet_lines = parse_batch_entries(raw_stdin.split("\n"))
    hard, soft = check_batch(ops, world_dir, beatsheet_lines, meta_lines)
    if beatsheet_lines:
        print(f"[AUDIT] ###BEATSHEET 回显: {beatsheet_lines[0]}", file=sys.stderr)
    if meta_lines:
        print(f"[AUDIT] ###META 回显: {meta_lines[0]}", file=sys.stderr)
        if "记忆" not in meta_lines[0]:
            soft.append((0, "###META 静默自查锚点缺少 记忆✓ 槽（记忆✓=逐角色同类计数留痕·每出场角色必列·见 SKILL.md §记忆维护）"))
    else:
        soft.append((0, "未检测到 ###META: 静默自查锚点——完整推进轮批次首行必写：###META: 压力扫描 人际✓/增殖✓/轨道✓/跨叙事✓/记忆✓（查询轮/维护轮豁免）"))
    if hard or parse_errors:
        print(f"[AUDIT] {len(hard) + len(parse_errors)} 个硬性违规——change set 不合格:", file=sys.stderr)
        for e in parse_errors:
            print(f"  - {e}", file=sys.stderr)
        for _, v in hard:
            print(f"  - {v}", file=sys.stderr)
        sys.exit(1)
    if soft:
        print(f"[AUDIT] 硬性检查通过（{len(soft)} 个软性警告·不拦截·validate 汇总）:", file=sys.stderr)
        for _, v in soft:
            print(f"  - {v}", file=sys.stderr)
    print("[AUDIT] OK——change set 通过硬性检查，可写入")


def quick_validate_summary(world_dir):
    """写入后自动触发：轻量关键项检查，只输出警告数摘要（详细列表见 validate 命令）。
    覆盖 SKILL.md 脚本校验线中最高价值项：记忆锚点总量/单条、焦点场景一致性、CT 键格式。"""
    warnings = []
    try:
        scene_dir = get_scene_dir(world_dir)
        # 记忆锚点（脚本校验线）
        for cfp in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
            try:
                cdata = yaml.safe_load(cfp.read_text()) or {}
            except Exception:
                continue
            mem = cdata.get("记忆锚点", "")
            if isinstance(mem, list):
                total = sum(len(str(it.get("内容", ""))) for it in mem if isinstance(it, dict))
                if total > ANCHOR_LIMIT_TOTAL:
                    warnings.append(f"{cfp.name}: 记忆锚点 {total} 字 > {ANCHOR_LIMIT_TOTAL} 校验线——需按 §记忆淘汰 整理")
                over = [it for it in mem if isinstance(it, dict) and len(str(it.get("内容", ""))) > ANCHOR_LIMIT_ENTRY_VALIDATE]
                if over:
                    warnings.append(f"{cfp.name}: {len(over)} 条记忆锚点超单条 {ANCHOR_LIMIT_ENTRY_VALIDATE} 字上限（宽松校验线·写作线 100）")
            elif isinstance(mem, str) and mem.strip():
                if len(mem) > ANCHOR_LIMIT_TOTAL:
                    warnings.append(f"{cfp.name}: 记忆锚点 {len(mem)} 字 > {ANCHOR_LIMIT_TOTAL} 校验线——需按 §记忆淘汰 整理")
                entries = re.split(r"\n\s*(?:·\s*)?(?=\[)", mem)
                over = [e for e in entries if len(e.strip()) > ANCHOR_LIMIT_ENTRY_VALIDATE]
                if over:
                    warnings.append(f"{cfp.name}: {len(over)} 条记忆锚点超单条 {ANCHOR_LIMIT_ENTRY_VALIDATE} 字上限（宽松校验线·写作线 100）")
        # 焦点场景 ↔ 场景目录
        ws_fp = world_dir / "world_state.yaml"
        if ws_fp.exists():
            ws = yaml.safe_load(ws_fp.read_text()) or {}
            focus = str(ws.get("焦点场景") or "").strip()
            if focus and scene_dir and not scene_dir.name.startswith(focus):
                warnings.append(f"焦点场景 '{focus}' 与当前场景目录 '{scene_dir.name}' 不一致")
        # CT 键格式
        c_fp = world_dir / "conflicts.yaml"
        if c_fp.exists():
            cdata = yaml.safe_load(c_fp.read_text()) or {}
            for k in cdata:
                if not re.match(r"^CT-\d{2}$", str(k)) and str(k) != BEAT_TOP_KEY:
                    warnings.append(f"conflicts.yaml: 顶层键 '{k}' 不符合 CT-XX 格式")
    except Exception:
        pass
    if warnings:
        print(f"[VALIDATE] 写入完成，{len(warnings)} 个内容警告待处理（详细列表运行 validate 查看）", file=sys.stderr)
        for w in warnings[:5]:
            print(f"  - {w}", file=sys.stderr)
        if len(warnings) > 5:
            print(f"  …等 {len(warnings) - 5} 条", file=sys.stderr)


def cmd_write_raw(world_dir: Path, extra: list[str], batch: bool = False, append_mode: bool = False, dry_run: bool = False):
    """
    write-raw: 直接写原始文本到指定字段，绕过 YAML 输入解析。
    append-raw: 追加到指定字段末尾（累积字段专用：记忆锚点/信念演化/场景时间线/关键场景信息）。

    单字段模式: worldctl.py <世界> write-raw <文件key> <YAML键路径> [内容]
                 worldctl.py <世界> append-raw <文件key> <YAML键路径> [内容]
    批量模式:   worldctl.py <世界> write-raw --batch / append-raw --batch
               stdin 格式:
                 ###FILE: <文件key>
                 ###KEY: <YAML键路径>      ← 覆盖写
                 <内容行...>
                 ###APPEND: <YAML键路径>   ← 追加写（字段不存在时等同新建）
                 <内容行...>
                 ###FILE: <另一个文件key>
                 ...

    文件key: scene_state, CHAR_Maeve Millay_state 等
    YAML键路径: 点分隔路径，如 "核心状态" 或 "子键.更深"
    内容: 单字段模式可选 CLI 参数，否则从 stdin 读取

    注意: write-raw --batch 非幂等——###APPEND: 重复执行会把累积字段（记忆锚点/场景时间线等）重复追加。
    同一批次只执行一次；执行后的确认用 read / validate / 重跑 --dry-run（只读），禁止重放 write 命令做验证。
    脚本内置重复追加检测：APPEND 内容已存在于字段中 → 自动跳过并打印 [SKIP]。
    """

    def write_one(file_key: str, key_path_str: str, content: str, append: bool = False):
        """写单个字段到指定文件。append=True 时追加到末尾。成功返回 True，失败返回 False。"""
        scene_dir = get_scene_dir(world_dir)
        existing = discover_files(world_dir, scene_dir)
        key_path = key_path_str.split(".")
        # conflicts.yaml 路径归一化：去掉多余的 `conflicts.` 根前缀
        if file_key == "conflicts" and key_path and key_path[0] == "conflicts":
            key_path = key_path[1:]

        filepath, note = resolve_char_file(existing, file_key, world_dir)
        if filepath is None:
            print(f"[ERR] 未知文件 key: {file_key}", file=sys.stderr)
            return False
        if note:
            print(note, file=sys.stderr)

        if filepath.exists():
            try:
                data = yaml.safe_load(filepath.read_text()) or {}
            except Exception as e:
                print(f"[ERR] {file_key} 解析失败，拒绝写入（防止静默清空）: {e}", file=sys.stderr)
                return False
        else:
            data = {}

        target = data
        for k in key_path[:-1]:
            if k not in target or not isinstance(target[k], dict):
                target[k] = {}
            target = target[k]
        leaf = key_path[-1]
        # 结构化累积字段（记忆锚点/信念演化/偏离登记/已知地点/伏笔）：append 时追加为 yaml 列表元素
        # 判定：记忆锚点/信念演化/偏离登记/伏笔以「- 轮次:/时间:/线索:」开头；已知地点以「- 」开头（元素=地点名字符串）
        STRUCTURED_APPEND_FIELDS = {"记忆锚点", "信念演化", "偏离登记", "已知地点", "伏笔"}
        is_structured_field = ((file_key.startswith(CHAR_STATE_PREFIX) or file_key == "foreshadow")
                               and leaf in STRUCTURED_APPEND_FIELDS)
        if leaf == "已知地点":
            is_list_item_content = bool(re.match(r"^\s*-\s+", content))
        else:
            is_list_item_content = bool(re.match(r"^\s*-\s*(?:轮次|时间|线索)[:：]", content))
        if append and is_structured_field and is_list_item_content:
            # 解析 change set 中给出的列表元素（可能多条）——直接用 yaml 解析（与 write_yaml 同款）
            try:
                new_items = yaml.safe_load(content)
            except Exception:
                print(f"[ERR] {file_key}.{'.'.join(key_path)} 结构化追加内容不是合法 YAML 列表，拒绝写入", file=sys.stderr)
                return False
            if not isinstance(new_items, list):
                print(f"[ERR] {file_key}.{'.'.join(key_path)} 结构化追加内容必须是 YAML 列表（- 轮次: ... / - 地点名）", file=sys.stderr)
                return False
            if leaf == "已知地点":
                new_items = [str(it).strip() for it in new_items if isinstance(it, str) and it.strip()]
            else:
                new_items = [it for it in new_items if isinstance(it, dict)]

            existing_val = target.get(leaf, [])
            if not isinstance(existing_val, list):
                # 旧字符串格式 → 转换为列表（每条旧锚点保留为「内容」元素）
                existing_val = [{"轮次": "", "内容": ent.strip()}
                                for ent in re.split(r"\n\s*(?:·\s*)?(?=\[)", str(existing_val))
                                if ent.strip()]
            # 重复追加检测：已知地点按元素相等；伏笔按 线索 相等；其余按 轮次+内容 判断
            for item in new_items:
                dup = False
                for e in existing_val:
                    if leaf == "已知地点":
                        if str(e) == str(item):
                            dup = True
                            break
                    elif leaf == "伏笔":
                        if str(e.get("线索", "")) == str(item.get("线索", "")):
                            dup = True
                            break
                    elif (str(e.get("轮次", "")) == str(item.get("轮次", ""))
                            and str(e.get("内容", "")) == str(item.get("内容", ""))):
                        dup = True
                        break
                if not dup:
                    existing_val.append(item)
                else:
                    print(f"[SKIP] {file_key}.{'.'.join(key_path)} 重复追加已跳过（{'地点已存在' if leaf == '已知地点' else ('线索已存在' if leaf == '伏笔' else '轮次+内容已存在')}）", file=sys.stderr)
            target[leaf] = existing_val
            write_yaml(filepath, data)
            print(f"[OK] {file_key}.{'.'.join(key_path)} 已追加 {len(new_items)} 条结构化元素", file=sys.stderr)
            return True
        if append and leaf in target and isinstance(target[leaf], str) and target[leaf]:
            existing_val = target[leaf]
            # 重复追加检测（硬防护·防同一批次重放/同一内容重复追加）：
            # 批次重放时 content 完全一致，必然作为子串存在于字段值中 → 跳过
            if content.strip() and content.strip() in existing_val:
                print(f"[SKIP] {file_key}.{'.'.join(key_path)} 重复追加已跳过（内容已存在——同一批次只执行一次，禁止重放 write 命令验证）", file=sys.stderr)
                return True
            target[leaf] = existing_val.rstrip("\n") + "\n" + content
            # 反应轨迹窗口（🪟）：APPEND 后超 5 轮自动删最旧块——LLM 零操作
            if file_key.startswith(CHAR_STATE_PREFIX) and leaf == "反应轨迹":
                trimmed = trim_reaction_window(target[leaf])
                if trimmed != target[leaf]:
                    print(f"[TRIM] {file_key}.反应轨迹 已自动裁剪至最近 {REACTION_WINDOW} 轮（窗口滚动·删最旧块）", file=sys.stderr)
                    target[leaf] = trimmed
        elif not append and is_structured_field and (is_list_item_content or content.strip() in ("[]", "{}")):
            # KEY 覆盖结构化列表字段：content 为 yaml 列表文本（- item / []）→ 解析为列表全量替换
            # （字段级替换意图与 APPEND 增量区分；非列表文本仍按原始文本覆盖）
            try:
                new_items = yaml.safe_load(content)
            except Exception:
                print(f"[ERR] {file_key}.{'.'.join(key_path)} 结构化覆盖内容不是合法 YAML 列表，拒绝写入", file=sys.stderr)
                return False
            if not isinstance(new_items, list):
                print(f"[ERR] {file_key}.{'.'.join(key_path)} 结构化覆盖内容必须是 YAML 列表（- 轮次: ... / - 地点名 / []）", file=sys.stderr)
                return False
            if leaf == "已知地点":
                new_items = [str(it).strip() for it in new_items if isinstance(it, str) and it.strip()]
            else:
                new_items = [it for it in new_items if isinstance(it, dict)]
            target[leaf] = new_items
            write_yaml(filepath, data)
            print(f"[OK] {file_key}.{'.'.join(key_path)} 已覆盖（结构化列表·{len(new_items)} 条）", file=sys.stderr)
            return True
        else:
            target[leaf] = content

        write_yaml(filepath, data)
        op = "已追加" if append else "已写入"
        print(f"[OK] {file_key}.{'.'.join(key_path)} {op} ({len(content)}b)")
        return True

    # ── 批量模式 ──
    if batch:
        import io
        raw_stdin = sys.stdin.buffer.read().decode("utf-8")
        lines = raw_stdin.split("\n")

        # 解析 + 语义不变量检查（audit）——硬性违规 → 单字段顶回（不整批拒绝）
        ops, parse_errors, meta_lines, beatsheet_lines = parse_batch_entries(lines)
        hard, soft = check_batch(ops, world_dir, beatsheet_lines, meta_lines)
        blocked = {idx for idx, _ in hard}
        if beatsheet_lines:
            print(f"[AUDIT] ###BEATSHEET 回显: {beatsheet_lines[0][0]}", file=sys.stderr)
        if meta_lines:
            print(f"[AUDIT] ###META 回显: {meta_lines[0]}", file=sys.stderr)
            if "记忆" not in meta_lines[0]:
                print("[AUDIT] 软性警告: ###META 静默自查锚点缺少 记忆✓ 槽（记忆✓=逐角色同类计数留痕·每出场角色必列·见 SKILL.md §记忆维护）", file=sys.stderr)
        else:
            print("[AUDIT] 软性警告: 未检测到 ###META: 静默自查锚点——完整推进轮批次首行必写（查询轮/维护轮豁免）", file=sys.stderr)
        for e in parse_errors:
            print(f"[AUDIT] 解析失败（该条未写入）: {e}", file=sys.stderr)
        for idx, v in hard:
            print(f"[AUDIT] 硬性违规——拒绝该字段写入: {v}", file=sys.stderr)
        # 软性警告不在此逐条打印（避免噪音）——由 quick_validate_summary 汇总（validate 明细）

        # ── --dry-run 预演：对比磁盘差异，不落盘 ──
        if dry_run:
            scene_dir = get_scene_dir(world_dir)
            existing = discover_files(world_dir, scene_dir)
            unknown_keys = 0
            print(f"[DRY-RUN] 预演 {len(ops)} 条操作，{len(blocked)} 条被顶回（不落盘）")
            for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
                if idx in blocked:
                    print(f"  [顶回] {file_key}.{key_path_str}")
                    continue
                if kind == "delete":
                    print(f"  [删除] {file_key}.{key_path_str}")
                    continue
                fp, _ = resolve_char_file(existing, file_key, world_dir)
                if fp is None:
                    unknown_keys += 1
                    print(f"  [ERR] 未知文件 key: {file_key}（dry-run 拦截·实写将拒绝该字段）")
                    continue
                old_val = None
                if fp.exists():
                    try:
                        d = yaml.safe_load(fp.read_text()) or {}
                        tgt = d
                        for k in key_path_str.split("."):
                            if k in tgt and isinstance(tgt[k], dict):
                                tgt = tgt[k]
                            else:
                                tgt = None
                                break
                        old_val = tgt if tgt is not None else None
                    except Exception:
                        pass
                if old_val is None:
                    print(f"  [新增] {file_key}.{key_path_str}")
                elif str(old_val) == content:
                    print(f"  [无变化] {file_key}.{key_path_str}")
                else:
                    action = "追加" if append else "覆盖"
                    print(f"  [{action}] {file_key}.{key_path_str}（旧 {len(str(old_val))}b → 新 {len(content)}b）")
            if unknown_keys:
                print(f"[DRY-RUN] ⚠ {unknown_keys} 条未知文件 key——实写将被拒绝（请检查 ###FILE: 的 key 是否与 discover_files 注册一致）")
            print("[DRY-RUN] ⚠ 非幂等：同一批次只执行一次；执行后确认用 read/validate，禁止重放 write 命令验证")
            return

        # ── ###BEATSHEET 自动执行（节拍表落盘·失败拦批——LLM 不手动调用）──
        if beatsheet_lines:
            for action, payload in beatsheet_lines:
                parts = action.split()
                if not parts or parts[0] not in ("add", "stay", "advance", "rewrite", "clear"):
                    print(f"[FAIL] ###BEATSHEET 动作非法: {action!r}（合法: add / stay N / advance N 拍名 / rewrite N / clear N）——批次拦截", file=sys.stderr)
                    sys.exit(1)
                stdin_text = "\n".join(payload) if payload is not None else None
                try:
                    cmd_beatsheet(world_dir, parts, stdin_text=stdin_text)
                except SystemExit as e:
                    print(f"[FAIL] ###BEATSHEET 执行失败: {action}（exit {e.code}）——节拍表未更新·批次拦截·撤回阶段1 修正后重提", file=sys.stderr)
                    sys.exit(1)
            print("[OK] ###BEATSHEET 已自动执行（节拍表落盘）", file=sys.stderr)

        # 逐条写入：顶回违规字段，其余照写
        written_count = 0
        for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
            if idx in blocked:
                continue
            if kind == "delete":
                cmd_delete(world_dir, [file_key, key_path_str])
                continue
            if write_one(file_key, key_path_str, content, append=append):
                written_count += 1
        op = "批量追加" if append_mode else "批量写入"
        if blocked:
            print(f"[OK] {op}完成：{written_count} 个字段写入，{len(blocked)} 个字段被顶回（硬性违规）")
        else:
            print(f"[OK] {op}完成，共 {written_count} 个字段")
        quick_validate_summary(world_dir)  # 写入后自动触发轻量校验（每轮必跑）
        return

    # ── 单字段模式（原有逻辑） ──
    scene_dir = get_scene_dir(world_dir)
    existing = discover_files(world_dir, scene_dir)

    if len(extra) < 2:
        print(f"[ERR] 用法: worldctl.py <世界> {'append-raw' if append_mode else 'write-raw'} <文件key> <YAML键路径> [内容]", file=sys.stderr)
        sys.exit(1)

    file_key = extra[0]
    key_path_str = extra[1]

    # 内容：CLI 参数优先，否则 stdin
    if len(extra) >= 3:
        content = extra[2]
    else:
        content = sys.stdin.read()

    if not append_mode and content == "":
        print(f"[ERR] 空值覆盖已拒绝: {file_key}.{key_path_str}（write-raw 值不能为空；追加请用 append-raw）", file=sys.stderr)
        sys.exit(1)

    write_one(file_key, key_path_str, content, append=append_mode)

# ── DELETE ───────────────────────────────────────────────────────
def cmd_delete(world_dir: Path, extra: list[str]):
    """
    delete: 删除指定键路径。
    用法: worldctl.py <世界> delete <文件key> <YAML键路径>
    示例: worldctl.py westworld delete conflicts CT-05        ← 删除整条 CT
          worldctl.py westworld delete pending_actions 已完成.PA-002
    """
    if len(extra) < 2:
        print("[ERR] 用法: worldctl.py <世界> delete <文件key> <YAML键路径>", file=sys.stderr)
        sys.exit(1)
    file_key = extra[0]
    key_path_str = extra[1]

    scene_dir = get_scene_dir(world_dir)
    existing = discover_files(world_dir, scene_dir)
    filepath, note = resolve_char_file(existing, file_key, world_dir)
    if filepath is None:
        print(f"[ERR] 未知文件 key: {file_key}", file=sys.stderr)
        return
    if note:
        print(note, file=sys.stderr)

    if not filepath.exists():
        print(f"[WARN] {file_key} 文件不存在，无需删除", file=sys.stderr)
        return

    try:
        data = yaml.safe_load(filepath.read_text()) or {}
    except Exception as e:
        print(f"[ERR] {file_key} 解析失败: {e}", file=sys.stderr)
        return

    key_path = key_path_str.split(".")
    # conflicts.yaml 路径归一化：去掉多余的 `conflicts.` 根前缀
    if file_key == "conflicts" and key_path and key_path[0] == "conflicts":
        key_path = key_path[1:]

    target = data
    for k in key_path[:-1]:
        if not isinstance(target, dict) or k not in target or not isinstance(target[k], dict):
            print(f"[ERR] 路径不存在: {key_path_str}", file=sys.stderr)
            return
        target = target[k]

    last = key_path[-1]
    if not isinstance(target, dict) or last not in target:
        print(f"[WARN] 键不存在: {key_path_str}，无需删除", file=sys.stderr)
        return
    del target[last]
    write_yaml(filepath, data)
    print(f"[OK] 已删除 {file_key}.{key_path_str}")

# ── VALIDATE ──────────────────────────────────────────────────────


def cmd_grep(world_dir: Path, keyword: str):
    """在所有状态文件中搜索关键词，输出注册原文——核对元素注册数据的标准工具（D11/W4 前置·防凭印象改写元素形态）。"""
    if not keyword:
        print("用法: worldctl.py <世界> grep <关键词>")
        return
    scene_dir = get_scene_dir(world_dir)
    files = discover_files(world_dir, scene_dir)
    # 额外扫描所有场景的 scene_state.yaml（不只焦点场景——核对历史注册原文必需，防止凭印象改写已有元素形态）
    scenes_dir = world_dir / "scenes"
    if scenes_dir.is_dir():
        for d in sorted(scenes_dir.iterdir()):
            if d.is_dir() and (d / "scene_state.yaml").exists():
                files[f"scenes/{d.name}/scene_state.yaml"] = d / "scene_state.yaml"
    hits = []
    for key, fp in sorted(files.items()):
        if not fp.exists():
            continue
        try:
            text = fp.read_text(errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if keyword in line:
                hits.append(f"{key}:{i}: {line.strip()}")
    if hits:
        print(f"[GREP] '{keyword}' 共 {len(hits)} 处（文件key:行号: 内容）：")
        for h in hits:
            print(f"  {h}")
        print("  → 使用已有元素前先核对注册原文（形态/位置/状态），禁止凭印象改写元素。")
    else:
        print(f"[GREP] '{keyword}' 无匹配——该元素未在任何 scene_state/状态文件注册，使用即幻觉。")



def cmd_scan(world_dir: Path, extra: list[str], live_only: bool = False):
    """scan: 全仓残留检查（标准入口，替代手拼 grep --include——BusyBox grep 不支持 --include）。
    递归扫描 worlds/<世界>/ 下所有 .md/.yaml/.yml 文件（排除历史轮转 narrative.*.md 与 archive）。
    退出码: 0=无匹配（干净）· 1=有匹配（残留存在）· 2=用法错误。
    用途: 修改数据/规则后检查旧字段是否残留——失败就是失败，不靠 || echo 兜底。
    """
    if not extra:
        print("用法: worldctl.py <世界> scan <关键词> [--live]  （--live=仅当前文件，跳过历史轮转/archive）", file=sys.stderr)
        sys.exit(2)
    keyword = extra[0]
    world_dir = world_dir.resolve()
    hits = []
    files = sorted(world_dir.rglob("*"))
    for fp in files:
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in (".md", ".yaml", ".yml"):
            continue
        if not live_only:
            # 默认全仓（含历史轮转文件——残留可能藏在旧 narrative）
            pass
        else:
            # --live: 排除 narrative.<时间戳>.md 与 archive 目录
            if re.search(r"narrative\.\d{8}_\d{6}\.md$", fp.name):
                continue
            if "archive" in fp.parts:
                continue
        try:
            text = fp.read_text(errors="replace")
        except Exception:
            continue
        rel = fp.relative_to(world_dir)
        for i, line in enumerate(text.splitlines(), 1):
            if keyword in line:
                hits.append(f"{rel}:{i}: {line.strip()}")
    if hits:
        print(f"[SCAN] '{keyword}' 共 {len(hits)} 处残留：")
        for h in hits:
            print(f"  {h}")
        sys.exit(1)
    print(f"[SCAN] '{keyword}' 无匹配——干净 ✅")
    sys.exit(0)



def _ct_sides(desc: str) -> list[str]:
    """从 CT 对抗双方 文本解析角色名（'A（注释） vs B（注释）' → [A, B]·抽象方无状态文件时调用方跳过）。"""
    if not desc:
        return []
    sides = re.split(r"\s+vs\s+", desc, maxsplit=1)
    if len(sides) < 2:
        sides = re.split(r"vs", desc, maxsplit=1)
        if len(sides) < 2:
            return []
    out = []
    for s in sides:
        name = s.split("（", 1)[0].split("(", 1)[0].strip()
        if name:
            out.append(name)
    return out


def _char_state_field_value(state: dict, field: str):
    """取 CHAR_state 关键字段值——列表字段（记忆锚点/信念演化）返回条数（基准比较用）。"""
    v = state.get(field)
    if field in CLIMAX_LIST_FIELDS:
        return len(v) if isinstance(v, list) else 0
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    return str(v)


def _climax_baseline_snapshot(world_dir: Path, n: str) -> dict:
    """快照事件线 n 牵动 CT 的对抗双方 CHAR_state 关键字段（进入顶点拍时记录·顶点拍起点状态）。
    找 conflicts 中 `当前节拍.拍名` 前缀 `{n}-` 的 CT → 对抗双方 → 读双方状态关键字段。
    返回 {角色名: {字段: 基准值}}——无牵动 CT / 无状态文件时返回空 dict（出线时拦）。"""
    fp = world_dir / "conflicts.yaml"
    if not fp.exists():
        return {}
    try:
        data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    prefix = f"{n}-"
    sides: list[str] = []
    for ctk, ct in data.items():
        if not isinstance(ct, dict) or not str(ctk).startswith("CT-"):
            continue
        beat_ref = ct.get("当前节拍")
        if isinstance(beat_ref, dict) and str(beat_ref.get("拍名", "") or "").strip().startswith(prefix):
            for s in _ct_sides(str(ct.get("对抗双方", "") or "")):
                if s not in sides:
                    sides.append(s)
    existing = discover_files(world_dir, get_scene_dir(world_dir))
    snap: dict[str, dict] = {}
    for s in sides:
        key = f"{CHAR_STATE_PREFIX}{s}{CHAR_STATE_SUFFIX}".removesuffix(".yaml")
        fp2, _ = resolve_char_file(existing, key, world_dir)
        if fp2 is None or not fp2.exists():
            continue
        try:
            st = yaml.safe_load(fp2.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(st, dict):
            continue
        snap[s] = {f: _char_state_field_value(st, f) for f in CLIMAX_KEY_FIELDS}
    return snap


def _snapshot_climax_baseline(line: dict, world_dir: Path, n: str) -> None:
    """进入顶点拍（add 起点=顶点 / advance N 顶点 / rewrite 后当前拍=顶点）时，
    自动快照该线牵动 CT 对抗双方的 CHAR_state 关键字段为 顶点落点.基准值（脚本自动·LLM 不填）。"""
    for b in (line.get("拍序") or []):
        if isinstance(b, dict) and str(b.get("拍名", "") or "").strip() == "顶点" and isinstance(b.get("顶点落点"), dict):
            b["顶点落点"][CLIMAX_BASELINE_KEY] = _climax_baseline_snapshot(world_dir, n)
            return


def _check_climax_exit(world_dir: Path, ops, beatsheet_lines) -> tuple[list[str], bool]:
    """顶点出线核验（硬性·gate dramatist --check 调用·收束需要证明）：
    批次声明 `advance N 余波 形态:XXX` 且该线当前拍=顶点 时——
    ① 形态∈四形态枚举（缺/非法=拦）；② 声明形态对应字段族至少一字段发生实质变化
    （≠顶点落点.基准值·当前文件+批次写 op 预演）；③ 双方全无变化=顶点未落地（拦·撤回阶段1）。
    返回 (违规消息列表, 是否执行了核验)。"""
    violations: list[str] = []
    checked = False
    if not beatsheet_lines:
        return violations, checked
    # 1. 找批次中的顶点出线动作 advance N 余波（可带 形态:XXX 指认）
    line_no = None
    form = ""
    for bl in beatsheet_lines:
        m = re.match(r"^advance\s+(\d+)\s+余波(?:\s+形态[:：]\s*(.+))?$", bl[0].strip())
        if m:
            line_no = m.group(1)
            form = (m.group(2) or "").strip()
            break
    if line_no is None:
        return violations, checked
    checked = True
    # 1b. 形态指认（收束证明·缺/非法=拦）
    if not form:
        violations.append(f"顶点出线（advance {line_no} 余波）缺 爆破形态 指认——出线行须带 形态:四形态之一（收束需要证明·展开不需要）·留顶点 stay {line_no} 或补形态重提")
        return violations, checked
    if form not in CLIMAX_FORMS:
        violations.append(f"顶点出线（advance {line_no} 余波）形态 '{form}' 非法（四形态: {'/'.join(CLIMAX_FORMS)}）")
        return violations, checked
    # 2. 读事件线：当前拍=顶点 才核验（非顶点出线不拦截）
    fp = world_dir / "conflicts.yaml"
    if not fp.exists():
        return violations, checked
    try:
        cdata = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return violations, checked
    beats = cdata.get(BEAT_TOP_KEY) or {}
    line = beats.get(line_no) if isinstance(beats, dict) else None
    if not isinstance(line, dict) or str(line.get("当前拍", "") or "").strip() != "顶点":
        return violations, checked
    # 3. 顶点落点（戏剧目标声明·缺/空则拦）
    landing = None
    for b in (line.get("拍序") or []):
        if isinstance(b, dict) and str(b.get("拍名", "") or "").strip() == "顶点":
            landing = b.get("顶点落点")
            break
    if not isinstance(landing, dict):
        violations.append(f"顶点出线（advance {line_no} 余波）缺 顶点落点——事件线 {line_no} 顶点拍未预设（建线/换线时预填 角色/内部变量）")
        return violations, checked
    if not str(landing.get("角色", "") or "").strip() or not str(landing.get("内部变量", "") or "").strip():
        violations.append("顶点落点 缺 角色/内部变量（戏剧目标声明·建线/换线时预填）——出线前须 rewrite 重声明")
        return violations, checked
    # 4. 基准值（顶点拍起点快照·脚本自动）——缺则拦
    baseline = landing.get(CLIMAX_BASELINE_KEY)
    if not isinstance(baseline, dict) or not baseline:
        violations.append(f"顶点落点.基准值 缺失——顶点拍起点状态未快照（advance {line_no} 顶点 时脚本自动记录）·先 stay 顶点·重新进入后再出线")
        return violations, checked
    # 5. 预演比较：任一方任一关键字段 ≠ 基准 = 变化发生（收集字段集·供形态联动）
    existing = discover_files(world_dir, get_scene_dir(world_dir))
    changed_any = False
    changed_fields: set[str] = set()
    detail: list[str] = []
    for side, base_fields in baseline.items():
        if not isinstance(base_fields, dict):
            continue
        key = f"{CHAR_STATE_PREFIX}{side}{CHAR_STATE_SUFFIX}".removesuffix(".yaml")
        fp2, _ = resolve_char_file(existing, key, world_dir)
        cur: dict = {}
        if fp2 is not None and fp2.exists():
            try:
                d = yaml.safe_load(fp2.read_text(encoding="utf-8")) or {}
                cur = d if isinstance(d, dict) else {}
            except Exception:
                cur = {}
        for field, base in base_fields.items():
            val = _char_state_field_value(cur, field)
            for kind, fk, kp, content, append in ops:
                if kind != "write" or fk != key or kp != field:
                    continue
                if field in CLIMAX_LIST_FIELDS:
                    n_items = 0
                    if isinstance(content, str):
                        n_items = content.count("\n- ") + (1 if content.strip().startswith("- ") else 0)
                    val = (val + n_items) if append else n_items
                else:
                    if not append:
                        val = content
            if str(val) != str(base):
                changed_any = True
                changed_fields.add(field)
                detail.append(f"{side}.{field}: {base!r} → {val!r}")
    if not changed_any:
        violations.append(
            f"顶点未落地——事件线 {line_no} 顶点拍展开期间 冲突双方关键状态均无实质变化（顶点落点.基准值 全部字段未变）·留顶点（beatsheet stay {line_no}）或 rewrite 更新 顶点落点 重声明"
        )
    elif not (changed_fields & set(CLIMAX_FORM_FIELDS[form])):
        violations.append(
            f"顶点出线（advance {line_no} 余波）形态-字段不匹配：声明形态 '{form}' 对应字段族（{'/'.join(CLIMAX_FORM_FIELDS[form])}）均无实质变化（变化在: {'/'.join(sorted(changed_fields))}）——收束需要证明·留顶点 stay {line_no} 或 rewrite 更新 顶点落点 重声明"
        )
    else:
        print(f"[GATE] 顶点出线核验通过（形态 '{form}'·字段族变化 {len(detail)} 处·收束证明成立）", file=sys.stderr)
        for d in detail[:3]:
            print(f"  · {d}", file=sys.stderr)
    return violations, checked


def cmd_gate(world_dir: Path, extra: list[str], check_mode: bool = False):
    """gate: 流程闸门工具化——强制在阶段1 结束（write-raw 前）与阶段2 推送前调用。
    用法: worldctl.py <世界> gate dramatist|writer [--check]
    - 无 --check: 输出该阶段闸门清单（D1-D10 / W1-W4），要求逐项作答（通过/不通过/跳过+证据）。
    - 带 --check: 从 stdin 读取已生成的 change set 或叙事，运行可代码化检查（必含项/锚点），输出硬性违规——不合格 exit 1。
    """
    phase = extra[0] if extra else ""
    scene_dir = get_scene_dir(world_dir)

    if phase == "dramatist":
        print("=" * 60, file=sys.stderr)
        print("[GATE] 阶段1 出口闸门 · 戏剧家 D1-D10（独立审计·默认不通过·逐项找茬）", file=sys.stderr)
        checklist = [
            "D1  冲突推进: ≥1 条 CT 推进/注册",
            "D2  代价前置: 双方可核验变化（资源易主/载体状态/伤害/控制权/被迫选择/关系档位）",
            "D2① 资源载体: 被争夺资源含 当前载体=/当前持有者=",
            "D3  档案强度: 反应强度 ≥ 档案基准",
            "D4  认知边界: 行为/台词有叙事来源",
            "D5  Value Boundary: 在场角色逐人查 CHAR_* X 条件",
            "D6  抽象方出手: 显现机制+出手形态+抵抗痕迹",
            "D7  焦外演化: pending_actions 滚动累积",
            "D8  记忆维护: 判型/重置/入锚/淘汰/提炼 落 change set",
            "D9  循环轨道: 循环角色在轨/偏离/回归",
            "D10 世界收尾: 时间/轮次/前情/时间线 齐备",
        ]
        for line in checklist:
            print("  " + line, file=sys.stderr)
        print("  输出格式: D1 {通过|不通过|跳过}+证据 → 全部通过才进阶段2", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        if check_mode:
            # 可代码化部分：stdin change set 必含项（与 write-raw audit 同一套）
            raw = sys.stdin.buffer.read().decode("utf-8")
            if not raw.strip():
                print("[GATE] 未提供 change set（stdin 为空）——批次缺失，闸门拦截：不进阶段2", file=sys.stderr)
                sys.exit(1)
            ops, parse_errors, meta_lines, beatsheet_lines = parse_batch_entries(raw.split("\n"))
            hard, soft = check_batch(ops, world_dir, beatsheet_lines, meta_lines)
            # ###BEATSHEET 事件线动作：回显（软性缺失由 batch_required 升级为硬拦）
            if beatsheet_lines:
                print(f"[GATE] ###BEATSHEET 回显: {beatsheet_lines[0]}", file=sys.stderr)
            # ###META 静默自查锚点：回显/缺失告警（软性·与 audit/write-raw 一致）
            if meta_lines:
                print(f"[GATE] ###META 回显: {meta_lines[0]}", file=sys.stderr)
                if "记忆" not in meta_lines[0]:
                    print("[GATE] 软性告警: ###META 静默自查锚点缺少 记忆✓ 槽（记忆✓=逐角色同类计数留痕·每出场角色必列·见 SKILL.md §记忆维护）", file=sys.stderr)
            else:
                print("[GATE] 软性告警: 未检测到 ###META: 静默自查锚点——完整推进轮批次首行必写（查询轮/维护轮豁免）", file=sys.stderr)
            # 批次必含项缺失（soft·op_index=-1 且消息为「完整推进轮 change set 应含」）→ 硬拦 exit 1
            batch_required = [msg for idx, msg in soft if idx == -1 and msg.startswith("完整推进轮 change set 应含")]
            field_violations = [msg for idx, msg in hard if idx != -1]
            # 节拍表空拍检查（软性·先于硬拦打印）：建线应预设完整拍序·推进/换线后空拍仍在=现实与该拍无法承接
            _c_fp = world_dir / "conflicts.yaml"
            if _c_fp.exists():
                try:
                    _cdata = yaml.safe_load(_c_fp.read_text(encoding="utf-8")) or {}
                except Exception:
                    _cdata = {}
                _beats = _cdata.get(BEAT_TOP_KEY) or {}
                if isinstance(_beats, dict):
                    for _n in sorted(_beats, key=lambda x: int(x) if str(x).isdigit() else 0):
                        _line = _beats[_n]
                        if isinstance(_line, dict):
                            for _w in _empty_beat_warnings(_line):
                                print(f"[GATE] 提醒: 节拍表 事件线 {_n} {_w}", file=sys.stderr)
            # 顶点出线核验（硬性·advance N 余波）：比对 顶点落点.基准值（冲突双方关键状态变化·双方全无变化=撤回阶段1）
            climax_violations, climax_checked = _check_climax_exit(world_dir, ops, beatsheet_lines)
            if parse_errors or field_violations or batch_required or climax_violations:
                if parse_errors or field_violations or batch_required:
                    print("[GATE] D1/D10 代码化核验失败——change set 不合格:", file=sys.stderr)
                    for e in parse_errors:
                        print(f"  - {e}", file=sys.stderr)
                    for msg in batch_required:
                        print(f"  - {msg}", file=sys.stderr)
                    for msg in field_violations:
                        print(f"  - {msg}", file=sys.stderr)
                if climax_violations:
                    print("[GATE] 顶点出线核验失败——change set 不合格:", file=sys.stderr)
                    for msg in climax_violations:
                        print(f"  - {msg}", file=sys.stderr)
                sys.exit(1)
            if climax_checked:
                print("[GATE] 顶点出线核验通过（冲突双方关键状态任一方实质变化·顶点落地）", file=sys.stderr)
            # 其余软性提醒（跨叙事核对/行为偏移落地等）打印不拦截
            for idx, msg in soft:
                if idx == -1 and not msg.startswith("完整推进轮 change set 应含"):
                    print(f"[GATE] 提醒: {msg}", file=sys.stderr)
            print("[GATE] D1/D10 代码化核验通过（硬性必含项齐备）——其余 D2-D9 请人工逐项作答", file=sys.stderr)

    elif phase == "writer":
        print("=" * 60, file=sys.stderr)
        print("[GATE] 阶段2 输出闸门 · 作家 W1-W4（独立审计·默认不通过·逐项找茬）", file=sys.stderr)
        checklist = [
            "W1  数据忠诚: 行为在 conflicts 有依据·物理元素在 scene_state 有来源",
            "W2  认知边界: POV 能看见/听见/推理出吗·内部动机用可观察动作表达",
            "W3  代价在纸上: 失去/转折出现在叙事里·不只存在于 YAML",
            "W4  锚点约束: 空间元素→物理锚点·物品→道具·线索→关键场景信息",
        ]
        for line in checklist:
            print("  " + line, file=sys.stderr)
        print("  输出格式: W1-W4 逐项 {通过|不通过|跳过}+证据 → 全部通过才推送", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        if check_mode:
            raw = sys.stdin.buffer.read().decode("utf-8")
            if not raw.strip():
                print("[GATE] 未提供叙事（stdin 为空）——W1/W3 无法代码化核验，请人工逐项作答", file=sys.stderr)
                return
            # W4 可代码化部分（与 write_narrative.sh 同一套逻辑）：叙事「」内专名若命中锚点词，
            # 必须与注册名有完整包含关系；位置型锚点核对叙事同语境无矛盾位置词
            registered = {}
            scenes_dir = world_dir / "scenes"
            if scenes_dir.is_dir():
                for sdir in sorted(scenes_dir.iterdir()):
                    ssp = sdir / "scene_state.yaml"
                    if ssp.exists():
                        try:
                            sdata = yaml.safe_load(ssp.read_text())
                        except Exception:
                            continue
                        if not isinstance(sdata, dict):
                            continue
                        for fld in ("物理锚点", "道具"):
                            val = sdata.get(fld)
                            if not val:
                                continue
                            for line in str(val).splitlines():
                                line = line.strip()
                                m = re.match(r"^(?:\d+\.\s*|[A-Z]+\d*\s+|[·\-]\s*)?([^:：—]+?)\s*[:：—]\s*(.*)$", line)
                                if m:
                                    registered.setdefault(m.group(1).strip(), m.group(2).strip())
                                pm = re.match(r"^\|\s*P\d+\s*\|\s*([^|]+)\s*\|\s*([^|]*)\s*\|", line)
                                if pm:
                                    registered.setdefault(pm.group(1).strip(), pm.group(2).strip())
            anchor_words = {"门", "窗", "床", "楼梯", "钢琴", "吧台", "暗门", "金库", "后厨", "油灯",
                           "纸玫瑰", "大门", "正门", "散桌", "房间", "门帘", "教堂", "月台", "墙根",
                           "柜台", "长椅", "地窖", "盖板", "楼梯口", "窗户", "酒杯", "筷子"}
            LOC_PATTERNS = [
                (r"二楼", ["楼下", "一楼", "下楼", "走上楼去弹"]),
                (r"一楼", ["楼上", "二楼", "上楼"]),
                (r"吧台后", ["门外", "街上"]),
                (r"后厨", ["二楼"]),
                (r"门口", ["楼上"]),
            ]
            quoted = set(re.findall(r"「([^」]{1,12})」", raw))
            suspect = []
            # 对话语境跳过：前 4 字含言语动词 或 「」内以句末标点结尾 → 是台词，不是空间元素引用
            SPEECH_VERBS = r"说|问|答|叫|喊|骂|复述|念|低声道|开口|吼|嚷|应声"
            for q in quoted:
                pos = raw.find("「" + q + "」")
                prev = raw[max(0, pos - 4):pos]
                is_speech = bool(re.search(SPEECH_VERBS, prev)) or q.endswith(("。", "？", "！", "——"))
                if is_speech:
                    continue
                hit_word = next((w for w in anchor_words if w in q), None)
                if not hit_word:
                    continue
                matches = [(rname, rdesc) for rname, rdesc in registered.items()
                           if q == rname or q in rname or rname in q]
                if not matches:
                    suspect.append(f"{q}（未注册——「{hit_word}」在注册表中无包含关系匹配）")
                    continue
                ctx = raw[max(0, raw.find(q) - 25): raw.find(q) + len(q) + 25]
                for rname, rdesc in matches:
                    for loc_re, conflict_words in LOC_PATTERNS:
                        if re.search(loc_re, rdesc):
                            for cw in conflict_words:
                                if cw in ctx:
                                    suspect.append(f"{q}（注册「{rname}」位置含「{loc_re}」但叙事同语境出现「{cw}」）")
                                    break
            # W4 人物存在性（可代码化项·与 gate_writer.md 一致）：叙事中具名角色 vs CHAR_*.md
            # 规则：每个具名/有台词/有行动的人物必须有 CHAR_.md（新人物二选一：补注册/降级背景剪影）
            # 代码化边界：只能可靠拦截「英文专名型」新人物；描述性称谓（骑马者/长外套）由写作时数据忠诚③人工拦截
            char_md_names = set()
            for fp in world_dir.glob("CHAR_*.md"):
                stem = fp.stem[len("CHAR_"):].strip()
                if stem:
                    char_md_names.add(stem)
            # 豁免：非角色专名（场景/组织/道具/系统）+ Guest/玩家 + 已知无档案的叙事称谓
            KNOWN_NO_CHAR = {
                "Guest", "Mesa", "QA", "游客", "便衣", "灰衣", "前门便衣",
                "Westworld", "Sweetwater", "Mariposa", "Delos", "Welcome", "Center",
                "Host", "Hosts", "Smart", "Ammo", "Mesa Hub", "The Maze", "Maze",
            }
            # 提取叙事中出现的英文专名（大写开头词/词组·排除句首·排除全大写缩写）
            name_pat = re.compile(r"\b([A-Z][a-zA-Z]+(?:[\s][A-Z][a-zA-Z]+)*)\b")
            text_no_speech = re.sub(r"「[^」]*」", "", raw)  # 去对话（台词内人名不算引用）
            found_names = set()
            for m in name_pat.finditer(text_no_speech):
                name = m.group(1).strip()
                # 排除句首（前一个非空白字符是句号/叹号/问号/破折号——换行不算句首）
                prev_ch = text_no_speech[max(0, m.start() - 1):m.start()]
                if prev_ch in "。！？—":
                    continue
                found_names.add(name)
            # 从 found_names 中挑出「非豁免 且 非 CHAR 名单」的 → 缺失档案
            char_suspect = []
            for n in sorted(found_names):
                if n in KNOWN_NO_CHAR:
                    continue
                if any(n == real or n in real or real in n for real in char_md_names):
                    continue
                # 可能误报（普通英文词/地名）——仅当该名在叙事中承担行动者角色才报：
                # 后续出现「XX说/问/答/喊」或「XX 从/走/进/推」结构
                action_ctx = re.search(rf"{re.escape(n)}\s*(说|问|答|喊|吼|嚷|开口|走进|走出|推门|站在|从门外|从街角|翻身下马)", raw)
                if action_ctx:
                    char_suspect.append(f"{n}（叙事中作为行动者出现但 CHAR_*.md 缺失——阶段1 补注册或降级背景剪影）")
            if char_suspect:
                print(f"[GATE] W4 人物存在性失败——叙事中具名行动人物无 CHAR_*.md: {char_suspect}（数据忠诚③人物项·新人物二选一：补注册/降级不具名不说话）", file=sys.stderr)
                sys.exit(1)
            if suspect:
                print(f"[GATE] W4 锚点核验失败——叙事「」内元素疑似未注册或位置冲突: {suspect}（请用 worldctl.py <世界> grep <元素名> 核对注册原文）", file=sys.stderr)
                sys.exit(1)
            print("[GATE] W4 锚点核验通过（叙事「」内专名均已注册且位置一致）——W1/W2/W3 请人工逐项作答", file=sys.stderr)
            print("[GATE] 回合收尾提醒（静默模式）：正文只含 message 叙事·回合结束零正文输出（状态摘要/执行汇报/叙事复述/下一步引导一律禁止）", file=sys.stderr)

    else:
        print("用法: worldctl.py <世界> gate dramatist|writer [--check]", file=sys.stderr)
        print("  dramatist: 阶段1 出口闸门 D1-D10（write-raw 前调用）", file=sys.stderr)
        print("  writer:    阶段2 输出闸门 W1-W4（message 推送前调用）", file=sys.stderr)
        print("  --check: 从 stdin 读 change set/叙事，运行可代码化硬性核验，不合格 exit 1", file=sys.stderr)
        sys.exit(1)



def cmd_validate(world_dir: Path):
    scene_dir = get_scene_dir(world_dir)
    files = discover_files(world_dir, scene_dir)
    errors = []
    for key, fp in sorted(files.items()):
        try:
            data = yaml.safe_load(fp.read_text())
            if data is None:
                errors.append(f"{key}: 空文件")
        except yaml.YAMLError as e:
            errors.append(f"{key}: YAML 解析错误: {e}")
        except Exception as e:
            errors.append(f"{key}: {e}")
    # 检查未转换的 .md 文件（仅检查状态文件，排除角色设定文件和世界观文件）
    state_md_patterns = ["world_state.md", "conflicts.md", "pending_actions.md", "scene_state.md"] + \
                       [f.name for f in world_dir.glob(f"{CHAR_STATE_PREFIX}*_state.md")]
    for state_md_name in state_md_patterns:
        fp = world_dir / state_md_name
        if not fp.exists():
            # 可能在子目录
            if scene_dir:
                fp = scene_dir / state_md_name
            if not fp.exists():
                continue
        if fp.suffix == ".md" and not fp.name.endswith(".bak"):
            yaml_fp = fp.with_suffix(".yaml")
            if not yaml_fp.exists():
                errors.append(f"{fp.name}: 仍为 .md 格式，未转换为 .yaml")
    # ── 内容级检查（警告，不阻断）──
    warnings = []
    # 1. conflicts.yaml 顶层键应为 CT-XX
    conflicts_fp = world_dir / "conflicts.yaml"
    if conflicts_fp.exists():
        try:
            cdata = yaml.safe_load(conflicts_fp.read_text())
            if isinstance(cdata, dict):
                for k in cdata:
                    if not re.match(r"^CT-\d{2}$", str(k)) and str(k) != BEAT_TOP_KEY:
                        warnings.append(f"conflicts.yaml: 顶层键 '{k}' 不符合 CT-XX 格式")
                    else:
                        cv = cdata[k]
                        if isinstance(cv, dict) and cv.get("当前节拍") and not cv.get("下一个节拍(推荐)"):
                            warnings.append(f"conflicts.yaml: {k} 有当前节拍但缺「下一个节拍(推荐)」（推进轮必写·多候选·方向灵活）")
                # 1b. 节拍表 CT 对齐（软性）——牵动 CT 的 当前节拍.拍名 应为某事件线 当前拍 的镜像
                beats = cdata.get(BEAT_TOP_KEY)
                if isinstance(beats, dict) and beats:
                    for k in cdata:
                        if not re.match(r"^CT-\d{2}$", str(k)):
                            continue
                        cv = cdata[k]
                        if not isinstance(cv, dict):
                            continue
                        cp = cv.get("当前节拍")
                        if not isinstance(cp, dict):
                            continue
                        beat_name = str(cp.get("拍名", "") or "").strip()
                        if not beat_name:
                            continue
                        m = re.match(r"^(\d+)[-·](.+)$", beat_name)
                        if not m:
                            warnings.append(f"conflicts.yaml: {k}.当前节拍.拍名 '{beat_name}' 缺少事件线编号前缀——应为 `{{N}}-{{拍名}}`（如 `1-接触`）")
                            continue
                        n, name = m.group(1), m.group(2).strip()
                        ln = beats.get(n) or beats.get(int(n)) if str(n).isdigit() else None
                        if not isinstance(ln, dict) or str(ln.get("当前拍", "") or "").strip() != name:
                            warnings.append(f"conflicts.yaml: {k}.当前节拍.拍名 '{beat_name}' 未对齐事件线 {n} 的当前拍（节拍表.{n}.当前拍='{ln.get('当前拍', '') if isinstance(ln, dict) else ''}')——CT 拍名应镜像为 `{n}-{拍名}`")
                # 1c. 顶点落点结构（软性·戏剧目标声明）——角色/内部变量非空·预期形态枚举
                if isinstance(beats, dict) and beats:
                    for n, ln in beats.items():
                        if not isinstance(ln, dict):
                            continue
                        for b in (ln.get("拍序") or []):
                            if not isinstance(b, dict) or str(b.get("拍名", "") or "").strip() != "顶点":
                                continue
                            ld = b.get("顶点落点")
                            if not isinstance(ld, dict):
                                warnings.append(f"conflicts.yaml: 节拍表.{n} 顶点拍缺 顶点落点（戏剧目标声明·建线/换线时预填 角色/内部变量）")
                                continue
                            if not str(ld.get("角色", "") or "").strip():
                                warnings.append(f"conflicts.yaml: 节拍表.{n}.顶点落点 缺 角色（爆破承受者·冲突双方皆可·任一方达成即落地）")
                            if not str(ld.get("内部变量", "") or "").strip():
                                warnings.append(f"conflicts.yaml: 节拍表.{n}.顶点落点 缺 内部变量（戏剧目标·哪样东西碎掉）")
                            form = str(ld.get("预期形态", "") or "").strip()
                            if form and form not in CLIMAX_FORMS:
                                warnings.append(f"conflicts.yaml: 节拍表.{n}.顶点落点.预期形态 '{form}' 非法（四形态: {'/'.join(CLIMAX_FORMS)}）")
                elif not isinstance(beats, dict) or not beats:
                    # 1c. 有 CT 当前节拍但节拍表为空——事件线应建未建
                    if any(isinstance(cdata.get(k), dict) and isinstance((cdata.get(k) or {}).get("当前节拍"), dict)
                           and any(str(v or "").strip() for v in (cdata.get(k) or {}).get("当前节拍", {}).values())
                           for k in cdata if re.match(r"^CT-\d{2}$", str(k))):
                        warnings.append("conflicts.yaml: 存在 CT 当前节拍但 节拍表 为空——完整推进轮应建线（beatsheet add）并写 CT.当前节拍.拍名")
        except Exception:
            pass
    # 2. world_state.焦点场景（唯一权威源）↔ INDEX + 场景目录一致性
    index_fp = world_dir / "scenes" / "INDEX.md"
    ws_fp = world_dir / "world_state.yaml"
    focus_id = ""
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text())
            if isinstance(ws, dict):
                if ws.get("焦点场景"):
                    focus_id = str(ws["焦点场景"]).strip()
                elif not (ws.get("地点") or {}).get("焦点场景") and not (ws.get("地点") or {}).get("当前焦点场景"):
                    warnings.append("world_state.yaml: 缺顶层键 焦点场景（唯一权威源，应置于第一行）")
        except Exception:
            pass
    if focus_id:
        scenes_dir = world_dir / "scenes"
        dir_ok = False
        if scenes_dir.is_dir():
            for d in scenes_dir.iterdir():
                if d.is_dir() and d.name.startswith(focus_id):
                    dir_ok = True
                    break
        if not dir_ok:
            warnings.append(f"焦点场景 '{focus_id}': 无对应场景目录 scenes/{focus_id}-*")
        if index_fp.exists():
            index_text = index_fp.read_text()
            if not re.search(rf"\|[ ]*{re.escape(focus_id)}[ ]*\|", index_text):
                warnings.append(f"焦点场景 '{focus_id}' 未在 scenes/INDEX.md 的表格行中找到")
            active_rows = re.findall(r"^\|\s*(S\d+)\s*\|.*\|\s*ACTIVE\s*\|", index_text, re.M)
            if active_rows and active_rows != [focus_id]:
                warnings.append(f"INDEX ACTIVE 行 {active_rows} 与 world_state.焦点场景 '{focus_id}' 不一致")
    elif ws_fp.exists() and index_fp.exists() and not focus_id:
        active_rows = re.findall(r"^\|\s*(S\d+)\s*\|.*\|\s*ACTIVE\s*\|", index_fp.read_text(), re.M)
        if active_rows:
            warnings.append(f"world_state.焦点场景 为空，但 INDEX 标记 {active_rows} 为 ACTIVE——焦点场景唯一权威源缺失")
    # 3. CHAR_*_state.yaml 应有对应 CHAR_*.md
    for sf in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        md_fp = world_dir / (sf.name[: -len(CHAR_STATE_SUFFIX)] + ".md")
        if not md_fp.exists():
            warnings.append(f"{sf.name}: 无对应 {md_fp.name}")
    # 4. world_state.yaml 必要键
    ws_fp = world_dir / "world_state.yaml"
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text())
            if isinstance(ws, dict):
                for need in ("焦点场景", "时间", "地点", "全局标记"):
                    if need not in ws:
                        warnings.append(f"world_state.yaml: 缺顶层键 {need}")
        except Exception:
            pass
    # 4b. world_state 键表外字段（软性警告——无语义定义的漂移字段）
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text())
            if isinstance(ws, dict):
                WS_TOP_KEYS = {"焦点场景", "轮次", "时间", "地点", "外部倒计时", "全局标记", "时间线", "重置记录", "叙事约定"}
                WS_TIME_KEYS = {"基准时间", "具体时间", "时间流速比", "前情描述"}
                WS_LOC_KEYS = {"当前区域", "已探索区域"}
                for k in ws:
                    if k not in WS_TOP_KEYS:
                        warnings.append(f"world_state.yaml: 未知顶层键 '{k}'（键表: 焦点场景/轮次/时间/地点/外部倒计时/全局标记/时间线/重置记录/叙事约定）")
                t = ws.get("时间")
                if isinstance(t, dict):
                    for k in t:
                        if k not in WS_TIME_KEYS:
                            warnings.append(f"world_state.yaml: 未知时间子键 '{k}'（键表: 基准时间/具体时间/时间流速比/前情描述）")
                loc = ws.get("地点")
                if isinstance(loc, dict):
                    for k in loc:
                        if k not in WS_LOC_KEYS:
                            warnings.append(f"world_state.yaml: 未知地点子键 '{k}'（键表: 当前区域/已探索区域）")
        except Exception:
            pass
    # 4c. 场景骨架占位检查（scene_card 目标/钩子/焦外、start_snapshot 姿态/道具——创建后禁止带模板占位运行）
    # 模板占位特征 = [字段定义] 或 (例: 示例)——真实场景文件不应含这两类（templates/ 符号契约）
    PLACEHOLDER_RE = re.compile(r"\[[^\]]{2,40}\]|\(例:")
    scenes_dir = world_dir / "scenes"
    if scenes_dir.is_dir():
        for d in sorted(scenes_dir.iterdir()):
            if not d.is_dir():
                continue
            sc_fp = d / "scene_card.md"
            if sc_fp.exists():
                sc_text = sc_fp.read_text(encoding="utf-8", errors="ignore")
                if PLACEHOLDER_RE.search(sc_text):
                    warnings.append(f"{d.name}/scene_card.md: 场景目标/前情钩子/焦外等仍为模板占位（[字段定义]/(例:) 残留）——创建后应已填充，禁止带占位运行")
            ss_fp = d / "start_snapshot.md"
            if ss_fp.exists():
                ss_text = ss_fp.read_text(encoding="utf-8", errors="ignore")
                if PLACEHOLDER_RE.search(ss_text):
                    warnings.append(f"{d.name}/start_snapshot.md: 角色姿态/道具位置等仍为模板占位（[字段定义]/(例:) 残留）——创建后应已填充，禁止带占位运行")
    # 5. world_map.yaml（可选增强层·迷雾制·多层嵌套）——缺失时静默跳过，不影响运行
    wm_fp = world_dir / "world_map.yaml"
    if wm_fp.exists():
        try:
            wm = yaml.safe_load(wm_fp.read_text())
            if not isinstance(wm, dict) or "已探索区域" not in wm:
                warnings.append("world_map.yaml: 缺顶层键 已探索区域（迷雾制地图，初始应为 {}）")
            else:
                scenes_dir = world_dir / "scenes"
                WM_KEYS = {"类型", "方位", "连接", "发现于", "备注", "子区域"}
                def walk_map(node, path):
                    """递归检查 world_map 节点：未知键 / 发现于引用 / 子区域结构"""
                    if not isinstance(node, dict):
                        warnings.append(f"world_map.yaml {path}: 值应为映射（节点字段/子区域）")
                        return
                    for k in node:
                        if k not in WM_KEYS:
                            warnings.append(f"world_map.yaml {path}.{k}: 未知键（应为 类型/方位/连接/发现于/备注/子区域）")
                    found = str(node.get("发现于", "") or "").strip()
                    if found and (not scenes_dir.is_dir() or not any(
                            d.is_dir() and d.name.startswith(found) for d in scenes_dir.iterdir())):
                        warnings.append(f"world_map.yaml {path}: 发现于 '{found}' 无对应场景目录")
                    kids = node.get("子区域")
                    if kids is not None:
                        if not isinstance(kids, dict):
                            warnings.append(f"world_map.yaml {path}.子区域: 值应为区域名→节点的映射")
                        else:
                            for name, sub in kids.items():
                                walk_map(sub, f"{path}.{name}")
                for name, sub in (wm.get("已探索区域") or {}).items():
                    walk_map(sub, f"已探索区域.{name}")
        except Exception:
            pass
    # 5b. foreshadow.yaml 伏笔闭环检查（可选文件·仅世界有该文件时检查）
    fs_fp = world_dir / "foreshadow.yaml"
    if fs_fp.exists():
        try:
            fdata = yaml.safe_load(fs_fp.read_text())
            f_list = fdata.get("伏笔", []) if isinstance(fdata, dict) else None
            if f_list is None:
                errors.append("foreshadow.yaml: 缺顶层键 伏笔（应为列表）")
            elif not isinstance(f_list, list):
                errors.append("foreshadow.yaml: 顶层键 伏笔 应为列表")
            else:
                cur_round = 0
                if ws_fp.exists():
                    try:
                        ws_cur = yaml.safe_load(ws_fp.read_text())
                        if isinstance(ws_cur, dict):
                            cur_round = int(ws_cur.get("轮次") or 0)
                    except Exception:
                        pass
                for i, it in enumerate(f_list, 1):
                    if not isinstance(it, dict):
                        warnings.append(f"foreshadow.yaml 伏笔[{i}]: 元素应为映射（线索/种下/时间/回收/状态）")
                        continue
                    clue = str(it.get("线索", "")).strip()
                    status = str(it.get("状态", "")).strip()
                    try:
                        plant = int(it.get("种下") or 0)
                    except (TypeError, ValueError):
                        plant = -1
                    try:
                        pay = int(it.get("回收") or 0)
                    except (TypeError, ValueError):
                        pay = 0
                    if not clue:
                        warnings.append(f"foreshadow.yaml 伏笔[{i}]: 缺 线索")
                    if status not in ("待回收", "已回收", "废弃"):
                        warnings.append(f"foreshadow.yaml 伏笔[{i}]: 非法状态 '{status}'（枚举：待回收/已回收/废弃）")
                    elif status == "已回收":
                        if pay == 0:
                            warnings.append(f"foreshadow.yaml 伏笔[{i}] '{clue}': 已回收但缺 回收 轮次")
                        elif plant > 0 and pay < plant:
                            errors.append(f"foreshadow.yaml 伏笔[{i}] '{clue}': 回收轮次 {pay} 早于种下轮次 {plant}（伏笔倒置·硬错）")
                    elif status == "待回收" and plant > 0 and cur_round - plant > 20:
                        warnings.append(f"foreshadow.yaml 伏笔[{i}] '{clue}': 种下 {plant} 轮已过 {cur_round - plant} 轮未回收（>20 轮·建议回收或废弃）")
        except Exception as e:
            warnings.append(f"foreshadow.yaml: 解析失败 {e}")
    # 6. CHAR_state 字段级校验（键表/人际动态档位/废弃键/全知视角/反应轨迹方向）
    CHAR_ALLOWED_KEYS = {"位置", "已知地点", "名字", "核心状态", "情绪", "人际动态", "决策状态",
                         "压力水平", "防御有效性", "防御形态", "崩溃表现", "信念演化", "记忆锚点", "反应轨迹",
                         "偏离登记",
                         "自主性",
                         "服装", "健康", "随身"}
    RELATION_TIERS = {"稳固", "信任", "中立", "防备", "破裂", "待重建"}
    OMNI_PATTERN = re.compile(r"[他她]不知道")
    for cfp in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            cdata = yaml.safe_load(cfp.read_text())
        except Exception:
            continue
        if not isinstance(cdata, dict):
            continue
        cname = cfp.name
        # 6a. 未知顶层键（键表外字段=无语义定义的漂移字段）
        for k in cdata:
            if k not in CHAR_ALLOWED_KEYS:
                warnings.append(f"{cname}: 未知键 '{k}'（键表: 自主性/位置/已知地点/名字/核心状态/情绪/人际动态/决策状态/压力水平/防御有效性/防御形态/崩溃表现/信念演化/记忆锚点/反应轨迹；模板扩展: 服装/健康/随身）")
        # 6b. 废弃键
        if "信任度" in cdata:
            warnings.append(f"{cname}: 顶层键 信任度 已废弃——唯一权威源=人际动态各对象行档位，应删除")
        # 6c. 人际动态行格式（一行=一个关系对象；{对象}: {档位}——{一句现状}）
        rel = cdata.get("人际动态", "")
        if isinstance(rel, str):
            for line in rel.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("（无"):
                    continue
                m = re.match(r"^([^:：]+):\s*([^-—]+)——(.+)$", line)
                if not m:
                    warnings.append(f"{cname}: 人际动态行格式不符「{{对象}}: {{档位}}——{{一句现状}}」: {line[:40]}")
                elif m.group(2).strip() not in RELATION_TIERS:
                    warnings.append(f"{cname}: 人际动态档位 '{m.group(2).strip()}' 非法（枚举: 稳固/信任/中立/防备/破裂/待重建）: {line[:40]}")
            if "→" in rel:
                warnings.append(f"{cname}: 人际动态含 →（旧 A→B 写法已废弃，每行=一个关系对象）")
        # 6d. 全知视角模式（他/她不知道——本角色未知须用「我」）
        for field in ("核心状态", "情绪", "人际动态", "决策状态", "反应轨迹", "信念演化"):
            val = cdata.get(field, "")
            if isinstance(val, str) and OMNI_PATTERN.search(val):
                warnings.append(f"{cname}: {field} 含「他/她不知道」——全知视角禁止，应改为「我不知道」或感知边界内描述")
        # 6e. 反应轨迹方向判断缺失
        rt = cdata.get("反应轨迹", "")
        if isinstance(rt, str) and rt.strip() and not re.search(r"方向", rt):
            warnings.append(f"{cname}: 反应轨迹缺方向判断（方向: … 或 方向性判断: …）")
        # 6f. 自主性枚举（仅循环角色字段——非法值=键表外漂移）
        auto = cdata.get("自主性", "")
        if auto and auto not in {"脚本", "漂移", "觉醒", "变质"}:
            warnings.append(f"{cname}: 自主性 '{auto}' 非法（枚举: 脚本/漂移/觉醒/变质）")
        # 6g. 防御-压力联动（loop_machinery §3 影响字段——防御降级/崩解须压力支撑·防「叙事显影状态不动」的孤岛降级）
        defense = cdata.get("防御有效性", "")
        pressure = cdata.get("压力水平", "")
        # 豁免：防御重构进行中（防御形态非空 且 防御=正在失效=人格修复弧线的回升形态·SKILL.md §记忆维护·防御重构）——压力低是重构后的正常形态，不警告
        in_reconstruction = bool(str(cdata.get("防御形态", "") or "").strip())
        if (isinstance(defense, str) and defense in ("正在失效", "已彻底崩解") and pressure == "低"
                and not (in_reconstruction and defense == "正在失效")):
            warnings.append(f"{cname}: 防御有效性={defense} 但 压力水平=低——防御降级缺压力支撑（loop_machinery §3 影响字段: 压力↑→防御↓·先积累压力再降防）")

    # 7. world_state.时间线 粗粒度摘要校验（脚本校验线：条目≤10 | 单场景≤3转折点 | 总字数≤2500——超限告警，提示场记执行压缩维护）
    ws_fp = world_dir / "world_state.yaml"
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text())
            tl = (ws.get("时间线") or {}) if isinstance(ws, dict) else {}
            if tl:
                if len(tl) > 10:
                    warnings.append(f"world_state.时间线: {len(tl)} 条 > 10 条上限——需压缩最旧场景条目")
                total = 0
                for sid, sv in tl.items():
                    if not isinstance(sv, dict):
                        warnings.append(f"world_state.时间线.{sid}: 值应为映射（时间/事件）")
                        continue
                    ev = sv.get("事件", "")
                    if not isinstance(ev, str):
                        continue
                    total += len(ev)
                    nodes = ev.count("·")
                    if nodes > 3:
                        warnings.append(f"world_state.时间线.{sid}: {nodes} 个转折点 > 3 上限——需压缩为 ≤3 条粗粒度摘要（明细在 scene_state 场景时间线）")
                if total > 2500:
                    warnings.append(f"world_state.时间线: 总字数 {total} > 2500 上限——需执行压缩维护")
        except Exception:
            pass

    # 8. CHAR_state 记忆锚点校验（脚本校验线：单条≤150字宽松校验线 | 总字数≤3000——超限告警，提示戏剧家按 §记忆淘汰 整理；写作线单条≤100 见 audit 写前提醒）
    ANCHOR_LIMIT_TOTAL = 3000
    ANCHOR_LIMIT_ENTRY = ANCHOR_LIMIT_ENTRY_VALIDATE  # 150 宽松校验线（防强制压缩·写作按 100 为准）
    for cfp in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            cdata = yaml.safe_load(cfp.read_text())
        except Exception:
            continue
        if not isinstance(cdata, dict):
            continue
        mem = cdata.get("记忆锚点", "")
        if isinstance(mem, list):
            # 结构化列表：每条内容 ≤100 · 总内容字数 ≤3000
            total = 0
            long_entries = []
            for it in mem:
                if not isinstance(it, dict):
                    continue
                content = str(it.get("内容", ""))
                total += len(content)
                if len(content) > ANCHOR_LIMIT_ENTRY:
                    long_entries.append((len(content), content[:45].replace("\n", " ")))
            if total > ANCHOR_LIMIT_TOTAL:
                warnings.append(f"{cfp.name}: 记忆锚点 {total} 字 > {ANCHOR_LIMIT_TOTAL} 校验线——需按 §记忆淘汰 整理（同类融合+低刺激遗忘）")
            if long_entries:
                shown = "；".join(f"{n}字:{head}…" for n, head in long_entries[:3])
                more = f" 等{len(long_entries)}条" if len(long_entries) > 3 else ""
                warnings.append(f"{cfp.name}: 记忆锚点 {len(long_entries)} 条超单条 {ANCHOR_LIMIT_ENTRY} 字上限（应压为事实一句+定性一句）——{shown}{more}")
            continue
        if not isinstance(mem, str) or not mem.strip():
            continue
        total = len(mem)
        if total > ANCHOR_LIMIT_TOTAL:
            warnings.append(f"{cfp.name}: 记忆锚点 {total} 字 > {ANCHOR_LIMIT_TOTAL} 校验线——需按 §记忆淘汰 整理（同类融合+低刺激遗忘）")
        # 单条超限检测：按 [时间/对象] 或 [碎片 开头切分
        entries = re.split(r"\n\s*(?:·\s*)?(?=\[)", mem)
        long_entries = []
        for ent in entries:
            ent = ent.strip()
            if len(ent) > ANCHOR_LIMIT_ENTRY:
                long_entries.append((len(ent), ent[:45].replace("\n", " ")))
        if long_entries:
            shown = "；".join(f"{n}字:{head}…" for n, head in long_entries[:3])
            more = f" 等{len(long_entries)}条" if len(long_entries) > 3 else ""
            warnings.append(f"{cfp.name}: 记忆锚点 {len(long_entries)} 条超单条 {ANCHOR_LIMIT_ENTRY} 字上限（应压为事实一句+定性一句）——{shown}{more}")
        # 8a. 重复条目检测（内容完全相同=重复事故残留；同 ID 不同内容=合法多轮条目不报）
        seen_lines, dup_lines = {}, []
        for line in mem.splitlines():
            line_s = line.strip()
            if not line_s:
                continue
            if line_s in seen_lines:
                dup_lines.append(line_s[:45])
            else:
                seen_lines[line_s] = True
        if dup_lines:
            shown = "；".join(f"「{d}…」" for d in dup_lines[:2])
            more = f" 等{len(dup_lines)}条" if len(dup_lines) > 2 else ""
            warnings.append(f"{cfp.name}: 记忆锚点 {len(dup_lines)} 条内容完全重复（重复事故残留——按完整 ID+内容判定去重；同 ID 不同内容=合法）——{shown}{more}")

    # 8b. 重置落地校验（触发：world_state.重置记录 登记了角色+档位 → 对照该角色记忆锚点是否按档位压缩）
    try:
        ws_data = yaml.safe_load((world_dir / "world_state.yaml").read_text()) or {}
    except Exception:
        ws_data = {}
    # 8b-0. 循环机制完整性软告警（循环世界：SETTING 声明循环/重置关键词 → 周期倒计时应有周期条目）
    try:
        setting_fp = world_dir / "SETTING.md"
        setting_txt = setting_fp.read_text(encoding="utf-8", errors="ignore") if setting_fp.exists() else ""
        mech_kw = ("循环", "重置", "循环日终", "抹除记忆", "遗忘法则")
        is_loop_world = any(kw in setting_txt for kw in mech_kw)
        cd_data = ws_data.get("外部倒计时") or {}
        has_periodic = False
        if isinstance(cd_data, dict):
            for cd in cd_data.values():
                if isinstance(cd, dict) and ("周期" in str(cd.get("威胁", "")) or "重置" in str(cd.get("威胁", "")) or "循环" in str(cd.get("威胁", ""))):
                    has_periodic = True
                    break
        if is_loop_world and not has_periodic:
            warnings.append("循环机制完整性: SETTING 声明循环/重置机制但外部倒计时无周期条目（含空表）——周期倒计时未初始化登记（见 session_recovery.md §第三章循环机制核对）")
    except Exception:
        pass
    reset_rec = ws_data.get("重置记录") or {}
    if isinstance(reset_rec, dict):
        for rname, rspec in reset_rec.items():
            if not isinstance(rspec, dict):
                continue
            rlvl = str(rspec.get("档位", "")).strip()
            cfp = world_dir / f"{CHAR_STATE_PREFIX}{rname}{CHAR_STATE_SUFFIX}"
            if not cfp.exists():
                continue
            try:
                cdata = yaml.safe_load(cfp.read_text()) or {}
            except Exception:
                continue
            mem = cdata.get("记忆锚点", "")
            if isinstance(mem, list):
                has_frag = any("碎片" in str(it.get("内容", "")) or "碎片" in str(it.get("时间", "")) for it in mem if isinstance(it, dict))
                has_key = any("关键锚点" in str(it.get("内容", "")) for it in mem if isinstance(it, dict))
                old_ts_left = len([it for it in mem if isinstance(it, dict) and re.search(r"第\d+日", str(it.get("时间", "")))])
            elif isinstance(mem, str):
                has_frag = "碎片" in mem
                has_key = "关键锚点" in mem
                old_ts_left = len(re.findall(r"\[第\d+日/", mem))
            else:
                continue
            if rlvl == "脚本" and old_ts_left:
                warnings.append(f"重置落地校验: {cfp.name} 重置档位=脚本——应全清回基线·但记忆锚点仍有 {old_ts_left} 条带时间戳旧锚点残留")
            elif rlvl in ("漂移", "觉醒"):
                if not has_frag:
                    warnings.append(f"重置落地校验: {cfp.name} 重置档位={rlvl}——记忆锚点应含「碎片·缺时间感」压缩条目·但未找到")
                if rlvl == "觉醒" and not has_key:
                    warnings.append(f"重置落地校验: {cfp.name} 重置档位=觉醒——应保留关键锚点标记·但未找到「关键锚点」条目")
                if old_ts_left and rlvl == "漂移":
                    warnings.append(f"重置落地校验: {cfp.name} 重置档位=漂移——保留规则仅限「可揭示+重复≥2次+最后高刺激」·但有 {old_ts_left} 条带时间戳旧锚点残留")

    # 8c. 叙事新鲜度（焦点场景 narrative.md mtime vs world_state.yaml——叙事落后=可能未落盘）
    try:
        ws_fp2 = world_dir / "world_state.yaml"
        if ws_fp2.exists():
            ws2 = yaml.safe_load(ws_fp2.read_text()) or {}
            focus_id2 = str(ws2.get("焦点场景", "") or "").strip()
            if focus_id2 and scene_dir and scene_dir.is_dir():
                nf = scene_dir / "narrative.md"
                if nf.exists():
                    if nf.stat().st_mtime < ws_fp2.stat().st_mtime - 300:  # 早于 world_state 5 分钟以上
                        warnings.append(f"叙事新鲜度: {scene_dir.name}/narrative.md 修改时间早于 world_state.yaml——叙事可能未落盘（每轮阶段2 叙事应经 write_narrative.sh 写入，缺失=连续性断裂）")
                else:
                    warnings.append(f"叙事新鲜度: {scene_dir.name}/narrative.md 不存在（焦点场景叙事文件缺失）")
    except Exception:
        pass

    # 8d. CRLF 行尾检测（防 Windows/rsync 引入 CRLF——破坏 shell 语法与脚本解析）
    crlf_hits = []
    for cfp in sorted(world_dir.rglob("*")):
        if not cfp.is_file() or ".git" in cfp.parts:
            continue
        if cfp.suffix not in (".yaml", ".md", ".sh", ".txt"):
            continue
        try:
            if b"\r\n" in cfp.read_bytes():
                crlf_hits.append(str(cfp.relative_to(world_dir.parent)))
        except Exception:
            continue
    if crlf_hits:
        shown = "；".join(crlf_hits[:5])
        more = f" 等 {len(crlf_hits)} 个" if len(crlf_hits) > 5 else ""
        warnings.append(f"CRLF 行尾: {len(crlf_hits)} 个文件含 \\r\\n（Windows/rsync 引入·会破坏 shell 语法）——应转 LF（.gitattributes 已锁定 eol=lf，git add 自动规范化）: {shown}{more}")

    if errors:
        print(f"[VALIDATE] {len(errors)} 个问题:")
        for e in errors:
            print(f"  - {e}")
    elif warnings:
        print(f"[VALIDATE] 格式通过 ✅，{len(warnings)} 个内容警告:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print(f"[VALIDATE] 全部 {len(files)} 个文件验证通过 ✅")

# ── CLI ───────────────────────────────────────────────────────────
def _beatsheet_usage():
    print("用法: worldctl.py <世界> beatsheet <子命令> [参数]", file=sys.stderr)
    print("  show [N]          读节拍表（全部 / 指定事件线 N）", file=sys.stderr)
    print("  add               stdin YAML 建线（追加事件线 N·N 自动递增）", file=sys.stderr)
    print("  stay N            停留当前拍（当前拍内容未完成·拍序保持原样·下轮继续）", file=sys.stderr)
    print("  advance N 拍名    推进事件线 N 到指定拍（写 当前拍）", file=sys.stderr)
    print("  rewrite N         stdin YAML 换线（现实不承接·判线仍有继续价值时重写事件线 N）", file=sys.stderr)
    print("  clear N           清线（当前拍=余波 或 现实与当前拍不承接时·清空保留字段名）", file=sys.stderr)
    print("add/rewrite stdin 事件线 YAML 骨架（拍序含顶点拍时须带 顶点落点）:", file=sys.stderr)
    print("  事件线: 事件标识", file=sys.stderr)
    print("  当前拍: 接触", file=sys.stderr)
    print("  拍序:", file=sys.stderr)
    print("  - 拍名: 接触", file=sys.stderr)
    print("    空间: 地点 / 时间: 时刻 / 事件: A 动作 → B 动作", file=sys.stderr)
    print("  - 拍名: 顶点", file=sys.stderr)
    print("    空间: 地点 / 时间: 待定 / 事件: A 动作 → B 动作", file=sys.stderr)
    print("    顶点落点:", file=sys.stderr)
    print("      角色: 爆破承受者（冲突双方皆可） / 内部变量: 哪样东西碎掉 / 预期形态(可选): 四形态之一", file=sys.stderr)


def _validate_storyline(line) -> str | None:
    """校验单条事件线结构。返回错误描述，None=通过。"""
    if not isinstance(line, dict):
        return "事件线必须是映射（事件线/当前拍/拍序）"
    if "事件线" not in line or not str(line.get("事件线", "")).strip():
        return "缺 事件线（当前跨轮展开的戏剧事件标识）"
    if "当前拍" not in line or not str(line.get("当前拍", "")).strip():
        return "缺 当前拍（当前所处节拍·拍名）"
    cur = str(line["当前拍"]).strip()
    if cur not in BEAT_ENUM:
        return f"当前拍 '{cur}' 非法（枚举: {'/'.join(BEAT_ENUM)}）"
    seq = line.get("拍序")
    if not isinstance(seq, list) or not seq:
        return "拍序 必须是非空 yaml 列表（元素: 拍名/空间/时间/事件）"
    names = []
    for b in seq:
        if not isinstance(b, dict):
            return "拍序 元素必须是映射（拍名/空间/时间/事件）"
        nm = str(b.get("拍名", "")).strip()
        if nm not in BEAT_ENUM:
            return f"拍名 '{nm}' 非法（枚举: {'/'.join(BEAT_ENUM)}）"
        if nm in names:
            return f"拍名 '{nm}' 重复"
        names.append(nm)
        ev = str(b.get("事件", "")).strip()
        if ev and "→" not in ev:
            return f"拍名 '{nm}' 的事件未含 '→'（事件=双方互动·主谓宾齐全·禁止独角戏）"
    if cur not in names:
        return f"当前拍 '{cur}' 不在拍序拍名中（{names}）"
    return None


def _storyline_landing_error(line) -> str | None:
    """顶点落点 戏剧目标声明校验（add/rewrite 时硬性·当场反馈）：拍序含顶点拍但 顶点落点 缺失
    或 角色/内部变量 为空 → 错误描述；预期形态（可选）须为四形态之一。
    拍序无顶点拍 → 放行（无顶点线无需戏剧目标；出线核验 _check_climax_exit 兜底）。"""
    for b in line.get("拍序") or []:
        if not isinstance(b, dict) or str(b.get("拍名", "") or "").strip() != "顶点":
            continue
        landing = b.get("顶点落点")
        if not isinstance(landing, dict):
            return "顶点拍缺 顶点落点（戏剧目标声明·建线/换线时预填——角色/内部变量·可选 预期形态（四形态之一））"
        if not str(landing.get("角色", "") or "").strip():
            return "顶点落点 缺 角色（爆破承受者——冲突双方皆可·结果不可预估·任一方达成即落地）"
        if not str(landing.get("内部变量", "") or "").strip():
            return "顶点落点 缺 内部变量（戏剧目标——哪样东西碎掉·爆破点库挑最痛）"
        form = str(landing.get("预期形态", "") or "").strip()
        if form and form not in CLIMAX_FORMS:
            return f"顶点落点.预期形态 '{form}' 非法（四形态: {'/'.join(CLIMAX_FORMS)}）"
        break
    return None


def _next_storyline_id(beats: dict) -> str:
    """下一个事件线编号（{N}·数字递增）。"""
    max_n = 0
    for k in beats:
        m = re.match(r"^(\d+)$", str(k))
        if m:
            max_n = max(max_n, int(m.group(1)))
    return str(max_n + 1)


def _empty_beat_warnings(line) -> list[str]:
    """检查事件线拍序：空间/时间/事件 任一为空的拍 → 警告列表。
    建线应预设完整拍序内容（拍=规划蓝图）；推进/换线后空拍仍在 = 现实与该拍无法承接（需 rewrite 补填或明确留空）。"""
    warns = []
    seq = line.get("拍序") or []
    if not isinstance(seq, list):
        return warns
    for b in seq:
        if not isinstance(b, dict):
            continue
        nm = str(b.get("拍名", "")).strip()
        missing = [f for f in ("空间", "时间", "事件") if not str(b.get(f, "")).strip()]
        if missing:
            warns.append(f"拍 '{nm}' 内容不完整（缺: {'/'.join(missing)}）——建线应预设完整拍序·现实与空拍无法承接·需 rewrite 补填")
    return warns


def _warn_empty_beats(n: str, line) -> None:
    """对单条事件线打印空拍警告（add/advance/rewrite 后调用·软性不拦截）。"""
    for w in _empty_beat_warnings(line):
        print(f"[WARN] {BEAT_TOP_KEY} 事件线 {n} {w}", file=sys.stderr)


def cmd_beatsheet(world_dir: Path, extra: list[str], stdin_text: str | None = None):
    """节拍表维护（conflicts.yaml 顶层 节拍表）——脚本唯一入口·LLM 不直接改。
    结构/枚举校验后机械写入，保证格式正确。stdin_text: write-raw 自动执行时传入
    add/rewrite 的事件线 YAML（None=从 sys.stdin 读·CLI 手动调用）。"""
    fp = world_dir / "conflicts.yaml"
    if not fp.exists():
        print("[ERR] conflicts.yaml 不存在", file=sys.stderr)
        sys.exit(1)
    data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}
    beats = data.get(BEAT_TOP_KEY)
    if beats is None:
        beats = {}
    if not isinstance(beats, dict):
        print(f"[ERR] {BEAT_TOP_KEY} 已存在但非映射结构: {type(beats).__name__}", file=sys.stderr)
        sys.exit(1)

    if not extra:
        _beatsheet_usage()
        sys.exit(1)
    sub = extra[0]
    if sub in ("--help", "-h"):
        _beatsheet_usage()
        sys.exit(0)

    if sub == "show":
        n = extra[1] if len(extra) > 1 else None
        if n is not None:
            line = beats.get(n)
            if line is None:
                print(f"[WARN] {BEAT_TOP_KEY} 无事件线 {n}", file=sys.stderr)
                sys.exit(1)
            out = {n: line}
        else:
            out = beats
        yaml.dump(out, sys.stdout, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)
        return

    if sub == "stay":
        if len(extra) < 2:
            _beatsheet_usage()
            sys.exit(1)
        n = extra[1]
        if n not in beats:
            print(f"[ERR] {BEAT_TOP_KEY} 无事件线 {n}", file=sys.stderr)
            sys.exit(1)
        line = beats[n]
        if not isinstance(line, dict) or not str(line.get("当前拍", "") or "").strip():
            print(f"[ERR] 事件线 {n} 无当前拍——停留需已有当前拍（先 add/rewrite 建线）", file=sys.stderr)
            sys.exit(1)
        print(f"[OK] {BEAT_TOP_KEY} 事件线 {n} 已更新（stay·停留当前拍·下轮继续）", file=sys.stderr)
        return

    if sub == "add":
        line = yaml.safe_load(stdin_text if stdin_text is not None else sys.stdin)
        err = _validate_storyline(line) or _storyline_landing_error(line)
        if err:
            print(f"[ERR] 事件线结构校验失败: {err}", file=sys.stderr)
            sys.exit(1)
        n = _next_storyline_id(beats)
        beats[n] = line
        if str(line.get("当前拍", "") or "").strip() == "顶点":
            _snapshot_climax_baseline(line, world_dir, n)
        data[BEAT_TOP_KEY] = beats
        write_yaml(fp, data)
        print(f"[OK] {BEAT_TOP_KEY} 事件线 {n} 已建（{sub}）")
        _warn_empty_beats(n, line)
        return

    if sub in ("advance", "clear", "rewrite"):
        if len(extra) < 2:
            _beatsheet_usage()
            sys.exit(1)
        n = extra[1]
        if n not in beats:
            print(f"[ERR] {BEAT_TOP_KEY} 无事件线 {n}", file=sys.stderr)
            sys.exit(1)
        line = beats[n]
        if sub == "advance":
            if len(extra) < 3:
                _beatsheet_usage()
                sys.exit(1)
            target = extra[2]
            names = [str(b.get("拍名", "")) for b in line.get("拍序", []) if isinstance(b, dict)]
            if target not in names:
                print(f"[ERR] 拍名 '{target}' 不在事件线 {n} 的拍序中（拍序拍名: {names}）", file=sys.stderr)
                sys.exit(1)
            cur = str(line.get("当前拍", ""))
            if cur and cur in names and names.index(cur) > names.index(target):
                print(f"[ERR] 当前拍回退（{cur}→{target}）不允许——节拍只向前推进", file=sys.stderr)
                sys.exit(1)
            line["当前拍"] = target
        elif sub == "clear":
            cur = str(line.get("当前拍", ""))
            if cur != "余波":
                print(f"[WARN] 当前拍='{cur}' 非余波——清线按生命周期第 3 步（现实与当前拍不承接·默认 clear）执行·语义由 D12 审计把关", file=sys.stderr)
            line = {}
        elif sub == "rewrite":
            newline = yaml.safe_load(stdin_text if stdin_text is not None else sys.stdin)
            err = _validate_storyline(newline) or _storyline_landing_error(newline)
            if err:
                print(f"[ERR] 事件线结构校验失败: {err}", file=sys.stderr)
                sys.exit(1)
            line = newline
        beats[n] = line
        if sub in ("add", "advance", "rewrite") and isinstance(line, dict) and str(line.get("当前拍", "") or "").strip() == "顶点":
            _snapshot_climax_baseline(line, world_dir, n)
        data[BEAT_TOP_KEY] = beats
        write_yaml(fp, data)
        print(f"[OK] {BEAT_TOP_KEY} 事件线 {n} 已更新（{sub}）")
        if sub in ("advance", "rewrite"):
            _warn_empty_beats(n, line)
        return

    _beatsheet_usage()
    sys.exit(1)


def cmd_tmp_clean(world_dir: Path):
    """清理世界临时文件目录（worlds/{世界名}/tmp/）——过程临时文件（批次/叙事草稿）用后即删；
    跨会话恢复时由加载序列调用。删除整个目录（下次写入可再生），不存在则提示无需清理。"""
    tmp_dir = world_dir / "tmp"
    if not tmp_dir.exists():
        print("[OK] tmp 目录不存在·无需清理")
        return
    n = sum(1 for _ in tmp_dir.rglob("*"))
    shutil.rmtree(tmp_dir)
    print(f"[OK] tmp 清理完成: 删除 {n} 个文件（{world_dir.name}/tmp/）")


def cmd_reset_cycle(world_dir: Path, world_name: str, force: bool = False):
    """循环世界周期重置（循环日终/到期点）——机械重置全员·登记重置记录·重建周期倒计时。
    触发：write-raw audit ④b 顶回后执行（或恢复序列 4.6②）。脚本做机械部分：
    反应轨迹清空 / 记忆锚点按自主性档位压缩（脚本全清·漂移/觉醒压缩+输出保留候选·变质保留）/
    状态字段回基线占位 / 压力防御回默认（觉醒/变质保留防御崩解）/ 人际动态与决策清空（LLM 按 LOOPS 补写）/
    信念演化与自主性保留 / 自动存档（snap.sh save _before_）/ 登记重置记录 / 重建周期倒计时（到期时刻+1 周期）。
    LLM 只做：保留候选确认/微调 + 状态字段按 LOOPS 补写 + CT 节拍核查 + 重置叙事。"""
    ws_fp = world_dir / "world_state.yaml"
    if not ws_fp.exists():
        print("[ERR] world_state.yaml 不存在", file=sys.stderr)
        return 1
    ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8")) or {}
    cur_time = str(ws.get("时间", {}).get("具体时间", "") or "").strip()
    cur_round = str(ws.get("轮次", "0") or "0").strip()
    cur_day = None
    _, _m = _parse_world_time(cur_time)
    if _m is None:
        print(f"[ERR] 当前时间无法解析（需 '第N日 HH:MM' 格式）: '{cur_time}'", file=sys.stderr)
        return 1
    dm, _ = _parse_world_time(cur_time)
    cur_day = dm

    # 定位周期重置倒计时（含 到期时刻）
    cds = ws.get("外部倒计时") or {}
    cd_id, cd_spec = None, None
    if isinstance(cds, dict):
        for cid, cspec in cds.items():
            if isinstance(cspec, dict) and str(cspec.get("到期时刻", "") or "").strip():
                cd_id, cd_spec = cid, cspec
                break
    if cd_id is None:
        print("[WARN] 未找到含 到期时刻 的周期倒计时——重置仍执行（周期倒计时登记见 session_recovery.md §4.6）", file=sys.stderr)

    # 0. 自动存档（可回滚）
    import subprocess
    snap_script = Path(__file__).parent / "snap.sh"
    snap_name = f"_before_reset_cycle_{world_name}_{_ts()}"
    try:
        r = subprocess.run(["sh", str(snap_script), world_name, "save", snap_name],
                           capture_output=True, text=True, timeout=120)
        print(f"[OK] 自动存档: {snap_name}（{r.stdout.strip()[:200] if r.stdout.strip() else 'snap.sh 输出为空'}）")
    except Exception as e:
        print(f"[WARN] 自动存档失败（继续执行）: {e}", file=sys.stderr)

    # 机械重置全员（含焦外——机制执行全员化）
    candidates = []          # (角色, 档位, 被压缩条目) 保留候选
    key_anchor_kw = ("承诺", "命名", "关系转折", "决定", "记得", "承诺", "他/她")
    for cfp in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            cdata = yaml.safe_load(cfp.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"[WARN] {cfp.name} 解析失败·跳过: {e}", file=sys.stderr)
            continue
        # 豁免判定（硬性）：自主性 字段仅循环角色有（模板语义）——外部者/管理者（Guest/Ford/Stubbs 等）
        #   无此字段 → 豁免周期重置（loop_machinery §4 豁免）。事件型角色（死亡即回收·如 Teddy/Hector）
        #   = 循环角色（有自主性字段）——周期时刻若活着度过当日，同样按「次日清晨仍按循环日终重置」执行，不豁免
        if "自主性" not in cdata or not str(cdata.get("自主性", "") or "").strip():
            print(f"[SKIP] {cfp.stem}: 无自主性字段（外部者/管理者·豁免周期重置）")
            continue
        lvl = str(cdata.get("自主性", "") or "").strip()
        old_mem = cdata.get("记忆锚点")
        # 记忆锚点按档位压缩
        if lvl == "脚本":
            new_mem = []
        elif lvl == "变质":
            new_mem = old_mem  # 几乎全保留（时间位抹除交给戏剧家）
        else:  # 漂移/觉醒：压缩为碎片 + 保留候选清单
            kept, removed = [], []
            if isinstance(old_mem, list):
                for it in old_mem:
                    if not isinstance(it, dict):
                        removed.append(it)
                        continue
                    content = str(it.get("内容", ""))
                    ts = str(it.get("时间", ""))
                    mark = str(it.get("标记", ""))
                    if "碎片" in content or "碎片" in ts or "可揭示" in mark:
                        kept.append(it)
                    elif lvl == "觉醒" and any(k in content for k in key_anchor_kw):
                        kept.append(it)
                    else:
                        removed.append(it)
                if kept and not any("碎片" in str(k.get("时间", "")) or "碎片" in str(k.get("内容", "")) for k in kept):
                    last = kept[-1] if kept else None
                    kept = kept[-1:]
                if not kept and removed:
                    last = removed[-1]
                    last = dict(last) if isinstance(last, dict) else {"内容": str(last)}
                    last["时间"] = "碎片"
                    kept = [last]
            elif old_mem:
                removed = [old_mem]
                last = dict(old_mem) if isinstance(old_mem, dict) else {"内容": str(old_mem)}
                last["时间"] = "碎片"
                kept = [last]
            new_mem = kept
            for it in removed:
                candidates.append((cfp.stem, lvl, str(it)[:120]))
        cdata["记忆锚点"] = new_mem if isinstance(new_mem, list) else ([] if not new_mem else [new_mem])
        # 反应轨迹清空（联动表·新循环从零累积）
        cdata["反应轨迹"] = ""
        # 状态字段回基线占位（LLM 按 LOOPS 补写——脚本不解析 LOOPS 自然语言）
        cdata["核心状态"] = ""
        cdata["情绪"] = ""
        cdata["决策状态"] = ""
        cdata["人际动态"] = ""
        # 压力/防御回默认；觉醒/变质保留防御崩解状态
        cdata["压力水平"] = "低"
        if lvl in ("觉醒", "变质"):
            cur_def = str(cdata.get("防御有效性", "") or "").strip()
            cdata["防御有效性"] = cur_def if cur_def == "已彻底崩解" else "有效"
        else:
            cdata["防御有效性"] = "有效"
        # 防御形态/崩溃表现：脚本/漂移=清空回档案默认；觉醒/变质=保留（联动表·重构后的新防御随自我连续保留）
        if lvl in ("脚本", "漂移"):
            cdata["防御形态"] = ""
            cdata["崩溃表现"] = ""
        # 偏离登记全档位清空（联动表·机械计数事实·新循环从零累积·validate 3b 计数源重置）
        cdata["偏离登记"] = []
        # 已知地点：脚本=回基线（清空·LLM 按 LOOPS 补常驻）；漂移/觉醒/变质=保留（保守不丢）
        if lvl == "脚本":
            cdata["已知地点"] = []
        # 信念演化/自主性/名字 保留（联动表）
        with open(cfp, "w", encoding="utf-8", newline="") as f:
            yaml.safe_dump(cdata, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        print(f"[OK] 重置 {cfp.stem}: 档位={lvl} · 记忆锚点→{len(new_mem) if isinstance(new_mem, list) else 1} 条 · 状态字段回基线")

    # 登记重置记录（{档位/轮次/重置日期}）
    reset_rec = ws.get("重置记录") or {}
    if not isinstance(reset_rec, dict):
        reset_rec = {}
    for cfp in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            cdata = yaml.safe_load(cfp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        # 豁免者（无自主性字段·外部者/管理者）不登记重置记录
        if "自主性" not in cdata or not str(cdata.get("自主性", "") or "").strip():
            continue
        name = cfp.stem[len(CHAR_STATE_PREFIX):-len("_state")]
        lvl = str(cdata.get("自主性", "") or "").strip()
        reset_rec[name] = {"档位": lvl, "轮次": cur_round, "重置日期": f"第{cur_day}日"}
    ws["重置记录"] = reset_rec

    # 重建周期倒计时（到期时刻 +1 周期·同时刻）
    if cd_id is not None:
        old_due = str(cd_spec.get("到期时刻", "") or "").strip()
        dd, dm = _parse_world_time(old_due)
        if dd is not None:
            nd = dd + 1
            new_due = f"第{nd}日 {old_due.split('日 ')[-1] if '日 ' in old_due else '07:00'}"
            cd_spec["到期时刻"] = new_due
            cd_spec["剩余时间"] = "1周期"
            ws.setdefault("外部倒计时", {})[cd_id] = cd_spec
            print(f"[OK] 周期倒计时 {cd_id} 重建: 到期时刻 {old_due} → {new_due}")
    with open(ws_fp, "w", encoding="utf-8", newline="") as f:
        yaml.safe_dump(ws, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # 保留候选清单 + 提示
    print("\n【重置完成】")
    print(f"  时间 {cur_time} · 轮次 {cur_round} · 重置记录 {len(reset_rec)} 角色")
    print("【LLM 后续动作（非脚本）】")
    print("  1. 状态字段（核心状态/情绪/决策状态/人际动态/已知地点）按 LOOPS.md 当前时段补写")
    print("  2. 觉醒/漂移档保留候选确认——压缩掉的条目：")
    if candidates:
        for role, lvl, content in candidates[:20]:
            print(f"    · {role}（{lvl}）: {content}")
    else:
        print("    （无压缩条目）")
    print("  3. CT 节拍核查（挂载 CT 是否依赖被抹记忆）· 重置叙事（醒来·新一天帧）")
    return 0


def _ts():
    import datetime
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


# ── CLI ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="WorldSim 批量状态管理 V2")
    parser.add_argument("world", help="世界名")
    parser.add_argument("action", choices=["read", "write", "write-raw", "append-raw", "delete", "convert", "validate", "audit", "grep", "scan", "gate", "beatsheet", "reset-cycle", "tmp-clean"])
    parser.add_argument("--files", help="read 时限定文件 key 列表，逗号分隔")
    parser.add_argument("--full", action="store_true", help="write 时全量覆写")
    parser.add_argument("--batch", action="store_true", help="write-raw/append-raw 批量模式：stdin 为 ###FILE/###KEY/###APPEND 记录格式（⚠非幂等：APPEND 重复执行会重复追加·同一批次只执行一次·验证用 read/validate/--dry-run）")
    parser.add_argument("--dry-run", action="store_true", help="write-raw/append-raw 预演：解析+audit+对比磁盘差异，不落盘（重跑批次前先对比）")
    parser.add_argument("--check", action="store_true", help="gate 代码化核验模式：从 stdin 读 change set（dramatist）或叙事（writer），运行可代码化检查，不合格 exit 1")
    parser.add_argument("--live", action="store_true", help="scan 仅当前文件（排除历史轮转 narrative.*.md 与 archive）")
    parser.add_argument("extra", nargs="*", help="write-raw/append-raw 的额外参数: <文件key> <YAML键路径> [内容]")
    # beatsheet 子命令 help 直达 cmd_beatsheet——argparse 内建 --help 会拦截并打印全局 help（action choices 一行）
    argv = sys.argv[1:]
    if len(argv) >= 3 and argv[1] == "beatsheet" and argv[2] in ("--help", "-h"):
        cmd_beatsheet(get_world_dir(argv[0]), ["--help"])
        sys.exit(0)
    args = parser.parse_args()

    world_dir = get_world_dir(args.world)

    if args.action == "read":
        files_filter = args.files.split(",") if args.files else None
        cmd_read(world_dir, files_filter)
    elif args.action == "write":
        cmd_write(world_dir, full_replace=args.full)
    elif args.action == "write-raw":
        cmd_write_raw(world_dir, args.extra, batch=args.batch, dry_run=args.dry_run)
    elif args.action == "append-raw":
        cmd_write_raw(world_dir, args.extra, batch=args.batch, append_mode=True, dry_run=args.dry_run)
    elif args.action == "delete":
        cmd_delete(world_dir, args.extra)
    elif args.action == "convert":
        cmd_convert(world_dir)
    elif args.action == "validate":
        cmd_validate(world_dir)
    elif args.action == "audit":
        cmd_audit(world_dir)
    elif args.action == "grep":
        keyword = " ".join(args.extra)
        cmd_grep(world_dir, keyword)
    elif args.action == "scan":
        cmd_scan(world_dir, args.extra, live_only=args.live)
    elif args.action == "gate":
        cmd_gate(world_dir, args.extra, check_mode=args.check)
    elif args.action == "beatsheet":
        cmd_beatsheet(world_dir, args.extra)
    elif args.action == "reset-cycle":
        force = any(x == "--force" for x in args.extra)
        sys.exit(cmd_reset_cycle(world_dir, args.world, force=force))
    elif args.action == "tmp-clean":
        cmd_tmp_clean(world_dir)

if __name__ == "__main__":
    main()
