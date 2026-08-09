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
  worldctl.py <世界名> convert            ← 将 .md 状态文件转为 .yaml（按章节存 block scalar）
  worldctl.py <世界名> validate           ← 验证 YAML 格式
  worldctl.py <世界名> audit             ← 校验 stdin 的 change set 草案（###FILE/###KEY 格式），不落盘
                                         （语义不变量：代价行/载体/记忆上限/轮次单调/落点一致）

文件格式约定:
  - 所有状态文件使用 .yaml 扩展名
  - 每个顶级章节用 YAML 映射键存储，内容为 block scalar (|)
  - 结构化的表（如 conflicts）用 mapping of mappings，键为项目ID
  - 角色状态用自由键值对 + 多行 prose 值
  
核心优化：read = 1 次 exec 获取所有状态；write = 1 次 exec 更新所有变更。
"""
import sys, os, yaml, re, shutil, argparse
from pathlib import Path

SKILL_DIR = Path(os.environ.get("WORLDSIM_DIR", Path(__file__).resolve().parent.parent))
CHAR_STATE_PREFIX = "CHAR_"
CHAR_STATE_SUFFIX = "_state.yaml"
REACTION_TRAJECTORY_WINDOW = 5  # 反应轨迹保留最近 N 轮——APPEND 后超窗自动裁剪最旧块（脚本执行·LLM 每轮只需 APPEND 本轮）

# ── 文件发现 ──────────────────────────────────────────────────────
def get_world_dir(world: str) -> Path:
    wd = SKILL_DIR / "worlds" / world
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
    return files

# ── CHAR key 命名归一化 ──────────────────────────────────────────
def resolve_char_file(existing: dict, key: str, world_dir: Path):
    """解析 CHAR_* 写入目标。已存在→直接映射；不存在→检查空格/下划线互换及缺失 _state 后缀的相似 key，
    命中则映射到已有文件并警告（杜绝同一角色产生两份状态文件）；再试唯一包含匹配（写错全名如
    CHAR_Maeve_state → CHAR_Maeve Millay_state 自动纠正）；否则→按 key 新建。
    防御: key 若误带 .yaml 扩展名（如 CHAR_Guest_state.yaml）→ 剥离后归一化，禁止生成 .yaml.yaml 重复文件。"""
    if key.endswith(".yaml"):
        print(f"[WARN] key '{key}' 误带 .yaml 扩展名——已剥离为 '{key[:-5]}'（防止生成 {key}.yaml 重复文件）", file=sys.stderr)
        key = key[:-5]
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
        # 唯一包含匹配：写错全名（缺字/多字/简写）时，扫描 CHAR_*.md 档案做包含判断——唯一命中=自动纠正
        stem2 = key[len(CHAR_STATE_PREFIX):]
        if stem2.endswith("_state"):
            stem2 = stem2[:-len("_state")]
        if stem2.strip():
            md_hits = []
            for fp in sorted(world_dir.glob("CHAR_*.md")):
                full = fp.stem[len("CHAR_"):]
                if stem2 in full or full in stem2:
                    md_hits.append(full)
            if len(md_hits) == 1:
                target = CHAR_STATE_PREFIX + md_hits[0] + "_state"
                if target in existing:
                    return existing[target], f"[WARN] key '{key}' 与已有档案 '{md_hits[0]}' 唯一包含匹配——已自动映射到 {existing[target].name}（全名写错自动纠正）"
        return world_dir / f"{key}.yaml", None
    return None, None

def resolve_file_key(existing: dict, file_key: str):
    """FILE key 归一化（兼容性兜底）：直接命中注册表 → 剥离路径/扩展名后再命中 → 未命中返回 None。
    允许 ###FILE: off_focus/pending_actions 这类直觉路径写法落盘，不必死记注册表 key。"""
    if file_key in existing:
        return file_key
    if file_key:
        stem = Path(file_key).stem  # off_focus/pending_actions.yaml → pending_actions
        if stem in existing:
            return stem
    return None

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
    with open(path, "w") as f:
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
            # 兼容：顶层键=某文件内的顶层键（裸内容写法，如「已探索区域: …」）→ 自动定位文件
            for fkey, fp in existing.items():
                try:
                    fdata = yaml.safe_load(fp.read_text()) or {}
                except Exception:
                    continue
                if key in fdata:
                    filepath = fp
                    note = f"[兼容] 顶层键 '{key}' 自动定位到文件 {fkey}"
                    break
        if filepath is None:
            print(
                f"[WARN] 未知 key: {key}, 跳过（--full 顶层键应为文件 key，如 world_map / conflicts / CHAR_Guest_state / pending_actions；"
                f"值=该文件完整内容。也可直接写文件顶层键自动定位）",
                file=sys.stderr,
            )
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
ANCHOR_LIMIT_ENTRY = 150

def strip_wrapping_quotes(content: str) -> str:
    """剥除 YAML 风格成对包裹引号（'...' / "..."）——change set 内容允许带引号书写。
    只剥最外层一对；内部不处理转义；不带引号则原样返回；剥后为空返回空串（由调用方按空值处理）。"""
    if len(content) >= 2 and content[0] in ("'", '"') and content[-1] == content[0]:
        return content[1:-1]
    return content


def parse_batch_entries(lines):
    """解析 ###FILE/###KEY/###APPEND/###DELETE 行到操作列表。
    返回 (ops, errors)。ops 元素: (kind, file_key, key_path, content, append)
    kind ∈ {"write", "delete"}。空值 KEY 覆盖在此阶段即拒绝。"""
    ops = []
    errors = []
    current_file = None
    current_key = None
    current_append = False
    current_content = []

    def flush():
        nonlocal current_file, current_key, current_append, current_content
        if current_file and current_key:
            content = strip_wrapping_quotes("\n".join(current_content).rstrip("\n"))
            if not current_append and content == "":
                errors.append(f"空值覆盖已拒绝: {current_file}.{current_key}（###KEY: 值不能为空；追加请用 ###APPEND:，覆盖需带完整值）")
            else:
                ops.append(("write", current_file, current_key, content, current_append))
        current_key = None
        current_append = False
        current_content = []

    for line in lines:
        if line.startswith("###FILE:"):
            flush()
            current_file = line[8:].strip()
        elif line.startswith("###KEY:"):
            flush()
            current_key = line[7:].strip()
            current_append = False
        elif line.startswith("###APPEND:"):
            flush()
            current_key = line[10:].strip()
            current_append = True
        elif line.startswith("###DELETE:"):
            flush()
            rest = line[10:].strip()
            parts = rest.split(None, 1)
            if len(parts) == 2:
                # 空格分隔：###DELETE: <文件key> <YAML键路径>
                ops.append(("delete", parts[0], parts[1], "", False))
            else:
                # 点路径兼容（与 ###KEY: 风格统一）：###DELETE: <文件key>.<YAML键路径>
                # 文件 key 均不含点（world_state/conflicts/CHAR_*_state/…），首段安全拆分
                dots = rest.split(".", 1)
                if len(dots) == 2 and dots[0] and dots[1]:
                    ops.append(("delete", dots[0], dots[1], "", False))
                else:
                    errors.append("###DELETE 格式: ###DELETE: <文件key> <YAML键路径>（或 <文件key>.<YAML键路径>）")
        elif line.startswith("###META:"):
            # 静默自查锚点（2026-08-09）：批次内元数据行——解析忽略，不落盘、不产生 ops（如「###META: 压力扫描 人际✓/…」）
            flush()
            continue
        elif current_file and current_key:
            # 内容行内嵌标记检测（防拼接 bug）：行内出现 ###FILE:/###KEY:/###APPEND: 但不在行首 = 上一字段内容被拼接
            for marker in ("###FILE:", "###KEY:", "###APPEND:", "###DELETE:"):
                if marker in line and not line.lstrip().startswith(marker):
                    errors.append(
                        f"内容行内嵌标记 {marker.strip(':')}（行首无标记）：'{line[:60]}'——疑似上一字段内容与标记拼接（如缺少换行）。"
                        f"位置: {current_file}.{current_key}"
                    )
                    break
            current_content.append(line)
    flush()
    return ops, errors


def check_batch(ops, world_dir):
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

    # 批次整体必含项标记（完整推进轮·查询轮豁免）
    has_ct_op = False
    has_ws_time = False
    has_ws_round = False
    has_ws_summary = False
    has_scene_timeline = False

    for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
        if kind != "write":
            continue
        key_path = key_path_str.split(".")

        # conflicts.yaml 路径归一化：去掉多余的 `conflicts.` 根前缀
        if file_key == "conflicts" and key_path and key_path[0] == "conflicts":
            key_path = key_path[1:]

        # 批次整体必含项标记（在归一化之后判断——带 conflicts. 前缀的键路径也计入）
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

        # ③ 记忆锚点：单条 ≤150 / 写入后总量 ≤3000（软性警告·不拦截——内容质量类，validate 汇总）
        if file_key.startswith(CHAR_STATE_PREFIX) and key_path == ["记忆锚点"]:
            filepath, _ = resolve_char_file(existing, file_key, world_dir)
            if append:
                entries = re.split(r"\n\s*(?:·\s*)?(?=\[)", content)
                for ent in entries:
                    ent = ent.strip()
                    if len(ent) > ANCHOR_LIMIT_ENTRY:
                        soft.append((idx, f"{file_key}.记忆锚点: 新条目 {len(ent)} 字 > {ANCHOR_LIMIT_ENTRY} 上限（应压为事实一句+定性一句）"))
                total = len(content)
                if filepath and filepath.exists():
                    try:
                        old = (yaml.safe_load(filepath.read_text()) or {}).get("记忆锚点", "")
                        if isinstance(old, str) and old:
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

        # ⑤ scene_state 落点：必须有焦点场景目录（防止写错场景）
        if file_key == "scene_state" and scene_dir is None:
            hard.append((idx, "scene_state 落点错误: 无法定位当前焦点场景目录——先确认 world_state.焦点场景 后再写入"))

        # ⑥ 时间线事件写语义提示（软性·不拦截）：world_state.时间线.*.事件 默认 APPEND 追加；
        #    ###KEY 覆盖仅用于 validate 告警后的压缩维护（读旧值+压缩合并+补新）
        if (file_key == "world_state" and len(key_path) >= 3
                and key_path[0] == "时间线" and key_path[-1] == "事件" and not append):
            soft.append((idx, f"{file_key}.{key_path_str}: 时间线事件默认 ###APPEND 追加；###KEY 覆盖仅在 validate 告警后的压缩维护时使用（读旧值+压缩合并+补新）"))

        # ⑥b 时间线事件内部禁「·」（硬性顶回——2026-08-06 实测：validate 按「·」计数转折点，
        #     事件内部用「·」=每个细节都被误计为转折点=必然超限告警；内部请用「，」/「→」分隔细节）
        if (file_key == "world_state" and len(key_path) >= 3
                and key_path[0] == "时间线" and key_path[-1] == "事件"):
            for ln in content.splitlines():
                line = ln.strip()
                if not line:
                    continue
                inner = line[2:] if line.startswith("· ") else line
                if "·" in inner:
                    hard.append((idx, f"{file_key}.{key_path_str}: 时间线事件内部禁「·」（validate 按「·」计数转折点——仅行首「· 」算转折点，内部请用「，」/「→」分隔细节）"))
                    break

        # ⑦ world_state 键表外字段（软性警告——无语义定义的漂移字段）
        if file_key == "world_state" and key_path:
            WS_TOP_KEYS = {"焦点场景", "轮次", "时间", "地点", "外部倒计时", "全局标记", "时间线", "重置记录", "叙事约定", "输出模式"}
            WS_TIME_KEYS = {"基准时间", "具体时间", "时间流速比", "前情描述"}
            WS_LOC_KEYS = {"当前区域", "已探索区域"}
            if key_path[0] not in WS_TOP_KEYS:
                soft.append((idx, f"world_state.{key_path_str}: 未知顶层键（键表: 焦点场景/轮次/时间/地点/外部倒计时/全局标记/时间线/重置记录/叙事约定/输出模式）"))
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
                CHAR_STATE_KEYS = {"自主性", "位置", "核心状态", "情绪", "压力水平", "防御有效性", "偏离登记", "人际动态", "决策状态", "信念演化", "记忆锚点", "反应轨迹", "名字"}
                if key_path[0] not in CHAR_STATE_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: CHAR_state 顶层键必须在键表内（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))
            elif file_key == "scene_state":
                SCENE_STATE_KEYS = {"核心状态", "场景时间线", "物理锚点", "道具", "关键场景信息", "出场角色摘要"}
                if key_path[0] not in SCENE_STATE_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: scene_state 顶层键必须在键表内（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))

        # ⑬b 反应轨迹覆盖写保护（硬性——防 change set 漏写历史段把磁盘旧值覆盖成旧内容）
        # 覆盖写必须保留磁盘旧值的首末轮次标记；丢失=顶回。推荐改用 ###APPEND: 反应轨迹 每轮只追加本轮。
        if (file_key.startswith(CHAR_STATE_PREFIX) and key_path == ["反应轨迹"] and not append):
            filepath_rt, _ = resolve_char_file(existing, file_key, world_dir)
            if filepath_rt and filepath_rt.exists():
                try:
                    old_rt = (yaml.safe_load(filepath_rt.read_text()) or {}).get("反应轨迹", "")
                except Exception:
                    old_rt = ""
                if isinstance(old_rt, str) and old_rt.strip():
                    marks = re.findall(r"第(\d+)轮", old_rt)
                    if marks:
                        first_mark = f"第{marks[0]}轮"
                        last_mark = f"第{marks[-1]}轮"
                        missing = [m for m in (first_mark, last_mark) if m not in content]
                        if missing:
                            hard.append((idx, f"{file_key}.反应轨迹: 覆盖写新内容缺少磁盘旧值轮次标记 {'/'.join(missing)}——疑似漏写历史轨迹（覆盖写将丢失旧值）；应从磁盘读旧值+追加本轮后整体覆盖，或改用 ###APPEND: 反应轨迹 只追加本轮"))

    # ⑩⑪⑫ 批次整体必含项（硬性·完整推进轮——含 world_state.轮次 即视为完整推进轮·查询轮豁免；批次为空不检查）
    # ⑩⑪⑫ 批次整体必含项（硬性·完整推进轮——含 world_state.轮次 + 至少一个其他推进字段 即视为完整推进轮·查询轮/纯轮次维护豁免）
    # 判定: 含轮次但批次只有轮次一条（无其他推进字段）= 纯轮次维护（数据修正），豁免
    has_other = has_ct_op or has_ws_time or has_ws_summary or has_scene_timeline
    if has_ws_round and has_other:
        missing = []
        if not has_ct_op:
            missing.append("≥1 条 CT 推进/注册（conflicts.CT-XX）——本轮没做冲突决策=没推进")
        if not has_ws_time:
            missing.append("world_state.时间.具体时间 推进")
        if not has_ws_summary:
            missing.append("world_state.时间.前情描述（≤100字状态短语）")
        if not has_scene_timeline:
            missing.append("scene_state.场景时间线 追加")
        if missing:
            hard.append((-1, "完整推进轮（含轮次更新）缺少必含项: " + "；".join(missing) + "——先补全决策/状态字段再写入"))
    elif ops:
        # 查询轮（无轮次更新）仍提示软性：若含部分推进字段但漏了轮次，多半是漏写而非查询轮
        if has_ct_op or has_ws_time or has_scene_timeline:
            soft.append((-1, "批次含推进字段但缺 world_state.轮次——若为完整推进轮请补轮次；若确为查询轮（/status 等）可忽略"))

    # ⑭ 跨叙事提醒（软性——CROSS_NARRATIVES.md 存在时，完整推进轮应核对深匹配）
    if (world_dir / "CROSS_NARRATIVES.md").exists() and has_ct_op:
        soft.append((-1, "CROSS_NARRATIVES.md 存在——完整推进轮应核对跨叙事深匹配（SKILL ④: 浅匹配=登记不操作；深匹配=注入可写行为偏移；激活=注册新 CT；每轮最多激活一条·同线间隔≥3轮）"))
    # ⑮ 行为偏移落地提醒（软性——change set 含「行为偏移」标记 → 叙事阶段必须落地）
    if any("行为偏移" in content for _, _, _, content, _ in ops):
        soft.append((-1, "change set 含「行为偏移」标记——叙事阶段必须如实落地该偏移（W3 核验·可观察行为·不解释来源）"))

    return hard, soft


def cmd_audit(world_dir):
    """audit: 校验 stdin 的 change set 草案（###FILE/###KEY/###APPEND 格式），不落盘。
    硬性违规 → 列出全部并 exit 1（草案不合格）；仅软性警告 → 打印警告，exit 0（可写入）。"""
    raw_stdin = sys.stdin.buffer.read().decode("utf-8")
    ops, parse_errors = parse_batch_entries(raw_stdin.split("\n"))
    hard, soft = check_batch(ops, world_dir)
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
            if isinstance(mem, str) and mem.strip():
                if len(mem) > ANCHOR_LIMIT_TOTAL:
                    warnings.append(f"{cfp.name}: 记忆锚点 {len(mem)} 字 > {ANCHOR_LIMIT_TOTAL} 校验线——需按 §记忆淘汰 整理")
                entries = re.split(r"\n\s*(?:·\s*)?(?=\[)", mem)
                over = [e for e in entries if len(e.strip()) > ANCHOR_LIMIT_ENTRY]
                if over:
                    warnings.append(f"{cfp.name}: {len(over)} 条记忆锚点超单条 {ANCHOR_LIMIT_ENTRY} 字上限")
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
                if not re.match(r"^CT-\d{2}$", str(k)):
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

        # FILE key 归一化（兼容性兜底）：off_focus/pending_actions → pending_actions
        resolved_key = resolve_file_key(existing, file_key)
        if resolved_key is not None:
            file_key = resolved_key
        elif file_key.startswith(CHAR_STATE_PREFIX):
            # CHAR_* 容错：变体/唯一包含匹配（写错全名自动纠正·如 CHAR_Maeve_state → CHAR_Maeve Millay_state）
            fp_try, note_try = resolve_char_file(existing, file_key, world_dir)
            if note_try is not None and fp_try is not None and fp_try.stem in existing:
                print(note_try, file=sys.stderr)
                file_key = fp_try.stem
            else:
                print(f"[ERR] 未知文件 key: {file_key}（注册表内可用: {', '.join(sorted(existing))}）", file=sys.stderr)
                return False
        else:
            print(f"[ERR] 未知文件 key: {file_key}（注册表内可用: {', '.join(sorted(existing))}）", file=sys.stderr)
            return False

        filepath, note = resolve_char_file(existing, file_key, world_dir)
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
        if append and leaf in target and isinstance(target[leaf], str) and target[leaf]:
            existing_val = target[leaf]
            # 重复追加检测（硬防护·防同一批次重放/同一内容重复追加）：
            # 批次重放时 content 完全一致，必然作为子串存在于字段值中 → 跳过
            if content.strip() and content.strip() in existing_val:
                print(f"[SKIP] {file_key}.{'.'.join(key_path)} 重复追加已跳过（内容已存在——同一批次只执行一次，禁止重放 write 命令验证）", file=sys.stderr)
                return True
            target[leaf] = existing_val.rstrip("\n") + "\n" + content
        else:
            target[leaf] = content

        # 反应轨迹窗口自动裁剪（脚本执行·LLM 零操作）：CHAR_*_state.反应轨迹 APPEND 后按 第N轮 切块，
        # 块数 > REACTION_TRAJECTORY_WINDOW 时删除最旧块到窗口内（每轮只写本轮·窗口维护不再需要 LLM 读旧值+全量重写）
        if (file_key.startswith(CHAR_STATE_PREFIX) and key_path == ["反应轨迹"]
                and append and isinstance(target[leaf], str)):
            blocks = re.split(r"(?=^第\d+轮)", target[leaf], flags=re.M)
            blocks = [b for b in blocks if b.strip()]
            if len(blocks) > REACTION_TRAJECTORY_WINDOW:
                dropped = blocks[: len(blocks) - REACTION_TRAJECTORY_WINDOW]
                kept = blocks[-REACTION_TRAJECTORY_WINDOW:]
                drop_marks = []
                for d in dropped:
                    m = re.search(r"第(\d+)轮", d)
                    drop_marks.append(f"第{m.group(1)}轮" if m else "非标条目")
                target[leaf] = "".join(kept).rstrip("\n")
                print(f"[TRIM] {file_key}.反应轨迹 窗口压缩: 删除 {' '.join(drop_marks)}（保留最近 {REACTION_TRAJECTORY_WINDOW} 轮·脚本自动维护·LLM 无需手动窗口重写）", file=sys.stderr)

        write_yaml(filepath, data)
        op = "已追加" if append else "已写入"
        print(f"[OK] {file_key}.{'.'.join(key_path)} {op} ({len(content)}b)")
        return True

    # ── 批量模式 ──
    if batch:
        import io
        raw_stdin = sys.stdin.buffer.read().decode("utf-8")
        lines = raw_stdin.split("\n")

        # 解析 + 语义不变量检查（audit）——字段级违规→单字段顶回；批次级违规（op_index=-1，如完整推进轮缺必含项）→整批拒绝
        ops, parse_errors = parse_batch_entries(lines)
        hard, soft = check_batch(ops, world_dir)
        batch_level = [v for idx, v in hard if idx == -1]
        field_level = [(idx, v) for idx, v in hard if idx != -1]
        blocked = {idx for idx, _ in field_level}
        for e in parse_errors:
            print(f"[AUDIT] 解析失败（该条未写入）: {e}", file=sys.stderr)
        for idx, v in field_level:
            print(f"[AUDIT] 硬性违规——拒绝该字段写入: {v}", file=sys.stderr)
        if batch_level:
            # 批次级违规：整批拒绝，不写任何字段，exit 1（防「缺决策但轮次照写」）
            print("[AUDIT] 批次级硬性违规——整批拒绝（不写任何字段）:", file=sys.stderr)
            for v in batch_level:
                print(f"  - {v}", file=sys.stderr)
            print("[AUDIT] 请补全决策/状态字段后重提批次（查询轮豁免：不含轮次更新的批次不受此限制）", file=sys.stderr)
            sys.exit(1)
        # 软性警告不在此逐条打印（避免噪音）——由 quick_validate_summary 汇总（validate 明细）

        # ── --dry-run 预演：对比磁盘差异，不落盘 ──
        if dry_run:
            scene_dir = get_scene_dir(world_dir)
            existing = discover_files(world_dir, scene_dir)
            unknown_count = 0
            unknown_items = []
            print(f"[DRY-RUN] 预演 {len(ops)} 条操作，{len(blocked)} 条被顶回（不落盘）")
            for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
                if idx in blocked:
                    print(f"  [顶回] {file_key}.{key_path_str}")
                    continue
                if kind == "delete":
                    print(f"  [删除] {file_key}.{key_path_str}")
                    continue
                # FILE key 归一化 + CHAR_* 容错（与正式写入 write_one 对齐）
                resolved_dr = resolve_file_key(existing, file_key)
                if resolved_dr is None and file_key.startswith(CHAR_STATE_PREFIX):
                    fp_try_dr, note_try_dr = resolve_char_file(existing, file_key, world_dir)
                    if note_try_dr is not None and fp_try_dr is not None and fp_try_dr.stem in existing:
                        resolved_dr = fp_try_dr.stem
                        print(f"  [映射] {file_key} → {fp_try_dr.name}（唯一包含/变体匹配·正式写入将自动纠正）")
                if resolved_dr is None:
                    print(f"  [未知文件] {file_key}.{key_path_str}（FILE key 不在注册表——正式写入将被拒）")
                    unknown_count += 1
                    unknown_items.append(f"{file_key}.{key_path_str}")
                    continue
                fp, _ = resolve_char_file(existing, resolved_dr, world_dir)
                old_val = None
                parse_failed = False
                if fp and fp.exists():
                    try:
                        d = yaml.safe_load(fp.read_text()) or {}
                        tgt = d
                        keys_dr = key_path_str.split(".")
                        tgt_found = True
                        for i_dr, k_dr in enumerate(keys_dr):
                            if not isinstance(tgt, dict) or k_dr not in tgt:
                                tgt_found = False
                                break
                            if i_dr == len(keys_dr) - 1:
                                tgt = tgt[k_dr]
                            else:
                                tgt = tgt[k_dr]
                                if not isinstance(tgt, dict):
                                    tgt_found = False
                                    break
                        old_val = tgt if tgt_found else None
                    except Exception as e:
                        # 与正式写入 write_one 行为对齐：文件解析失败 → 正式写入会被拒
                        parse_failed = True
                        print(f"  [ERR] {file_key} 解析失败，正式写入将被拒绝（防止静默清空）: {e}", file=sys.stderr)
                if parse_failed:
                    continue
                if old_val is None:
                    print(f"  [新增] {file_key}.{key_path_str}")
                elif str(old_val) == content:
                    print(f"  [无变化] {file_key}.{key_path_str}")
                else:
                    action = "追加" if append else "覆盖"
                    print(f"  [{action}] {file_key}.{key_path_str}（旧 {len(str(old_val))}b → 新 {len(content)}b）")
                    if (append and resolved_dr.startswith(CHAR_STATE_PREFIX) and key_path_str == "反应轨迹"
                            and isinstance(old_val, str)):
                        old_blocks = [b for b in re.split(r"(?=^第\d+轮)", old_val, flags=re.M) if b.strip()]
                        if len(old_blocks) >= REACTION_TRAJECTORY_WINDOW:
                            print(f"  [TRIM预演] {resolved_dr}.反应轨迹 追加后超 {REACTION_TRAJECTORY_WINDOW} 轮窗口——正式写入将自动删除最旧 {len(old_blocks) + 1 - REACTION_TRAJECTORY_WINDOW} 块")
            print("[DRY-RUN] ⚠ 非幂等：同一批次只执行一次；执行后确认用 read/validate，禁止重放 write 命令验证")
            if blocked or unknown_count:
                parts = []
                if blocked:
                    parts.append(f"顶回 {len(blocked)} 条")
                if unknown_count:
                    parts.append(f"无法写入 {unknown_count} 条")
                print(f"[DRY-RUN] ❌ " + " + ".join(parts) + ": " + ", ".join(f"{ops[i][1]}.{ops[i][2]}" for i in blocked) + (", " + ", ".join(unknown_items) if unknown_items else ""))
            else:
                print("[DRY-RUN] ✅ 顶回 0 条——批次可安全落盘")
            return

        # 逐条写入：顶回违规字段，其余照写
        written_count = 0
        failed = []
        for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
            if idx in blocked:
                continue
            if kind == "delete":
                cmd_delete(world_dir, [file_key, key_path_str])
                continue
            if write_one(file_key, key_path_str, content, append=append):
                written_count += 1
            else:
                failed.append(f"{file_key}.{key_path_str}")
        op = "批量追加" if append_mode else "批量写入"
        if failed:
            print(f"[FAIL] {len(failed)} 个字段未写入（预期 {len(ops) - len(blocked)} 条，实际写入 {written_count} 个）: {', '.join(failed)}")
            print(f"[OK] {op}完成：{written_count} 个字段写入，{len(failed)} 个字段失败未落盘——请修复后重提批次")
            sys.exit(1)
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
def extract_anchor_names(text: str) -> list[str]:
    """从 scene_state.物理锚点 文本提取元素名（每行冒号/破折号前的名称）。

    兼容两种行格式：
      - 旧格式（S04 等）： `1. 吧台: 描述` 或 `吧台: 描述`
      - 新格式（S08/S09 等）： `· A01 大门——Mariposa正门...`（A 前缀 + 破折号）
    均归一为「名称: 描述」冒号格式后提取。
    """
    names = []
    for line in str(text).splitlines():
        line = line.strip()
        if not line or line.startswith(("|", "-", "#")):
            continue
        # 破折号格式归一：`· A01 大门——描述` / `A01 大门——描述` → `大门: 描述`
        dash_m = re.match(r"^(?:[·\-\s]*)(?:[A-Z]+\d*\s+)?([^:：—]+?)\s*[—–]+\s*", line)
        if dash_m and "——" in line:
            line = re.sub(r"^(?:[·\-\s]*)(?:[A-Z]+\d*\s+)?([^:：—]+?)\s*[—–]+\s*", r"\1: ", line, count=1)
        m = re.match(r"^(?:\d+\.\s*|[A-Z]+\d*\s+)?([^:：]+)[:：]", line)
        if m:
            names.append(m.group(1).strip())
    return names


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
                    if not re.match(r"^CT-\d{2}$", str(k)):
                        warnings.append(f"conflicts.yaml: 顶层键 '{k}' 不符合 CT-XX 格式")
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
    # 3b. 偏离登记 ≥2 次但未注册 Host vs 法则 CT（循环世界·偏离冲突化缺失——loop_machinery §5.1）
    # 限制（O2）：只查「已登记的偏离」，不查「实际偏离但未登记」——本检查是登记后保险（防漏注册），不是偏离检测器（检测=戏剧家四件套职责）
    _abstract_kw = ("园区", "法则", "系统", "世界", "循环", "脚本", "记忆", "程序", "编程")
    for sf in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            sdata = yaml.safe_load(sf.read_text())
        except Exception:
            continue
        if not isinstance(sdata, dict):
            continue
        dev = sdata.get("偏离登记")
        dev_count = 0
        if isinstance(dev, str):
            dev_count = len([ln for ln in dev.splitlines() if ln.strip()])
        elif isinstance(dev, list):
            dev_count = len(dev)
        if dev_count < 2:
            continue
        role_name = sf.name[len(CHAR_STATE_PREFIX):-len(CHAR_STATE_SUFFIX)]
        has_law_ct = False
        try:
            cdata = yaml.safe_load(conflicts_fp.read_text()) if conflicts_fp.exists() else None
            if isinstance(cdata, dict):
                for v in cdata.values():
                    if not isinstance(v, dict):
                        continue
                    sides = str(v.get("对抗双方", ""))
                    if role_name in sides and any(kw in sides for kw in _abstract_kw):
                        has_law_ct = True
                        break
        except Exception:
            pass
        if not has_law_ct:
            warnings.append(f"{sf.name}: 偏离登记 ≥{dev_count} 次但未注册「Host vs 法则」型 CT（对抗双方应含 {role_name} 与抽象方）——偏离冲突化缺失（loop_machinery §5.1）")
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
                WS_TOP_KEYS = {"焦点场景", "轮次", "时间", "地点", "外部倒计时", "全局标记", "时间线", "重置记录", "叙事约定", "输出模式"}
                WS_TIME_KEYS = {"基准时间", "具体时间", "时间流速比", "前情描述"}
                WS_LOC_KEYS = {"当前区域", "已探索区域"}
                for k in ws:
                    if k not in WS_TOP_KEYS:
                        warnings.append(f"world_state.yaml: 未知顶层键 '{k}'（键表: 焦点场景/轮次/时间/地点/外部倒计时/全局标记/时间线/重置记录/叙事约定/输出模式）")
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
    # 4c. 同物理地点场景元素继承检查（防漏继承——同一建筑的空间元素不因时间区间变化而消失）
    try:
        scenes_dir = world_dir / "scenes"
        if scenes_dir.is_dir():
            TIME_WORDS = ["清晨", "午后", "上午", "下午", "黄昏", "黎明", "正午", "傍晚", "午夜", "深夜", "早晨", "中午", "晚上", "早上"]
            ELEMENT_TAIL = ["暗门", "金库", "吧台", "钢琴", "楼梯", "大门", "前门", "正门", "门帘", "窗户", "窗", "床", "盖板", "地窖", "柜台", "长椅", "教堂", "月台", "墙根", "后厨", "房间", "门"]
            ELEMENT_SYN = {"暗门": ["暗门", "盖板"], "门": ["门", "大门", "前门", "正门"]}
            groups = {}
            for d in sorted(scenes_dir.iterdir()):
                if not d.is_dir():
                    continue
                m = re.match(r"^(S\d+)-(.*)$", d.name)
                if not m:
                    continue
                sid, sname = m.group(1), m.group(2)
                pk = sname
                for tw in TIME_WORDS:
                    pk = pk.replace(tw, "")
                pk = pk.strip(" -")
                if not pk:
                    continue
                ssp = d / "scene_state.yaml"
                names = []
                if ssp.exists():
                    try:
                        sdata = yaml.safe_load(ssp.read_text())
                        if isinstance(sdata, dict) and sdata.get("物理锚点"):
                            names = extract_anchor_names(str(sdata["物理锚点"]))
                    except Exception:
                        pass
                groups.setdefault(pk, []).append((sid, sname, names))
            for pk, scenes in groups.items():
                if len(scenes) < 2:
                    continue
                scenes.sort(key=lambda x: x[0])
                base_id, base_name, base_names = scenes[0]
                for sid, sname, names in scenes[1:]:
                    for b in base_names:
                        btype = next((t for t in ELEMENT_TAIL if b.endswith(t)), None)
                        if not btype:
                            continue
                        # 同义词组匹配（如 暗门/盖板）：新场景元素名命中任一成员即视为存在
                        syn = ELEMENT_SYN.get(btype, [btype])
                        if not any(any(s in c for s in syn) for c in names):
                            warnings.append(f"场景继承: {sid}-{sname} 缺少同建筑元素「{btype}」（{base_id}-{base_name} 已注册: {b}）——疑似漏继承，用 init_scene.sh --from 继承或核对")
    except Exception:
        pass
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
    # 6. CHAR_state 字段级校验（键表/人际动态档位/废弃键/全知视角/反应轨迹方向）
    CHAR_ALLOWED_KEYS = {"位置", "名字", "核心状态", "情绪", "人际动态", "决策状态",
                         "压力水平", "防御有效性", "偏离登记", "信念演化", "记忆锚点", "反应轨迹",
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
                warnings.append(f"{cname}: 未知键 '{k}'（键表: 自主性/位置/名字/核心状态/情绪/人际动态/决策状态/压力水平/防御有效性/偏离登记/信念演化/记忆锚点/反应轨迹；模板扩展: 服装/健康/随身）")
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

    # 8. CHAR_state 记忆锚点校验（脚本校验线：单条≤150字 | 总字数≤3000——超限告警，提示戏剧家按 §记忆淘汰 整理）
    ANCHOR_LIMIT_TOTAL = 3000
    ANCHOR_LIMIT_ENTRY = 150
    for cfp in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            cdata = yaml.safe_load(cfp.read_text())
        except Exception:
            continue
        if not isinstance(cdata, dict):
            continue
        mem = cdata.get("记忆锚点", "")
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
            if not isinstance(mem, str):
                continue
            has_frag = "碎片" in mem
            has_key = "关键锚点" in mem
            old_ts_left = len(re.findall(r"\[第\d+日/", mem))
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

    # 8d. 轮次覆盖检查（场记收尾自查代码化——①焦点场景时间线②出场角色反应轨迹③world_state 齐备）
    try:
        ws3 = yaml.safe_load(world_dir.joinpath("world_state.yaml").read_text()) or {}
        cur_round3 = str(ws3.get("轮次", "") or "").strip()
        t3 = ws3.get("时间") or {}
        if not isinstance(t3, dict):
            t3 = {}
        cur_time3 = str(t3.get("具体时间", "") or "").strip()
        focus3 = str(ws3.get("焦点场景", "") or "").strip()
        # ① 焦点场景 scene_state 场景时间线末条应含本轮时间/轮次
        if focus3 and scene_dir and scene_dir.is_dir():
            ssp3 = scene_dir / "scene_state.yaml"
            if ssp3.exists():
                try:
                    sd3 = yaml.safe_load(ssp3.read_text()) or {}
                    tl3 = sd3.get("场景时间线", "")
                    if isinstance(tl3, str) and tl3.strip():
                        last_line3 = [l for l in tl3.splitlines() if l.strip()][-1]
                        hm3 = cur_time3.split(" ")[-1] if " " in cur_time3 else cur_time3
                        if hm3 and hm3 not in last_line3 and cur_round3 not in last_line3:
                            warnings.append(f"轮次覆盖: {scene_dir.name}/scene_state.yaml 场景时间线末条不含本轮时间 {cur_time3}——疑似漏写本轮场景时间线（收尾自查①）")
                    else:
                        warnings.append(f"轮次覆盖: {scene_dir.name}/scene_state.yaml 场景时间线为空——疑似漏写（收尾自查①）")
                except Exception:
                    pass
        # ② 焦点场景出场角色（非焦外）CHAR_state 反应轨迹末项 ≥ 本轮
        if focus3 and cur_round3 and scene_dir and scene_dir.is_dir():
            try:
                sdata3 = yaml.safe_load((scene_dir / "scene_state.yaml").read_text()) or {}
                cast_txt3 = sdata3.get("出场角色摘要", "")
                if isinstance(cast_txt3, str):
                    for ln3 in cast_txt3.splitlines():
                        if "(焦外)" in ln3 or "焦外" in ln3:
                            continue
                        m3 = re.match(r"^\s*-\s*([^:：\-—]+?)\s*(?:[—\-—]|:)", ln3)
                        if not m3:
                            continue
                        cname3 = m3.group(1).strip()
                        if not cname3:
                            continue
                        # 简称→全名：用包含匹配扫描角色档案（场景摘要常用简称如 Clementine/Maeve）
                        hits3 = []
                        for cand3 in sorted(world_dir.glob(f"{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
                            full3 = cand3.stem[len(CHAR_STATE_PREFIX):]
                            if full3.endswith("_state"):
                                full3 = full3[:-len("_state")]
                            if cname3 in full3 or full3 in cname3:
                                hits3.append(cand3)
                        if len(hits3) != 1:
                            continue
                        cfp3 = hits3[0]
                        if not cfp3.exists():
                            continue
                        cd3 = yaml.safe_load(cfp3.read_text()) or {}
                        rt3 = cd3.get("反应轨迹", "")
                        if isinstance(rt3, str) and rt3.strip():
                            marks3 = [int(x) for x in re.findall(r"第(\d+)轮", rt3)]
                            if marks3 and marks3[-1] < int(cur_round3):
                                warnings.append(f"轮次覆盖: {cfp3.name} 反应轨迹末项第{marks3[-1]}轮 < 本轮{cur_round3}——疑似漏写本轮反应轨迹（收尾自查②）")
            except Exception:
                pass
        # ③ world_state 轮次/时间/前情齐备
        if cur_round3 and cur_time3:
            if not str(t3.get("前情描述", "") or "").strip():
                warnings.append("轮次覆盖: world_state 缺 时间.前情描述（收尾自查③）")
        elif not cur_round3:
            warnings.append("轮次覆盖: world_state 缺 轮次（收尾自查③）")
        elif not cur_time3:
            warnings.append("轮次覆盖: world_state 缺 时间.具体时间（收尾自查③）")
    except Exception:
        pass

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
            "D8  记忆维护: 判型/重置/入锚/淘汰 落 change set",
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
                print("[GATE] 未提供 change set（stdin 为空）——D1/D10 无法代码化核验，请人工逐项作答", file=sys.stderr)
                return
            ops, parse_errors = parse_batch_entries(raw.split("\n"))
            hard, _ = check_batch(ops, world_dir)
            # check_batch 的必含项 hard 用 op_index=-1 标记批次级违规
            batch_violations = [msg for idx, msg in hard if idx == -1]
            field_violations = [msg for idx, msg in hard if idx != -1]
            if batch_violations or field_violations or parse_errors:
                print("[GATE] D1/D10 代码化核验失败——change set 不合格:", file=sys.stderr)
                for e in parse_errors:
                    print(f"  - {e}", file=sys.stderr)
                for msg in batch_violations:
                    print(f"  - {msg}", file=sys.stderr)
                for msg in field_violations:
                    print(f"  - {msg}", file=sys.stderr)
                sys.exit(1)
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
            if suspect:
                print(f"[GATE] W4 锚点核验失败——叙事「」内元素疑似未注册或位置冲突: {suspect}（请用 worldctl.py <世界> grep <元素名> 核对注册原文）", file=sys.stderr)
                sys.exit(1)
            print("[GATE] W4 锚点核验通过（叙事「」内专名均已注册且位置一致）——W1/W2/W3 请人工逐项作答", file=sys.stderr)

    else:
        print("用法: worldctl.py <世界> gate dramatist|writer [--check]", file=sys.stderr)
        print("  dramatist: 阶段1 出口闸门 D1-D10（write-raw 前调用）", file=sys.stderr)
        print("  writer:    阶段2 输出闸门 W1-W4（message 推送前调用）", file=sys.stderr)
        print("  --check: 从 stdin 读 change set/叙事，运行可代码化硬性核验，不合格 exit 1", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="WorldSim 批量状态管理 V2")
    parser.add_argument("world", help="世界名")
    parser.add_argument("action", choices=["read", "write", "write-raw", "append-raw", "delete", "convert", "validate", "audit", "grep", "scan", "gate"])
    parser.add_argument("--files", help="read 时限定文件 key 列表，逗号分隔")
    parser.add_argument("--full", action="store_true", help="write 时全量覆写")
    parser.add_argument("--batch", action="store_true", help="write-raw/append-raw 批量模式：stdin 为 ###FILE/###KEY/###APPEND 记录格式（⚠非幂等：APPEND 重复执行会重复追加·同一批次只执行一次·验证用 read/validate/--dry-run）")
    parser.add_argument("--dry-run", action="store_true", help="write-raw/append-raw 预演：解析+audit+对比磁盘差异，不落盘（重跑批次前先对比）")
    parser.add_argument("--check", action="store_true", help="gate 代码化核验模式：从 stdin 读 change set（dramatist）或叙事（writer），运行可代码化检查，不合格 exit 1")
    parser.add_argument("--live", action="store_true", help="scan 仅当前文件（排除历史轮转 narrative.*.md 与 archive）")
    parser.add_argument("extra", nargs="*", help="write-raw/append-raw 的额外参数: <文件key> <YAML键路径> [内容]")
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

if __name__ == "__main__":
    main()
