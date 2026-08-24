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
  worldctl.py <世界名> gate dramatist|storyliner|director|actor|keeper|writer [--check]
                                         ← 六阶段闸门（--check=从 stdin 读该阶段批次/叙事跑代码化核验·不合格 exit 1）
  worldctl.py <世界名> storyline <子命令> ← 事件线结构维护（show/add/rewrite/close/clear·写 states/storylines.yaml·②编剧唯一通道）
  worldctl.py <世界名> beat <子命令>     ← 演出指针维护（show/set/stay/advance·写 states/direction.yaml·③导演唯一通道）
  worldctl.py <世界名> reset-cycle [--asset <角色>]
                                         ← 循环世界周期重置（全员机械重置+登记+重建倒计时）
  worldctl.py <世界名> round-check       ← 轮完整性检查（⑤场记收尾：direction/world_state 三件套/场景时间线/区域一致性/引用对账）
  worldctl.py <世界名> migrate           ← v0.11→v0.12 数据迁移（节拍表→storylines·CT.当前节拍→direction·旧字段清除+迁移报告）
  worldctl.py <世界名> init-states      ← 首次启动物化缺失动态文件（幂等·模板+SEED+CHAR_state 骨架·LF·有 regions/ 自动对账）
  worldctl.py <世界名> map-sync         ← world_map 镜像层对账（regions/ 目录树 → 补缺失节点）
  worldctl.py <世界名> lint              ← 规范化检查：报告 YAML 引号/类型问题（只读，不修改）
  worldctl.py <世界名> fix               ← 规范化重写：修复引号/类型问题（snap 自动备份 + validate）
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

# I/O 纪律（硬性）：本脚本读写一律 UTF-8——Windows 缺省 locale（GBK）读中文 yaml 必炸、
# emoji（🔴等）写 GBK stdout 必炸；所有 open/read_text/write_text 已显式 encoding，此处兜底 stdout/stderr
for _s in (sys.stdout, sys.stderr):
    try:
        if _s and _s.encoding and _s.encoding.lower().replace("-", "") != "utf8":
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# skill 根 = 脚本自身位置推导（不可被环境变量覆写——SKILL.md/脚本/模板必须同源）
SKILL_DIR = Path(__file__).resolve().parent.parent
# worlds 根 = 可被环境变量 WORLDSIM_WORLDS_DIR 覆写（用户自己的存储）；缺省 = {skill_dir}/worlds
WORLDS_ROOT = Path(os.environ.get("WORLDSIM_WORLDS_DIR", SKILL_DIR / "worlds"))
CHAR_STATE_PREFIX = "CHAR_"
CHAR_STATE_SUFFIX = "_state.yaml"

# 节拍表（v0.11 旧结构·conflicts.yaml 顶层·迁移后由 storylines.yaml 取代）
BEAT_TOP_KEY = "节拍表"
BEAT_ENUM = ("铺垫", "接触", "升级", "顶点", "余波")

# v0.12 六阶段单管道：结构蓝图（storylines·②编剧）与现场控制（direction·③导演）分权
STORYLINES_FILE = "storylines.yaml"
DIRECTION_FILE = "direction.yaml"
STORYLINE_TOP_KEY = "事件线"
STORYLINE_ID_PREFIX = "SL-"
STAGES = ("戏剧家", "编剧", "导演", "角色", "场记", "作家")
# Single Writer per State（design-v2 §4 写入矩阵）：阶段 → 允许写入的文件 key（"CHAR_"=前缀匹配）
STAGE_WRITE_MAP = {
    "戏剧家": {"conflicts"},
    "编剧": {"storylines"},
    "导演": {"direction"},
    "角色": {"CHAR_"},
    "场记": {"scene_state", "world_state", "world_map", "pending_actions", "foreshadow"},
    "作家": set(),
}
# conflicts 已迁移字段（v0.11 → v0.12）：写入即拦截（防旧流程残留写回）
CT_LEGACY_KEYS = ("当前节拍", "下一个节拍(推荐)", "角色反应", "节拍表")
DIRECTION_KEYS = {"当前事件线", "当前拍", "当前戏剧问题", "当前张力", "演出状态", "阶段",
                  "承接判断", "节拍决策", "guidance", "转场", "escalation_flags", "时间窗口", "调度单"}
STORYLINES_TOP_KEYS = {"故事弧线", STORYLINE_TOP_KEY}
PERF_STATES = ("上升", "持续", "转折", "收束", "停滞")
# 施压方向（conflicts 顶层键·①戏剧家每轮随推进池标注——瞄准声明·非结算字段非行动脚本）
PRESSURE_KEY = "施压方向"
PRESSURE_ENUM = ("死局两难", "防御踩爆", "关系撕裂", "不可逆代价", "维持")
# 连续行动轨迹增长告警线（窗口滚动裁剪后·兜底软告警）
ACTION_TRACK_LIMIT = 5000

# 顶点约束（Vertex Constraint——编剧声明的这一场关系必须被推至的临界验收结构）
# 结构：关系主体(≥2·不区分玩家/NPC·顶点单位=关系) / 核心张力(未决问题·点名赌注所在) /
#       变化维度(枚举·创作意图声明——指导张力走向与演出侧重·非验收映射) /
#       非玩家爆破(≥1 外部角色或事件·主体静止时的加压力量·防死锁) /
#       基准快照(脚本自动记录·仅关系主体·实质状态字段集·私有落档 states/.climax_baseline_{SL}.yaml——
#         不进 storylines/任何读取面·LLM 不填不读)
# 验收：关系主体的实质状态字段发生任何真实变化即出线（任一来源——主体/对手/外部爆破/世界事件）。
#   【核心设计】验收对比面 = 下面的字段集·但该字段集不写入任何规则文本/审计消息——
#   让 LLM 公开知道"验收哪些字段"= 给它做题靶子（信念演化/防御重构/自主性正是最高级改变·更须防泄露）；
#   字段集的唯一权威在本文件（脚本层）：LLM 只负责演出·脚本默默比对。
DIM_ENUM = ("关系", "认知", "决策", "资源")
SUBSTANTIVE_FIELDS = ("人际动态", "记忆锚点", "信念演化", "决策状态", "decision",
                      "防御有效性", "防御形态", "崩溃表现", "自主性", "核心状态")
CLIMAX_LIST_FIELDS = ("记忆锚点", "信念演化")   # 列表字段按条数比较（基准快照用）

def _climax_baseline_fp(world_dir: Path, sl_id: str) -> Path:
    """基准快照私有落档路径（下划线前缀=脚本私有·不进入 discover_files/read/storyline show 等任何读取面）。"""
    return world_dir / "states" / f".climax_baseline_{sl_id}.yaml"

def _load_climax_baseline(world_dir: Path, sl_id: str) -> dict:
    fp = _climax_baseline_fp(world_dir, sl_id)
    if not fp.exists():
        return {}
    try:
        d = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}
CLIMAX_BASELINE_KEY = "基准快照"
CLIMAX_CONSTRAINT_KEY = "顶点约束"

def _read_stdin_utf8() -> str:
    """stdin 原始字节显式 UTF-8（与 --batch 同款安全通道）——Windows cmd /c 重定向 UTF-8 临时文件时，
    sys.stdin 按 locale（GBK）解码会损坏中文；一律经系统 stdin 字节流显式 UTF-8 解码。"""
    return sys.stdin.buffer.read().decode("utf-8")


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
    ws_fp = world_dir / "states" / "world_state.yaml"
    if not ws_fp.exists():
        return None
    try:
        ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8"))
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
            scene_id = active_file.read_text(encoding="utf-8").strip()
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
    for fname in ["world_state.yaml", "conflicts.yaml", "world_map.yaml", STORYLINES_FILE, DIRECTION_FILE]:
        fp = world_dir / "states" / fname
        if fp.exists(): files[fp.stem] = fp
    # 角色状态
    for fp in world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}"):
        files[fp.stem] = fp
    # 场景状态
    if scene_dir:
        ssp = scene_dir / "scene_state.yaml"
        if ssp.exists(): files["scene_state"] = ssp
    # 焦外（场景级·与 scene_state 同处）
    if scene_dir:
        ofp = scene_dir / "pending_actions.yaml"
        if ofp.exists(): files["pending_actions"] = ofp
    # 伏笔登记（可选·触发式）
    ffp = world_dir / "states" / "foreshadow.yaml"
    if ffp.exists(): files["foreshadow"] = ffp
    return files

# ── CHAR key 命名归一化 ──────────────────────────────────────────
def _normalize_file_key(key: str) -> str:
    """文件 key 归一化（对齐 write_protocol「FILE key 注册表·兼容写法自动剥离」承诺）：
    剥 .yaml/.yml 后缀、剥 states/ 或任意路径前缀（含反斜杠）——使
    `world_state.yaml` / `scenes/S01-xx/pending_actions.yaml` / `scenes/S01-xx/scene_state.yaml` 等写法
    均归一到注册表 stem（world_state/pending_actions/scene_state…）。"""
    k = (key or "").strip().replace("\\", "/")
    if k.endswith(".yaml"):
        k = k[:-5]
    elif k.endswith(".yml"):
        k = k[:-4]
    k = k.split("/")[-1]
    return k


def resolve_char_file(existing: dict, key: str, world_dir: Path):
    """解析 CHAR_* 写入目标。已存在→直接映射；不存在→检查空格/下划线互换及缺失 _state 后缀的相似 key，
    命中则映射到已有文件并警告（杜绝同一角色产生两份状态文件）；否则→按 key 新建。"""
    key = _normalize_file_key(key)
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
        return world_dir / "states" / f"{key}.yaml", None
    return None, None

def pending_actions_path(scene_dir: Path | None, create: bool = True) -> Path | None:
    """场景级 pending_actions.yaml 路径——缺失时按模板建（对齐 init_scene）。create=False 用于 --dry-run（只解析不落盘）。"""
    if scene_dir is None:
        return None
    ofp = scene_dir / "pending_actions.yaml"
    if not ofp.exists():
        if not create:
            return ofp
        try:
            ofp.write_text("已完成: {}\n活跃中: {}\n", encoding="utf-8", newline="")
        except OSError as e:
            print(f"[ERR] 创建 pending_actions.yaml 失败（{e}）", file=sys.stderr)
            return None
    return ofp

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
        world_dir / "world_state.md":      world_dir / "states" / "world_state.yaml",
        world_dir / "conflicts.md":        world_dir / "states" / "conflicts.yaml",
    }
    # 角色状态
    for fp in world_dir.glob(f"{CHAR_STATE_PREFIX}*_state.md"):
        yaml_name = fp.stem + ".yaml"
        md_to_yaml[fp] = world_dir / "states" / yaml_name
    
    # 场景状态
    if scene_dir:
        ssmd = scene_dir / "scene_state.md"
        ssym = scene_dir / "scene_state.yaml"
        if ssmd.exists():
            md_to_yaml[ssmd] = ssym
    
    # 焦外（legacy convert：旧格式单一 off_focus/pending_actions.md → states/pending_actions.yaml）
    # 注：现行约定 pending_actions 为场景级（scenes/{焦点场景}/·由 init_scene/create 建）；此映射仅服务旧 .md 世界转换的过渡产物。
    ofmd = world_dir / "off_focus" / "pending_actions.md"
    ofym = world_dir / "states" / "pending_actions.yaml"
    if ofmd.exists():
        md_to_yaml[ofmd] = ofym

    # 处理函数映射：(函数, 额外参数)
    handlers = {
        "world_state": (convert_world_state, False),
    }

    for src, dst in md_to_yaml.items():
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
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
            with open(fp, encoding="utf-8") as f:
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

    delta = yaml.safe_load(_read_stdin_utf8())
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
                with open(filepath, encoding="utf-8") as f:
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
TRAJECTORY_WINDOW = 10              # 连续行动轨迹窗口（最近 N 轮·APPEND 后脚本自动删最旧·LLM 零操作·长期记忆由记忆锚点承载）

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
    """解析 ###FILE/###KEY/###APPEND/###DELETE 与 v0.12 批次元数据行。
    返回 ctx（dict）：
      ops      : [(kind, file_key, key_path, content, append)]，kind ∈ {"write","delete"}；空值 KEY 覆盖在此阶段拒绝
      errors   : 解析错误列表
      meta     : ###META 行（静默自查锚点——不产生写入 ops·不落盘）
      stage    : ###STAGE 声明的阶段名（戏剧家/编剧/导演/角色/场记/作家·缺省 ""）
      storyline: [(动作行, payload行列表|None)]——add/rewrite/close 后跟 YAML 块（到下一个 ### 行·write-raw 自动执行）
      beat     : [动作行]——set/stay/advance（③导演·无 payload）
      action   : [行动卡行]——④角色阶段产物（四件套·audit ①①b⑨ 检查对象）
      schedule : [调度单行]——受影响链留痕（④角色·时间窗口收敛记录）"""
    ops = []
    errors = []
    meta_lines = []
    stage = ""
    storyline_lines = []
    beat_lines = []
    action_lines = []
    schedule_lines = []
    current_file = None
    current_key = None
    current_append = False
    current_content = []
    sl_payload = None

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
        line = line.lstrip("\ufeff")  # Windows 工具链（如 PS5.1 Set-Content -Encoding UTF8）可能在首行产生 BOM
        if line.startswith("###STAGE:"):
            sl_payload = None
            stage = line[len("###STAGE:"):].strip()
        elif line.startswith("###META:"):
            sl_payload = None
            meta_lines.append(line[8:].strip())
        elif line.startswith("###STORYLINE:"):
            sl_action = line[len("###STORYLINE:"):].strip()
            first = sl_action.split()[0] if sl_action else ""
            if first in ("add", "rewrite", "close"):
                sl_payload = []
                storyline_lines.append((sl_action, sl_payload))
            else:
                sl_payload = None
                storyline_lines.append((sl_action, None))
        elif line.startswith("###BEAT:"):
            sl_payload = None
            beat_lines.append(line[len("###BEAT:"):].strip())
        elif line.startswith("###ACTION:"):
            sl_payload = None
            action_lines.append(line[len("###ACTION:"):].strip())
        elif line.startswith("###SCHEDULE:"):
            sl_payload = None
            schedule_lines.append(line[len("###SCHEDULE:"):].strip())
        elif line.startswith("###FILE:"):
            sl_payload = None
            flush()
            current_file = line[8:].strip()
        elif line.startswith("###KEY:"):
            sl_payload = None
            flush()
            current_key = line[7:].strip()
            current_append = False
        elif line.startswith("###APPEND:"):
            sl_payload = None
            flush()
            current_key = line[10:].strip()
            current_append = True
        elif line.startswith("###DELETE:"):
            sl_payload = None
            flush()
            rest = line[10:].strip()
            parts = rest.split(None, 1)
            if len(parts) == 2:
                ops.append(("delete", parts[0], parts[1], "", False))
            else:
                errors.append("###DELETE 格式: ###DELETE: <文件key> <YAML键路径>")
        elif sl_payload is not None:
            # ###STORYLINE: add/rewrite 的事件线 YAML 块（收集到下一个 ### 行）
            sl_payload.append(line)
        elif current_file and current_key:
            # 内容行内嵌标记检测（防拼接 bug）：行内出现批次标记但不在行首 = 上一字段内容被拼接
            for marker in ("###FILE:", "###KEY:", "###APPEND:", "###DELETE:", "###STORYLINE:", "###BEAT:", "###ACTION:", "###SCHEDULE:", "###STAGE:"):
                if marker in line and not line.lstrip().startswith(marker):
                    errors.append(
                        f"内容行内嵌标记 {marker.strip(':')}（行首无标记）：'{line[:60]}'——疑似上一字段内容与标记拼接（如缺少换行）。"
                        f"位置: {current_file}.{current_key}"
                    )
                    break
            current_content.append(line)
    flush()
    return {"ops": ops, "errors": errors, "meta": meta_lines, "stage": stage,
            "storyline": storyline_lines, "beat": beat_lines, "action": action_lines, "schedule": schedule_lines}


def _parse_role_coverage(meta_lines):
    """解析 ###META 中的结构化角色覆盖声明。

    格式：角色覆盖: Name=更新,Other=更新(在轨·轻量)
    返回 {规范化角色名: 状态}；角色名允许用下划线代替空格。
    """
    coverage = {}
    for line in meta_lines or []:
        match = re.search(r"角色覆盖\s*[:：]\s*(.+)$", line)
        if not match:
            continue
        for item in match.group(1).split(","):
            item = item.strip()
            if "=" not in item:
                continue
            role, status = item.split("=", 1)
            role = role.strip().replace("_", " ")
            status = status.strip()
            if role:
                coverage[role] = status
    return coverage


def _action_roles(action_lines):
    """收集 ###ACTION 行动卡的角色名（'{角色}: {行为序列} | 驱动: …' 前缀）。"""
    roles = set()
    for line in action_lines or []:
        m = re.match(r"^\s*([^:|]+)[:：]", str(line))
        if m:
            role = m.group(1).strip()
            if role:
                roles.add(role)
    return roles


def _direction_schedule_text(world_dir: Path) -> str:
    """direction.yaml 的「调度单」字段文本（③导演画面调度·焦内活跃/背景/焦外）。"""
    fp = world_dir / "states" / DIRECTION_FILE
    if not fp.exists():
        return ""
    try:
        d = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return ""
    if not isinstance(d, dict):
        return ""
    return str(d.get("调度单", "") or "")


def _schedule_cast_roles(world_dir: Path) -> set:
    """从 调度单 提取点名/提及的已知角色名（焦内活跃/背景/焦外段·用于角色覆盖对账）。"""
    sched = _direction_schedule_text(world_dir)
    if not sched:
        return set()
    segs = []
    for part in sched.split("·"):
        p = part.strip()
        if any(p.startswith(k) for k in ("焦内活跃", "背景", "焦外", "焦外→焦内")):
            segs.append(p)
    if not segs:
        segs = [sched]
    seg_text = " ".join(segs)
    known = set()
    for fp in world_dir.glob("characters/CHAR_*.md"):
        stem = fp.stem[len("CHAR_"):].strip()
        if stem:
            known.add(stem)
    cast = set()
    for char in known:
        # 别名：全名 + 各 token（≥3 字符）——调度单常以名字引用（如 Dolores/Teddy/Maeve）
        cands = {" ".join(char.split())}
        for w in char.split():
            if len(w) >= 3:
                cands.add(w)
        if any(c in seg_text for c in cands):
            cast.add(char)
    return cast


def check_batch(ops, world_dir, ctx=None, enforce_scene_dir=True, force=False, via="write"):
    """语义不变量检查（v0.12 六阶段批次→硬性违规/软性警告分类）。
    ctx = parse_batch_entries 返回值（stage/storyline/beat/action/schedule/meta）——按阶段分化必含项。
    enforce_scene_dir=False（gate/audit 预检路径）：scene_state 落点检查降级为软提示——
    场景目录由场记阶段 init_scene 创建（先于批次写入），预检时目录可能尚不存在，不误拦。
    硬性违规（hard）：结构性/机械性错误——关键字段缺失、载体核验、轮次单调、落点错误、Single Writer 越权。写入时**单字段顶回**。
    软性警告（soft）：内容质量类——记忆锚点超限等。写入时**不拦截**，仅记录（validate 汇总）。
    返回 (hard, soft)，元素为 (op_index, message)；批次级消息 op_index=-1（gate 按阶段升级为硬拦）。"""

    hard = []
    soft = []
    scene_dir = get_scene_dir(world_dir)
    existing = discover_files(world_dir, scene_dir)
    ctx = ctx or {}
    stage = str(ctx.get("stage", "") or "")
    storyline_lines = ctx.get("storyline") or []
    beat_lines = ctx.get("beat") or []
    action_lines = ctx.get("action") or []
    meta_lines = ctx.get("meta") or []

    # 预读当前值（用于对比型检查：轮次单调、锚点总量）
    current = {}
    for key, fp in existing.items():
        try:
            current[key] = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
        except Exception:
            current[key] = {}

    # 重置豁免预扫描（2026-08-12 加入）：批次内登记了角色重置（world_state.重置记录.{角色} KEY 写入）→
    # 该角色按 loop_machinery §4 联动表清空/压缩 记忆锚点/轨迹（脚本档全清·漂移压缩·觉醒/变质保留）。
    # 轨迹覆盖写检查对此豁免——重置清空是机制执行（联动表），不是丢失历史
    reset_chars = set()
    for _i, (_k, _fk, _kp, _c, _a) in enumerate(ops):
        if _k == "write" and _fk == "world_state" and _kp.startswith("重置记录."):
            _name = _kp[len("重置记录."):]
            if _name:
                reset_chars.add(_name)

    # Single Writer per State（硬性·design-v2 §4 写入矩阵）：###STAGE 声明后按矩阵拦截越权写入
    if stage in STAGE_WRITE_MAP:
        allowed = STAGE_WRITE_MAP[stage]
        for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
            if kind != "write":
                continue
            ok = (file_key in allowed
                  or ("CHAR_" in allowed and file_key.startswith(CHAR_STATE_PREFIX)))
            if not ok:
                hard.append((idx, f"Single Writer 违规：{stage}批不得写 {file_key}.{key_path_str}（写入矩阵: conflicts=①戏剧家 / storylines=②编剧 / direction=③导演 / CHAR_*=④角色 / scenes+world_state+world_map+pending_actions+foreshadow=⑤场记——design-v2 §4）"))
    elif stage and stage not in STAGES:
        soft.append((-1, f"###STAGE '{stage}' 非法（枚举: {'/'.join(STAGES)}）"))

    # 批次整体必含项标记（阶段分化·见批次级检查）
    has_ct_op = False
    has_ws_time = False
    has_ws_round = False
    has_ws_summary = False
    has_scene_timeline = False
    has_char_op = False

    for idx, (kind, file_key, key_path_str, content, append) in enumerate(ops):
        if kind != "write":
            continue
        key_path = key_path_str.split(".")

        # 嵌套记录字段类型校验（2026-08-17 加入·方案B·防复发）：记录类字段（world_state.重置记录.{角色}/时间线.{ID}/外部倒计时.{CD}
        #   ·world_map.已探索区域.{区域}）内容必须为 YAML 映射——多行字符串会被当字符串写入=读取端（reset-cycle 豁免/④b 覆盖判定/validate 8b）读不到。
        #   判据与 write_one 实际写入对齐：多行且 safe_load 为 dict → 写入 dict（放行）；单行/列表/解析失败 → 写入字符串（顶回）
        if len(key_path) == 2 and (
                (file_key == "world_state" and key_path[0] in ("重置记录", "时间线", "外部倒计时"))
                or (file_key == "world_map" and key_path[0] == "已探索区域")):
            _will_be_dict = False
            if "\n" in content:
                try:
                    _parsed_map = yaml.safe_load(content)
                except Exception:
                    _parsed_map = None
                _will_be_dict = isinstance(_parsed_map, dict)
            if not _will_be_dict:
                hard.append((idx, f"{file_key}.{key_path_str}: 嵌套映射字段内容必须为 YAML 映射（{key_path[0]}.{key_path[1]} 应为多行键值块·当前单行/列表/字符串=写入后读取端读不到）"))

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
        if file_key.startswith(CHAR_STATE_PREFIX):
            has_char_op = True

        # conflicts.yaml 路径归一化：去掉多余的 `conflicts.` 根前缀
        if file_key == "conflicts" and key_path and key_path[0] == "conflicts":
            key_path = key_path[1:]

        # ⓪ CT 已迁移字段守卫（硬性·v0.12 schema）：节拍表/当前节拍/下一个节拍(推荐)/角色反应 已迁出 conflicts——
        #    结构归 storylines（###STORYLINE·②编剧）/指针归 direction（###BEAT·③导演）/角色行动归 ###ACTION+CHAR_state（④角色）
        if file_key == "conflicts" and key_path:
            if key_path[0] == BEAT_TOP_KEY or (key_path[0].startswith("CT-")
                    and any(k in key_path for k in ("当前节拍", "下一个节拍(推荐)", "角色反应"))):
                hard.append((idx, f"{file_key}.{key_path_str}: v0.12 已迁移字段（节拍表/当前节拍/下一个节拍(推荐)/角色反应）——结构走 ###STORYLINE（storylines）/指针走 ###BEAT（direction）/角色行动走 ###ACTION+CHAR_state；存量世界先执行 worldctl.py {world_dir.name} migrate"))

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
                        old = (yaml.safe_load(filepath.read_text(encoding="utf-8")) or {}).get("记忆锚点", "")
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

        # ④ 轮次单调（时间只增不减）——显式回退（--force）豁免：轮次可回退，但必须仍为整数
        # via="gate" 为闸门终检：落盘在闸门之前（SKILL 顺序：产出→写→gate），磁盘轮次已=新值，
        #   故用防倒退语义（new<old 才拦·new==old 放行=已落盘正常）；via="write"（write-raw/audit）为落盘前校验，用推进语义（new>old）。
        if file_key == "world_state" and key_path == ["轮次"]:
            try:
                new_val = int(content.strip())
                old_val = int((current.get("world_state", {}).get("轮次") or 0))
                if not force:
                    if via == "gate":
                        if new_val < old_val:
                            hard.append((idx, f"world_state.轮次: {new_val} < 当前值 {old_val}（时间只增不减·防回退）"))
                    else:
                        if new_val <= old_val:
                            hard.append((idx, f"world_state.轮次: {new_val} 必须 > 当前值 {old_val}（时间只增不减·显式回退用 write-raw --batch --force）"))
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
                                # 豁免记录（触发=豁免）不算全员重置已执行——豁免仅跳过该角色·其他循环角色仍须重置
                                #   （2026-08-17 加入·防豁免记录误放行全员重置）
                                if isinstance(rspec, dict) and str(rspec.get("重置日期", "")) == day_label \
                                        and str(rspec.get("触发", "")) != "豁免":
                                    covered = True
                                    break
                        if not covered:
                            hard.append((idx, f"world_state.时间.具体时间: 越过周期重置到期时刻 {due_hit}·但 重置记录 无覆盖 {day_label} 的记录——重置未执行（执行: worldctl.py {world_dir.name} reset-cycle 后重写）"))
            except Exception:
                pass


        # ⑤ scene_state 落点：必须有真实存在的焦点场景目录（防止写错场景 / init_scene 未执行时静默 mkdir 残缺场景）——写入路径硬性拦截；
        #    gate/audit 预检路径（enforce_scene_dir=False）降为软提示（场景目录由场记阶段3 init_scene 创建·先于批次写入）
        if file_key == "scene_state" and (scene_dir is None or not scene_dir.is_dir()):
            if scene_dir is None:
                msg = "scene_state 落点错误: 无法定位当前焦点场景目录——先确认 world_state.焦点场景 后再写入"
            else:
                msg = f"scene_state 落点错误: 焦点场景目录不存在（{scene_dir}）——先执行 init_scene 创建场景（scene_card/start_snapshot/INDEX ACTIVE）后再写入"
            if enforce_scene_dir:
                hard.append((idx, msg))
            else:
                soft.append((idx, f"{msg}（预检软提示：场景目录将由场记阶段3 init_scene 创建·写入点仍硬性拦截）"))

        # ⑥ 时间线事件写语义提示（软性·不拦截）：world_state.时间线.*.事件 默认 APPEND 追加；
        #    ###KEY 覆盖仅用于 validate 告警后的压缩维护（读旧值+压缩合并+补新）
        if (file_key == "world_state" and len(key_path) >= 3
                and key_path[0] == "时间线" and key_path[-1] == "事件" and not append):
            soft.append((idx, f"{file_key}.{key_path_str}: 时间线事件默认 ###APPEND 追加；###KEY 覆盖仅在 validate 告警后的压缩维护时使用（读旧值+压缩合并+补新）"))

        # ⑦ world_state 键表外字段（软性警告——无语义定义的漂移字段）
        if file_key == "world_state" and key_path:
            WS_TOP_KEYS = {"焦点场景", "轮次", "时间", "外部倒计时", "全局标记", "时间线", "重置记录", "叙事约定"}
            WS_TIME_KEYS = {"基准时间", "具体时间", "时间流速比", "前情描述"}
            if key_path[0] not in WS_TOP_KEYS:
                soft.append((idx, f"world_state.{key_path_str}: 未知顶层键（键表: 焦点场景/轮次/时间/外部倒计时/全局标记/时间线/重置记录/叙事约定）"))
            elif len(key_path) >= 2 and key_path[0] == "时间" and key_path[1] not in WS_TIME_KEYS:
                soft.append((idx, f"world_state.{key_path_str}: 未知时间子键（键表: 基准时间/具体时间/时间流速比/前情描述）"))
            elif len(key_path) >= 2 and key_path[0] == "地点":
                soft.append((idx, f"world_state.{key_path_str}: 地点字段已废弃（当前区域→scene 区域关联·已探索区域→world_map 镜像·请勿再写）"))

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

        # ⑬ FILE 归属校验（硬性——防 FILE 标记错位导致字段写入错误文件）
        if key_path:
            if file_key == "conflicts":
                if not (key_path[0].startswith("CT-") or key_path[0] == PRESSURE_KEY):
                    hard.append((idx, f"{file_key}.{key_path_str}: conflicts 顶层键必须是 CT-XX 或 {PRESSURE_KEY}（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))
                elif len(key_path) >= 2:
                    # ⑭ CT 子键白名单（硬性·防编码损坏静默入库）：CT-XX 下仅允许八字段+事件线引用（+存量归档标记）
                    #   实测案例：PowerShell 管道把中文键损坏成 `????` → 被当新键静默创建；白名单使此类损坏当场爆炸
                    CT_SUB_KEYS = {"描述", "对抗双方", "被争夺资源", "关联角色", "关系状态", "内部状态", "相位", "紧迫度", "事件线引用", "状态"}
                    if key_path[1] not in CT_SUB_KEYS:
                        hard.append((idx, f"{file_key}.{key_path_str}: CT 子键 '{key_path[1]}' 不在键表（描述/对抗双方/被争夺资源/关联角色/关系状态/内部状态/相位/紧迫度/事件线引用/状态）——疑似编码损坏或字段漂移"))
                    # ⑮ CT 列表字段类型守卫（硬性·A）：关联角色/事件线引用 是 YAML 列表——只接受多行列表文本（逐行 '- 名字' / '[]'）的 KEY 全量覆盖；
                    #   单行文本会被当字符串覆盖整个列表（类型损坏）；###APPEND 对这两字段无安全追加路径（禁用）
                    elif key_path[1] in ("关联角色", "事件线引用"):
                        if append:
                            hard.append((idx, f"{file_key}.{key_path_str}: 禁用 ###APPEND（通用追加通道会把列表写成字符串）——用 ###KEY 全量覆盖为完整 YAML 列表（含保留项+新增项）"))
                        else:
                            try:
                                _items = yaml.safe_load(content)
                            except Exception:
                                _items = None
                            if not isinstance(_items, list):
                                hard.append((idx, f"{file_key}.{key_path_str}: 内容必须为多行 YAML 列表（逐行 '- 名字'）——单行文本会把列表覆盖成字符串（类型损坏）"))
                            # 软性（B·档案对账）：名单与 characters/CHAR_*.md 无唯一匹配 → 警告核对拼写（不拦·防跨世界命名差异误伤）
                            elif key_path[1] == "关联角色":
                                _chars_dir = world_dir / "characters"
                                if _chars_dir.is_dir():
                                    _stems = [p.stem[len("CHAR_"):] for p in sorted(_chars_dir.glob("CHAR_*.md"))]
                                    for _nm in dict.fromkeys(str(it).strip() for it in _items if str(it).strip()):
                                        if _nm in _stems:
                                            continue
                                        _hits = [s for s in _stems if _nm in s or s in _nm]
                                        if len(_hits) != 1:
                                            soft.append((idx, f"{file_key}.{key_path_str}: '{_nm}' 与 characters/ 档案无唯一匹配（{'候选: ' + '/'.join(_hits[:3]) if _hits else '无候选'}）——核对角色名拼写"))
            elif file_key.startswith(CHAR_STATE_PREFIX):
                CHAR_STATE_KEYS = {"自主性", "位置", "已知地点", "核心状态", "情绪", "压力水平", "防御有效性", "防御形态", "崩溃表现", "偏离登记", "人际动态", "决策状态", "decision", "信念演化", "记忆锚点", "反应轨迹", "连续行动轨迹", "名字"}
                if key_path[0] not in CHAR_STATE_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: CHAR_state 顶层键必须在键表内（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))
            elif file_key == "scene_state":
                SCENE_STATE_KEYS = {"核心状态", "场景时间线", "物理锚点", "道具", "关键场景信息", "出场角色摘要"}
                if key_path[0] not in SCENE_STATE_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: scene_state 顶层键必须在键表内（当前 '{key_path[0]}'）——疑似 FILE 标记错位/字段写入错误文件"))
            elif file_key == "direction":
                if key_path[0] not in DIRECTION_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: direction 顶层键必须在键表内（当前 '{key_path[0]}'·键表: {'/'.join(sorted(DIRECTION_KEYS))}）——疑似 FILE 标记错位/防镜像（焦点场景/CT紧迫度/拍序不得复制）"))
            elif file_key == "storylines":
                if key_path[0] not in STORYLINES_TOP_KEYS:
                    hard.append((idx, f"{file_key}.{key_path_str}: storylines 顶层键必须在键表内（当前 '{key_path[0]}'·键表: 故事弧线/事件线）——事件线读写走 ###STORYLINE（②编剧）"))

        # ⑬b 轨迹覆盖写检测（硬性——防覆盖写丢失历史：覆盖写必须保留旧值首末轮次标记·反应轨迹窗口由脚本裁剪·连续行动轨迹不裁剪但禁手动删块）
        # 重置豁免：该角色已登记重置（world_state.重置记录.{角色}）→ 按 loop_machinery §4 联动表清空/压缩重建，不拦
        if (file_key.startswith(CHAR_STATE_PREFIX) and key_path and key_path[0] in ("反应轨迹", "连续行动轨迹")
                and len(key_path) == 1 and not append and not force):
            _fp_r, _ = resolve_char_file(existing, file_key, world_dir)
            if _fp_r is not None:
                _stem = _fp_r.stem[len(CHAR_STATE_PREFIX):]
                if _stem.endswith("_state"):
                    _stem = _stem[:-len("_state")]
                if _stem in reset_chars:
                    continue
            old_val = (current.get(file_key, {}) or {}).get(key_path[0], "")
            if isinstance(old_val, str) and old_val.strip():
                old_marks = re.findall(r"第\s*\d+\s*轮\(", old_val)
                if old_marks:
                    first, last = old_marks[0], old_marks[-1]
                    if first not in content or last not in content:
                        hard.append((idx, f"{file_key}.{key_path[0]}: 覆盖写丢失历史——新内容必须保留旧值首末轮次标记（{first}…/{last}…）·窗口/压缩由机制执行·禁止手动删块"))

    # ① 行动卡四件套 + ①b 代价可核验 + ⑨ 角色档案存在（硬性·###ACTION——④角色阶段产物）
    COST_BLACKLIST = ("幻想", "安全感", "预期", "确定性", "耐性", "错觉", "安宁", "掌控感", "主动权", "节奏", "局面", "从容")
    for a_line in action_lines:
        a_show = a_line[:60]
        for token in ("驱动:", "情绪:", "强度:", "代价:"):
            if token not in a_line:
                hard.append((-1, f"###ACTION 缺「{token}」: {a_show}"))
                break
        m = re.search(r"代价:\s*(\S+)", a_line)
        if m and not m.group(1).strip():
            hard.append((-1, f"###ACTION 代价: 后为空（任一方无变化=本轮无冲突）: {a_show}"))
        cost_m = re.search(r"代价:\s*(.+?)(?:\s*\|\s*耗时:|$)", a_line)
        if cost_m:
            braces = re.findall(r"\{([^}]*)\}", cost_m.group(1))
            hit = [w for w in COST_BLACKLIST if any(w in b for b in braces)]
            if hit:
                hard.append((-1, f"###ACTION 代价含不可核验抽象词 {hit}——内部认知/无载体抽象词不算可核验变化（可核验枚举: 资源易主/载体状态变化/新增伤害/控制权易手/被迫选择/被迫承认/关系档位变化）: {a_show}"))
        rm = re.match(r"^\s*([^:|]+)[:：]", a_line)
        if rm:
            char_name = rm.group(1).strip()
            md_fp = world_dir / "characters" / f"CHAR_{char_name}.md"
            state_fp = world_dir / "states" / f"CHAR_{char_name}_state.yaml"
            if char_name and not md_fp.exists() and not state_fp.exists():
                resolved = None
                try:
                    for fp in world_dir.glob("characters/CHAR_*.md"):
                        full = fp.stem[len("CHAR_"):]
                        if char_name in full or full in char_name or full.replace(" ", "") == char_name.replace(" ", ""):
                            resolved = full
                            break
                except Exception:
                    pass
                if resolved:
                    soft.append((-1, f"###ACTION 角色 '{char_name}' 是简称，档案全名为 '{resolved}'——请用全名"))
                else:
                    hard.append((-1, f"###ACTION 角色 '{char_name}' 无档案（缺 CHAR_{char_name}.md——档案缺失=禁止该角色行动；若为简称请用档案全名）"))

    # ⑩⑪⑫ 阶段必含项（软性·查询轮/no-op 豁免；gate <阶段> --check 升级为硬拦）
    if ops and stage == "戏剧家":
        if not has_ct_op:
            soft.append((-1, "戏剧家批应含 ≥1 条 CT 推进/注册（conflicts.CT-XX）——查询轮豁免"))
        # 停滞旗标消费核验：旗标在场 → 本批必须写 conflicts.施压方向 且 ≠维持（加压兑现）
        _flags = _load_direction(world_dir).get("escalation_flags")
        if isinstance(_flags, dict) and any("停滞" in str(k) for k in _flags):
            _press_writes = [
                str(_content).strip()
                for _kind, _file_key, _key_path, _content, _append in ops
                if _kind == "write" and _file_key.strip().lower() == "conflicts"
                and _key_path.strip() == PRESSURE_KEY
            ]
            if not _press_writes:
                hard.append((-1, f"direction.escalation_flags.停滞 在场——本批必须写 conflicts.{PRESSURE_KEY}（四爆破方向四选一·加压兑现·停滞旗标当轮消化）"))
            elif all(v == "维持" for v in _press_writes):
                hard.append((-1, f"direction.escalation_flags.停滞 在场而 {PRESSURE_KEY}=维持——停滞轮禁标维持（四爆破方向四选一）"))
        # 施压方向枚举校验（本批写入值）
        for _kind, _file_key, _key_path, _content, _append in ops:
            if _kind == "write" and _file_key.strip().lower() == "conflicts" and _key_path.strip() == PRESSURE_KEY:
                _pv = str(_content).strip()
                if _pv and _pv not in PRESSURE_ENUM:
                    hard.append((-1, f"conflicts.{PRESSURE_KEY} '{_pv}' 非法（枚举: {'/'.join(PRESSURE_ENUM)}）"))
    elif ops and stage == "场记":
        for flag, msg in ((has_ws_time, "场记批应含 world_state.时间.具体时间 推进"),
                          (has_ws_round, "场记批应含 world_state.轮次 +1"),
                          (has_ws_summary, "场记批应含 world_state.前情描述（≤100字状态短语）"),
                          (has_scene_timeline, "场记批应含 scene_state.场景时间线 追加")):
            if not flag:
                soft.append((-1, msg + "——查询轮豁免"))
    elif stage == "编剧":
        if not storyline_lines:
            _sl_map = (_load_storylines(world_dir).get(STORYLINE_TOP_KEY) or {})
            if _sl_map:
                if ops and not any(("no-op" in m) or ("张力基调" in m) for m in meta_lines):
                    soft.append((-1, "编剧批应含 ###STORYLINE: 动作（add/rewrite N/close N/clear N）或 META 声明 no-op·张力基调——常态轮 no-op 豁免"))
            else:
                hard.append((-1, "storylines 空表而批次无建线动作——重路径触发（空表）：###STORYLINE: add 必含（建线/重规划·phase_storyliner 职责2）"))
    elif stage == "导演":
        _dr = _load_direction(world_dir)
        _writes_guidance = any(
            _kind == "write" and _file_key.strip().lower() == "direction" and "guidance" in _key_path.lower()
            for _kind, _file_key, _key_path, _content, _append in ops
        )
        if not str(_dr.get("guidance", "") or "").strip() and not _writes_guidance:
            hard.append((-1, "direction.guidance 为空且批次未写 guidance——③导演回判/guidance 未落盘（direction 核心三件之一）"))
        if ops and not beat_lines and not any("回判" in m for m in meta_lines):
            soft.append((-1, "导演批应含 ###BEAT: 动作（set/stay/advance）或 META 回判留痕（no-op 亦算）"))
        # 连续 stay 核验（无状态）：落盘前节拍决策已是「继续当前拍」而本批仍 stay → 必须写停滞旗标
        # （措辞不匹配=静默放过·退化为 phase_director 规则兜底·不误拦）
        if any(_b.startswith("stay") for _b in beat_lines) \
                and str(_dr.get("节拍决策", "") or "").strip().startswith("继续当前拍"):
            _flag_stay = any(
                _kind == "write" and _file_key.strip().lower() == "direction"
                and "escalation_flags" in _key_path
                and ("停滞" in _key_path or "停滞" in _content)
                for _kind, _file_key, _key_path, _content, _append in ops
            )
            if not _flag_stay:
                hard.append((-1, "连续第 2 轮 stay（上轮节拍决策=继续当前拍）——本批必须写 escalation_flags.停滞=待加压（①戏剧家次轮必须加压）"))
    elif stage == "角色":
        _char_writes = sum(
            1 for _kind, _file_key, _key_path, _content, _append in ops
            if _kind == "write" and _file_key.startswith(CHAR_STATE_PREFIX) and _file_key.endswith("_state")
        )
        if not action_lines and not _char_writes:
            hard.append((-1, "角色批既无 ###ACTION 行动卡也未更新任何 CHAR_state——④角色层零产出（焦内活跃角色即兴/焦外自推演至少落其一）"))
        elif ops and not action_lines and has_char_op:
            soft.append((-1, "角色批应含 ≥1 条 ###ACTION 行动卡（焦内活跃角色逐一即兴）"))
    elif ops and not stage:
        # 未声明阶段的兼容路径（迁移期维护批）：沿用综合检查
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

    # ⑬c 角色覆盖声明（硬性——角色批必须显式说明行动角色是否落到 CHAR_state）
    if has_char_op:
        coverage = _parse_role_coverage(meta_lines)
        reaction_roles = _action_roles(action_lines)
        submitted_roles = set()
        for _kind, _file_key, _key_path, _content, _append in ops:
            if _kind != "write" or not _file_key.startswith(CHAR_STATE_PREFIX) or not _file_key.endswith("_state"):
                continue
            _fp, _ = resolve_char_file(existing, _file_key, world_dir)
            if _fp is not None:
                submitted_roles.add(_fp.stem[len(CHAR_STATE_PREFIX):-len("_state")])
        if not coverage:
            hard.append((-1, "###META 缺少角色覆盖声明：角色批必须写 `角色覆盖: Name=更新,Other=更新(在轨·轻量)`"))
        else:
            for role in sorted(reaction_roles):
                normalized = role.replace("_", " ")
                status = coverage.get(normalized)
                if status is None:
                    hard.append((-1, f"角色覆盖声明缺少 ###ACTION 行动角色: {role}"))
                elif status.startswith("无变化"):
                    hard.append((-1, f"角色覆盖声明 {role}=无变化——「无变化」通道已废止（歧义=易执行为无反应冻结）：焦外角色一律自推演更新·在轨循环角色标 更新(在轨·轻量)"))
                elif status.startswith("更新") and normalized not in submitted_roles:
                    hard.append((-1, f"角色覆盖声明标记 {role}=更新，但批次缺 CHAR_state 写入"))
            for role in sorted(submitted_roles):
                if role not in {r.replace("_", " ") for r in coverage}:
                    hard.append((-1, f"CHAR_state 已写入但角色覆盖声明缺少: {role}"))

    # ⑭ 跨叙事提醒（软性——CROSS_NARRATIVES.md 存在时，完整推进轮应核对深匹配）
    if (world_dir / "story_architecture" / "CROSS_NARRATIVES.md").exists() and has_ct_op:
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
                has_anchor = any(
                    _k == "write" and _fk.startswith(CHAR_STATE_PREFIX) and _fk.endswith("_state")
                    and _kp == "记忆锚点"
                    and resolve_char_file(existing, _fk, world_dir)[0] is not None
                    and resolve_char_file(existing, _fk, world_dir)[0].stem[len(CHAR_STATE_PREFIX):-len("_state")] == role
                    for _k, _fk, _kp, _c, _a in ops
                )
                if not has_anchor:
                    hard.append((-1, f"###META 记忆✓ 留痕标 {role}:已触发·但批次缺该角色 ###APPEND: 记忆锚点"))

    # ⑬c-2 导演调度单点名角色覆盖（硬性——③调度单的 焦内活跃/背景/焦外 cast 必须被角色覆盖声明）
    # 复用 角色覆盖 对账：调度单命名的已知角色 = 更新(→CHAR_state 写) 或 更新(在轨·轻量)(→CHAR_state 写)；
    # 「无变化」通道废止（歧义=易执行为无反应冻结）；未覆盖 → 拦。
    if stage == "角色" and (has_char_op or any("角色覆盖" in (ln or "") for ln in meta_lines)):
        sched_roles = _schedule_cast_roles(world_dir)
        if sched_roles:
            coverage2 = _parse_role_coverage(meta_lines)
            submitted2 = set()
            for _kind, _fk, _kp, _c, _a in ops:
                if _kind == "write" and _fk.startswith(CHAR_STATE_PREFIX) and _fk.endswith("_state"):
                    _fp, _ = resolve_char_file(existing, _fk, world_dir)
                    if _fp is not None:
                        submitted2.add(_fp.stem[len(CHAR_STATE_PREFIX):-len("_state")])
            for role in sorted(sched_roles):
                status = coverage2.get(role)
                if status is None:
                    hard.append((-1, f"角色覆盖声明缺少调度单点名角色: {role}（③调度单点名·④自推演后在同批更新 CHAR_state）"))
                elif status.startswith("无变化"):
                    hard.append((-1, f"角色覆盖声明 {role}=无变化——「无变化」通道已废止：④为其自推演更新 CHAR_state·在轨循环角色标 更新(在轨·轻量)"))
                elif status.startswith("更新") and role not in submitted2:
                    hard.append((-1, f"角色覆盖声明标记 {role}=更新，但批次缺 CHAR_state 写入"))

    return hard, soft


def cmd_audit(world_dir):
    """audit: 校验 stdin 的阶段批次草案（###STAGE/###FILE/###KEY/###APPEND 格式），不落盘。
    硬性违规 → 列出全部并 exit 1（草案不合格）；仅软性警告 → 打印警告，exit 0（可写入）。"""
    raw_stdin = sys.stdin.buffer.read().decode("utf-8")
    ctx = parse_batch_entries(raw_stdin.split("\n"))
    ops, parse_errors = ctx["ops"], ctx["errors"]
    if raw_stdin.strip() and not ctx["stage"]:
        parse_errors.append("###STAGE 缺失——批次首行须为 `###STAGE: <阶段名>`；若首行看似正确仍报此错，检查文件是否带 BOM/编码损坏")
    hard, soft = check_batch(ops, world_dir, ctx, enforce_scene_dir=False)
    if ctx["stage"]:
        print(f"[AUDIT] ###STAGE 回显: {ctx['stage']}", file=sys.stderr)
    if ctx["storyline"]:
        print(f"[AUDIT] ###STORYLINE 回显: {ctx['storyline'][0][0]}", file=sys.stderr)
    if ctx["beat"]:
        print(f"[AUDIT] ###BEAT 回显: {ctx['beat'][0]}", file=sys.stderr)
    if ctx["action"]:
        sched = ctx["schedule"][0] if ctx["schedule"] else "（无）"
        print(f"[AUDIT] ###ACTION 回显: {len(ctx['action'])} 条行动卡 · SCHEDULE: {sched}", file=sys.stderr)
    if ctx["meta"]:
        print(f"[AUDIT] ###META 回显: {ctx['meta'][0]}", file=sys.stderr)
        if "记忆" not in ctx["meta"][0]:
            soft.append((0, "###META 静默自查锚点缺少 记忆✓ 槽（记忆✓=逐角色同类计数留痕·每出场角色必列·见 phase_actor.md）"))
    else:
        soft.append((0, "未检测到 ###META: 静默自查锚点——阶段批次必写（###STAGE 之后）：各阶段格式见 phase_*.md（查询轮/维护轮豁免）"))
    # scene_state 落点软提示（预检路径·场景目录由场记阶段3 init_scene 创建·先于批次写入）
    for _idx, _msg in soft:
        if _idx != -1 and "预检软提示" in _msg:
            print(f"[AUDIT] 软性提示: {_msg}", file=sys.stderr)
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
        for cfp in sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
            try:
                cdata = yaml.safe_load(cfp.read_text(encoding="utf-8")) or {}
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
        ws_fp = world_dir / "states" / "world_state.yaml"
        if ws_fp.exists():
            ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8")) or {}
            focus = str(ws.get("焦点场景") or "").strip()
            if focus and scene_dir and not scene_dir.name.startswith(focus):
                warnings.append(f"焦点场景 '{focus}' 与当前场景目录 '{scene_dir.name}' 不一致")
        # CT 键格式
        c_fp = world_dir / "states" / "conflicts.yaml"
        if c_fp.exists():
            cdata = yaml.safe_load(c_fp.read_text(encoding="utf-8")) or {}
            for k in cdata:
                if not re.match(r"^CT-\d{2}$", str(k)):
                    extra = "（v0.11 节拍表残留·先 migrate）" if str(k) == BEAT_TOP_KEY else ""
                    warnings.append(f"conflicts.yaml: 顶层键 '{k}' 不符合 CT-XX 格式{extra}")
    except Exception:
        pass
    if warnings:
        print(f"[VALIDATE] 写入完成，{len(warnings)} 个内容警告待处理（详细列表运行 validate 查看）", file=sys.stderr)
        for w in warnings[:5]:
            print(f"  - {w}", file=sys.stderr)
        if len(warnings) > 5:
            print(f"  …等 {len(warnings) - 5} 条", file=sys.stderr)


def cmd_write_raw(world_dir: Path, extra: list[str], batch: bool = False, append_mode: bool = False, dry_run: bool = False, force: bool = False):
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
    --force（显式回退专用·仅 --batch）：绕过 audit ④ 轮次单调 与 ⑬b 反应轨迹覆盖写——回退手工重建（无快照）时用；
    其余数据完整性硬性检查（① 角色反应四件套/② 载体/⑤ scene_state 落点）照常拦截。回退后必做残留扫描 + validate。
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
        if filepath is None and file_key == "pending_actions":
            # pending_actions：缺失时按模板建（对齐 init_scene·保证焦外记录层可写）
            filepath = pending_actions_path(scene_dir, create=True)
            if filepath is None:
                print("[ERR] pending_actions 创建失败（缺场景目录或写盘失败）", file=sys.stderr)
                return False
        elif filepath is None:
            # scene_state 解析失败：准确诊断焦点场景目录/文件状态（避免「未知文件 key」误导为 FILE key 写错）
            if file_key == "scene_state":
                if scene_dir is None:
                    print("[ERR] scene_state 落点错误: 无法定位当前焦点场景目录——先确认 world_state.焦点场景 后再写入", file=sys.stderr)
                elif not (scene_dir / "scene_state.yaml").exists():
                    print(f"[ERR] scene_state 落点错误: 焦点场景目录/文件不存在（{scene_dir}）——先执行 init_scene 创建场景（scene_card/start_snapshot/INDEX ACTIVE）后再写入", file=sys.stderr)
            else:
                print(f"[ERR] 未知文件 key: {file_key}", file=sys.stderr)
            return False
        if note:
            print(note, file=sys.stderr)

        if filepath.name == "world_map.yaml":
            print("[ERR] world_map 禁用点路径写入（键名可含空格/点·点路径与 shell 分词均不支持）——请用 write 命令（YAML diff 合并·含单字段更新）", file=sys.stderr)
            return False

        if filepath.exists():
            try:
                data = yaml.safe_load(filepath.read_text(encoding="utf-8")) or {}
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
        # 结构化累积字段（记忆锚点/信念演化/偏离登记/已知地点/伏笔/连续行动轨迹/场景时间线/道具）：
        #   append 时追加为 yaml 列表元素——轮次/时间/线索 开头或 已知地点「- 地点名」或 道具「- ID:」
        STRUCTURED_APPEND_FIELDS = {"记忆锚点", "信念演化", "偏离登记", "已知地点", "伏笔", "连续行动轨迹", "场景时间线", "道具"}
        is_structured_field = ((file_key.startswith(CHAR_STATE_PREFIX) or file_key in ("foreshadow", "scene_state"))
                               and leaf in STRUCTURED_APPEND_FIELDS)
        if leaf == "已知地点":
            is_list_item_content = bool(re.match(r"^\s*-\s+", content))
        else:
            is_list_item_content = bool(re.match(r"^\s*-\s*(?:轮次|时间|线索|ID)[:：]", content))
        if append and is_structured_field and not is_list_item_content:
            print(f"[ERR] {file_key}.{'.'.join(key_path)} 结构化字段追加需列表元素格式（- 轮次:…/- 时间:…/- ID:…/地点名）——旧字符串格式（· 连接/表格行）不再接受·拒绝写入（防把结构化列表替换成字符串）", file=sys.stderr)
            return False
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
            if isinstance(existing_val, str):
                # 模板占位残留（templates/CHAR_state.yaml 骨架占位·如 '[我知道哪些地方（去过/被告知/目睹）]'）——视为空·不混入列表
                if re.fullmatch(r"\s*\[[^\]]*\]\s*", existing_val):
                    existing_val = []
                else:
                    existing_val = [{"轮次": "", "内容": ent.strip()}
                                    for ent in re.split(r"\n\s*(?:·\s*)?(?=\[)", existing_val)
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
                    elif leaf == "连续行动轨迹":
                        if (str(e.get("轮次", "")) == str(item.get("轮次", ""))
                                and str(e.get("行动", "")) == str(item.get("行动", ""))):
                            dup = True
                            break
                    elif leaf == "场景时间线":
                        if (str(e.get("轮次", "")) == str(item.get("轮次", ""))
                                and str(e.get("时间", "")) == str(item.get("时间", ""))):
                            dup = True
                            break
                    elif leaf == "道具" and str(e.get("ID", "")) == str(item.get("ID", "")):
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
            if file_key.startswith(CHAR_STATE_PREFIX) and leaf == "连续行动轨迹" and len(existing_val) > TRAJECTORY_WINDOW:
                existing_val = existing_val[-TRAJECTORY_WINDOW:]
                print(f"[TRIM] {file_key}.连续行动轨迹 已自动裁剪至最近 {TRAJECTORY_WINDOW} 轮（窗口滚动·删最旧块）", file=sys.stderr)
            target[leaf] = existing_val
            write_yaml(filepath, data)
            print(f"[OK] {file_key}.{'.'.join(key_path)} 已追加 {len(new_items)} 条结构化元素", file=sys.stderr)
            return True
        if append and leaf in target and isinstance(target[leaf], str) and target[leaf]:
            existing_val = target[leaf]
            # 模板占位残留（templates/CHAR_state.yaml 骨架占位·如 '[最近5轮动作序列…]'）——视为空·不当前缀
            if re.fullmatch(r"\s*\[[^\]]*\]\s*", existing_val):
                existing_val = ""
            # 重复追加检测（硬防护·防同一批次重放/同一内容重复追加）：
            # 批次重放时 content 完全一致，必然作为子串存在于字段值中 → 跳过
            elif content.strip() and content.strip() in existing_val:
                print(f"[SKIP] {file_key}.{'.'.join(key_path)} 重复追加已跳过（内容已存在——同一批次只执行一次，禁止重放 write 命令验证）", file=sys.stderr)
                return True
            target[leaf] = (existing_val.rstrip("\n") + "\n" if existing_val else "") + content
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
            # 映射/列表多行内容自动解析（2026-08-17 加入·方案A）：多行 YAML 块（嵌套映射/列表）解析为 dict/list 再写入——
            #   修复「嵌套记录字段（重置记录.{角色}/时间线.{ID}/外部倒计时.{CD}/已探索区域.{区域}）被写成字符串·读取端读不到」；
            #   单行标量保持字符串（防 轮次/时间 等类型漂移）；解析失败/无结构（场景时间线等字符串块）按原字符串
            if "\n" in content:
                try:
                    _parsed = yaml.safe_load(content)
                except Exception:
                    _parsed = None
                if isinstance(_parsed, (dict, list)):
                    content = _parsed
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
        ctx = parse_batch_entries(lines)
        ops, parse_errors = ctx["ops"], ctx["errors"]
        hard, soft = check_batch(ops, world_dir, ctx, force=force)
        blocked = {idx for idx, _ in hard}
        if ctx["stage"]:
            print(f"[AUDIT] ###STAGE 回显: {ctx['stage']}", file=sys.stderr)
        if ctx["storyline"]:
            print(f"[AUDIT] ###STORYLINE 回显: {ctx['storyline'][0][0]}", file=sys.stderr)
        if ctx["beat"]:
            print(f"[AUDIT] ###BEAT 回显: {ctx['beat'][0]}", file=sys.stderr)
        if ctx["action"]:
            sched = ctx["schedule"][0] if ctx["schedule"] else "（无）"
            print(f"[AUDIT] ###ACTION 回显: {len(ctx['action'])} 条行动卡 · SCHEDULE: {sched}", file=sys.stderr)
        if ctx["meta"]:
            print(f"[AUDIT] ###META 回显: {ctx['meta'][0]}", file=sys.stderr)
        else:
            print("[AUDIT] 软性警告: 未检测到 ###META: 静默自查锚点——阶段批次必写（查询轮/维护轮豁免）", file=sys.stderr)
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
                if fp is None and file_key == "pending_actions":
                    fp = pending_actions_path(get_scene_dir(world_dir), create=False)
                if fp is None:
                    unknown_keys += 1
                    print(f"  [ERR] 未知文件 key: {file_key}（dry-run 拦截·实写将拒绝该字段）")
                    continue
                old_val = None
                if fp.exists():
                    try:
                        d = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
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

        # ── ###STORYLINE / ###BEAT 自动执行（结构/指针落盘·失败拦批——LLM 不手动调用）──
        for action, payload in ctx["storyline"]:
            parts = action.split()
            if not parts or parts[0] not in ("add", "rewrite", "close", "clear"):
                print(f"[FAIL] ###STORYLINE 动作非法: {action!r}（合法: add / rewrite N / close N / clear N——结构动作·②编剧）——批次拦截", file=sys.stderr)
                sys.exit(1)
            stdin_text = "\n".join(payload) if payload is not None else None
            try:
                cmd_storyline(world_dir, parts, stdin_text=stdin_text)
            except SystemExit as e:
                print(f"[FAIL] ###STORYLINE 执行失败: {action}（exit {e.code}）——storylines 未更新·批次拦截·修正后重提", file=sys.stderr)
                sys.exit(1)
        for action in ctx["beat"]:
            parts = action.split()
            try:
                cmd_beat(world_dir, parts)
            except SystemExit as e:
                print(f"[FAIL] ###BEAT 执行失败: {action}（exit {e.code}）——direction 指针未更新·批次拦截·修正后重提", file=sys.stderr)
                sys.exit(1)

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
        # 结构/指针落盘结果置于收尾（tail 可见·无需重放批次确认）
        if ctx["storyline"] or ctx["beat"]:
            print("[OK] ###STORYLINE/###BEAT 已自动执行（storylines 结构 / direction 指针·本轮事件线动作）", file=sys.stderr)
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
        hint = ""
        try:
            raw = sys.stdin.buffer.read()
            if raw.strip():
                if b"###FILE:" in raw or b"###KEY:" in raw:
                    hint = "检测到 ###FILE:/###KEY: 记录格式——记录式批量请用 write-raw --batch（stdin 直通·中文编码安全）"
                else:
                    hint = "检测到整份 YAML 输入——整份覆盖请用 write --full（stdin YAML）；增量合并用 write"
        except Exception:
            hint = ""
        msg = f"[ERR] 用法: worldctl.py <世界> {'append-raw' if append_mode else 'write-raw'} <文件key> <YAML键路径> [内容]"
        if hint:
            msg += "\n       " + hint
        print(msg, file=sys.stderr)
        sys.exit(1)

    file_key = extra[0]
    key_path_str = extra[1]

    # 内容：CLI 参数优先，否则 stdin
    if len(extra) >= 3:
        content = extra[2]
        if not content.isascii():
            print("[ERR] 单字段模式仅限短 ASCII 值——中文/多行内容经 CLI 参数会随 locale 解码损坏文件，请用 write-raw --batch（stdin 直通·唯一编码安全通道）", file=sys.stderr)
            sys.exit(1)
    else:
        content = _read_stdin_utf8()

    if not append_mode and content == "":
        print(f"[ERR] 空值覆盖已拒绝: {file_key}.{key_path_str}（write-raw 值不能为空；追加请用 append-raw）", file=sys.stderr)
        sys.exit(1)

    if not write_one(file_key, key_path_str, content, append=append_mode):
        sys.exit(1)

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

    if filepath.name == "world_map.yaml":
        print("[ERR] world_map 禁用点路径删除（键名可含空格/点·点路径与 shell 分词均不支持）——请用 write 命令（YAML diff 合并）", file=sys.stderr)
        return

    if not filepath.exists():
        print(f"[WARN] {file_key} 文件不存在，无需删除", file=sys.stderr)
        return

    try:
        data = yaml.safe_load(filepath.read_text(encoding="utf-8")) or {}
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
            text = fp.read_text(encoding="utf-8", errors="replace")
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
            # --live: 排除 narrative 轮转归档（narrative.<时间戳>.md 或 narrative.r{轮次}.<时间戳>.md）与 archive 目录
            if re.search(r"narrative\.\d{8}_\d{6}\.md$", fp.name) or re.search(r"narrative\.r\d+\.\d{8}_\d{6}\.md$", fp.name):
                continue
            if "archive" in fp.parts:
                continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
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


def _climax_principals(line: dict | None) -> list[str]:
    """读事件线顶点拍的 顶点约束.关系主体。无顶点约束 → []。"""
    if not isinstance(line, dict):
        return []
    for b in (line.get("拍序") or []):
        if isinstance(b, dict) and str(b.get("拍名", "") or "").strip() == "顶点" and isinstance(b.get(CLIMAX_CONSTRAINT_KEY), dict):
            cons = b[CLIMAX_CONSTRAINT_KEY]
            return [str(x).strip() for x in (cons.get("关系主体") or []) if str(x).strip()]
    return []


def _climax_baseline_snapshot(world_dir: Path, sl_id: str, line: dict | None = None) -> dict:
    """快照 顶点约束.关系主体 的 CHAR_state 声明维度字段（进入顶点拍时记录·顶点拍起点状态）。
    仅关系主体（外部爆破者=压力供应方·其自身状态变化不计入出线——防"改旁观者凑验收"）。
    返回 {角色名: {字段: 基准值}}——无约束/无状态文件时返回空 dict（出线时拦）。"""
    principals = _climax_principals(line)
    if not principals:
        return {}
    existing = discover_files(world_dir, get_scene_dir(world_dir))
    snap: dict[str, dict] = {}
    for s in principals:
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
        snap[s] = {f: _char_state_field_value(st, f) for f in SUBSTANTIVE_FIELDS}
    return snap


def _snapshot_climax_baseline(line: dict, world_dir: Path, n: str) -> None:
    """进入顶点拍时，自动快照 顶点约束.关系主体 的实质状态字段为 基准快照（脚本自动·LLM 不填不读）。
    落档 states/.climax_baseline_{SL}.yaml（脚本私有·不进 storylines 与任何读取面——对比面不预声明）。"""
    snap = _climax_baseline_snapshot(world_dir, n, line)
    _climax_baseline_fp(world_dir, n).write_text(
        yaml.dump(snap, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8", newline="")


def _norm_sl_id(n) -> str:
    """事件线 id 归一化：纯数字 N / SL-N → SL-XX（两位）。"""
    s = str(n).strip()
    m = re.match(r"^(?:SL-)?(\d+)$", s, re.IGNORECASE)
    if m:
        return f"{STORYLINE_ID_PREFIX}{int(m.group(1)):02d}"
    return s


def _load_storylines(world_dir: Path) -> dict:
    fp = world_dir / "states" / STORYLINES_FILE
    if not fp.exists():
        return {}
    try:
        data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_direction(world_dir: Path) -> dict:
    fp = world_dir / "states" / DIRECTION_FILE
    if not fp.exists():
        return {}
    try:
        data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_direction(world_dir: Path, dr: dict):
    write_yaml(world_dir / "states" / DIRECTION_FILE, dr)


def _check_climax_exit(world_dir: Path, ops, beat_lines) -> tuple[list[str], bool]:
    """顶点出线核验（硬性·gate director --check 调用·收束需要证明）：
    批次声明 `###BEAT: advance SL-XX 余波` 且 direction 当前拍=顶点 时——
    ① 顶点约束齐备（关系主体≥2/核心张力/变化维度合法/非玩家爆破≥1·缺=拦）；
    ② 基准快照存在（进入顶点拍时脚本自动记录·缺=拦）；
    ③ 关系主体的声明维度字段任一实质变化（≠基准快照·当前文件+批次写 op 预演·来源不限——主体选择/对手/
       外部爆破/世界事件皆可）——主体全无变化=顶点未落地（拦·撤回③导演）。
    验收=关系主体的声明维度发生实质变化（任一来源）；外部爆破者为加压力量·不参与验收。
    返回 (违规消息列表, 是否执行了核验)。"""
    violations: list[str] = []
    checked = False
    if not beat_lines:
        return violations, checked
    sl_id = None
    for bl in beat_lines:
        m = re.match(r"^advance\s+(\S+)\s+余波\s*$", str(bl).strip())
        if m:
            sl_id = _norm_sl_id(m.group(1))
            break
    if sl_id is None:
        return violations, checked
    checked = True
    # direction：当前事件线/当前拍=顶点 才核验（非顶点出线不拦截）
    dr = _load_direction(world_dir)
    if str(dr.get("当前事件线", "") or "").strip() != sl_id:
        return violations, checked
    if str(dr.get("当前拍", "") or "").strip() != "顶点":
        return violations, checked
    # storylines：读事件线与顶点约束
    st = _load_storylines(world_dir)
    line = (st.get(STORYLINE_TOP_KEY) or {}).get(sl_id)
    if not isinstance(line, dict):
        violations.append(f"顶点出线（advance {sl_id} 余波）失败——storylines 无事件线 {sl_id}")
        return violations, checked
    cons = None
    for b in (line.get("拍序") or []):
        if isinstance(b, dict) and str(b.get("拍名", "") or "").strip() == "顶点":
            cons = b.get(CLIMAX_CONSTRAINT_KEY)
            break
    if not isinstance(cons, dict):
        violations.append(f"顶点出线（advance {sl_id} 余波）缺 顶点约束（Vertex Constraint——关系主体/核心张力/变化维度/非玩家爆破·建线/换线时预填·旧字段 顶点落点 需 rewrite）")
        return violations, checked
    principals = [str(x).strip() for x in (cons.get("关系主体") or []) if str(x).strip()]
    if len(set(principals)) < 2:
        violations.append("顶点约束.关系主体 需 ≥2 去重角色（顶点的单位是关系不是单人·不区分玩家/NPC）")
        return violations, checked
    if not str(cons.get("核心张力", "") or "").strip():
        violations.append("顶点约束.核心张力 为空（必须被推至临界的未决问题·点名赌注所在）")
        return violations, checked
    dims = [str(d).strip() for d in (cons.get("变化维度") or []) if str(d).strip()]
    bad_dims = [d for d in dims if d not in DIM_ENUM]
    if not dims or bad_dims:
        violations.append(f"顶点约束.变化维度 非法（{bad_dims or '空'}——枚举: {'/'.join(DIM_ENUM)}）")
        return violations, checked
    blasters = [str(x).strip() for x in (cons.get("非玩家爆破") or []) if str(x).strip()]
    if not blasters:
        violations.append("顶点约束.非玩家爆破 为空（≥1 外部角色或事件——压力供应方：主体全静止时逼上悬崖的力量·防死锁）")
        return violations, checked
    # 基准快照（脚本私有落档·进入顶点拍时自动记录）——缺则拦
    baseline = _load_climax_baseline(world_dir, sl_id)
    if not isinstance(baseline, dict) or not baseline:
        violations.append(f"顶点基线未建档（beat set/advance 进入顶点拍时脚本自动落档）·先 stay {sl_id}·建档后再出线")
        return violations, checked
    # 预演比较：关系主体的实质状态字段任一 ≠ 基准 = 真实变化发生（任一来源·比对面=脚本层常量·不预声明）
    existing = discover_files(world_dir, get_scene_dir(world_dir))
    changed_any = False
    detail: list[str] = []
    for side, base_fields in baseline.items():
        if not isinstance(base_fields, dict):
            continue
        key = f"{CHAR_STATE_PREFIX}{side}{CHAR_STATE_SUFFIX}".removesuffix(".yaml")
        fp2, _ = resolve_char_file(existing, key, world_dir)
        cur: dict = {}
        if fp2 is not None and fp2.exists():
            try:
                d2 = yaml.safe_load(fp2.read_text(encoding="utf-8")) or {}
                cur = d2 if isinstance(d2, dict) else {}
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
                detail.append(f"{side}.{field}: {base!r} → {val!r}")
    if not changed_any:
        violations.append(
            f"顶点未落地——演出未产生足以证明临界达成的真实改变（基线比对未通过）·留顶点（###BEAT: stay {sl_id}）·非玩家爆破可加压；判线作废则 ###STORYLINE: rewrite {sl_id} 重声明 顶点约束"
        )
    else:
        print("[GATE] 顶点出线核验通过（收束证明成立）", file=sys.stderr)
    return violations, checked


def _load_audit_words(world_dir: Path) -> tuple[set, list, set]:
    """W4 词表加载（世界级配置·可移植性修复）：worlds/{世界}/audit_words.yaml 优先，缺省用内置通用词表。
    返回 (锚点词集, 位置冲突模式 [(正则, [冲突词])], 豁免专名集)。"""
    default_anchor = {"门", "窗", "床", "楼梯", "钢琴", "吧台", "暗门", "金库", "后厨", "油灯",
                      "纸玫瑰", "大门", "正门", "散桌", "房间", "门帘", "教堂", "月台", "墙根",
                      "柜台", "长椅", "地窖", "盖板", "楼梯口", "窗户", "酒杯", "筷子"}
    default_loc = [
        ("二楼", ["楼下", "一楼", "下楼", "走上楼去弹"]),
        ("一楼", ["楼上", "二楼", "上楼"]),
        ("吧台后", ["门外", "街上"]),
        ("后厨", ["二楼"]),
        ("门口", ["楼上"]),
    ]
    default_known = {
        "Guest", "Mesa", "QA", "游客", "便衣", "灰衣", "前门便衣",
        "Westworld", "Sweetwater", "Mariposa", "Delos", "Welcome", "Center",
        "Host", "Hosts", "Smart", "Ammo", "Mesa Hub", "The Maze", "Maze",
    }
    fp = world_dir / "audit_words.yaml"
    if fp.exists():
        try:
            data = yaml.safe_load(fp.read_text(encoding="utf-8")) or {}
            if isinstance(data, dict):
                anchor = {str(w) for w in (data.get("锚点词") or [])} or default_anchor
                loc = [tuple(x) for x in (data.get("位置冲突") or []) if isinstance(x, list) and len(x) == 2] or default_loc
                known = {str(w) for w in (data.get("豁免专名") or [])} or default_known
                return anchor, loc, known
        except Exception:
            pass
    return default_anchor, default_loc, default_known


def cmd_gate(world_dir: Path, extra: list[str], check_mode: bool = False):
    """gate: 六阶段流程闸门——各阶段批次出口核验。
    用法: worldctl.py <世界> gate dramatist|storyliner|director|actor|keeper|writer [--check]
    - 无 --check: 输出该阶段人工审计清单，要求逐项作答（通过/不通过/跳过+证据）。
    - 带 --check: 批次类从 stdin 读该阶段批次（###STAGE 声明），运行可代码化检查——
      Single Writer 越权（硬）+ 阶段必含项（soft→硬拦）+ 字段级硬性检查（同一 check_batch 引擎）；
      director 另跑顶点出线核验；writer 读叙事跑 W4 锚点/人物存在性核验。不合格 exit 1。"""
    phase = extra[0] if extra else ""
    PHASE_CN = {"dramatist": "戏剧家", "storyliner": "编剧", "director": "导演",
                "actor": "角色", "keeper": "场记", "writer": "作家"}
    CHECKLISTS = {
        "dramatist": [
            "D1 冲突推进: ≥1 条 CT 推进/注册（推进池非空）",
            "D2b 施压方向: conflicts.施压方向 已写（死局两难/防御踩爆/关系撕裂/不可逆代价/维持——施压瞄准·停滞旗标在场时禁维持）",
            "D2 代价: CT 对抗双方可核验变化（资源易主/控制权易手/新增伤害/被迫选择/关系档位）",
            "D3 实质推进: 对抗加码或重大转折（冷却不写弱）",
            "D4 抽象方: 显现机制+本轮出手形态+抵抗痕迹",
            "D5 循环轨道: 偏离检测（决策/行动 vs LOOPS 基线）+冲突化+兜底",
        ],
        "storyliner": [
            "S1 戏剧问题: 每拍有边界可回答（禁无界持续描述）",
            "S2 顶点约束: 关系主体≥2 + 核心张力点名赌注所在 + 变化维度 + 非玩家爆破≥1（外部加压·防死锁）",
            "S3 弧线对照: SETTING 故事弧线/张力基调",
            "S4 LOOPS 融入: 在轨节拍并入结构（无来源标记）",
        ],
        "director": [
            "R1 回判: 上轮结果 vs 当前拍戏剧问题（十问·含意外事件）",
            "R2 承接判断: 当前拍继续的理由或进入下一拍的理由（已写入 direction）",
            "R3 演出状态: 上升/持续/转折/收束/停滞（停滞→escalation flag）",
            "R4 guidance: 问题+张力方向·禁预写角色行动",
            "R5 场景切换: 物理变化/跨天必切（机械规则）",
        ],
        "actor": [
            "A1 行动卡四件套: ###ACTION 驱动/情绪/强度/代价（audit ①①b）",
            "A2 反顺从五则: 代价前置/档案强度/抽象方显现/认知闸门/VB 升级路径",
            "A3 认知上限: 循环档位速查（脚本/漂移/觉醒/变质·元视角禁令）",
            "A4 用户角色: 行动资格=仅用户输入·禁引擎代笔定性抉择",
            "A5 记忆: 入锚写前五步 + 角色覆盖/记忆✓ 留痕",
        ],
        "keeper": [
            "K1 场景事实: 场景时间线/出场摘要（集合索引）/道具锚点线索",
            "K2 世界事实: 时间/轮次/前情/倒计时走表",
            "K3 落点: 焦点场景目录（world_state.焦点场景 唯一权威）",
            "K4 轮完整: round-check 收尾",
            "K5 Single Writer: 场记批不写 CHAR_state（角色意志文件·唯一写者=④角色）",
        ],
        "writer": [
            "W1 POV 过滤: 单镜头·只写 POV 感知·焦外不进正文",
            "W2 代价在纸上 + 特异性（换人测试）",
            "W3 一致性: 行动卡骨架如实呈现·行为偏移落地不解释来源",
            "W4 锚点约束: 元素/人物存在性（代码化核对）",
        ],
    }
    if phase not in PHASE_CN:
        print("用法: worldctl.py <世界> gate dramatist|storyliner|director|actor|keeper|writer [--check]", file=sys.stderr)
        print("  dramatist/storyliner/director/actor/keeper: 阶段批次闸门（stdin=该阶段 ###STAGE 批次）", file=sys.stderr)
        print("  writer: 叙事输出闸门（stdin=叙事正文·W4 代码化核验）", file=sys.stderr)
        print("  --check: 运行可代码化硬性核验，不合格 exit 1", file=sys.stderr)
        sys.exit(1)

    stage_cn = PHASE_CN[phase]
    print("=" * 60, file=sys.stderr)
    print(f"[GATE] {stage_cn}阶段出口闸门（独立审计·默认不通过·逐项找茬）", file=sys.stderr)
    for line in CHECKLISTS[phase]:
        print("  " + line, file=sys.stderr)
    print("  输出格式: 逐项 {通过|不通过|跳过}+证据 → 全部通过才进下一阶段", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    if not check_mode:
        return

    if phase == "writer":
        if check_mode:
            raw = sys.stdin.buffer.read().decode("utf-8")
            if not raw.strip():
                print("[GATE] 未提供叙事（stdin 为空）——W1/W3 无法代码化核验，请人工逐项作答", file=sys.stderr)
                return
            # W4 可代码化部分（与 write_narrative.py 同一套逻辑）：叙事「」内专名若命中锚点词，
            # 必须与注册名有完整包含关系；位置型锚点核对叙事同语境无矛盾位置词
            registered = {}
            scenes_dir = world_dir / "scenes"
            if scenes_dir.is_dir():
                for sdir in sorted(scenes_dir.iterdir()):
                    ssp = sdir / "scene_state.yaml"
                    if ssp.exists():
                        try:
                            sdata = yaml.safe_load(ssp.read_text(encoding="utf-8"))
                        except Exception:
                            continue
                        if not isinstance(sdata, dict):
                            continue
                        for fld in ("物理锚点", "道具"):
                            val = sdata.get(fld)
                            if not val:
                                continue
                            if isinstance(val, list):
                                for it in val:
                                    if isinstance(it, dict) and str(it.get("名称", "") or "").strip():
                                        # 注册名称+描述（W4 包含关系匹配·desc=位置/状态）
                                        registered.setdefault(str(it["名称"]).strip(),
                                                              f"{str(it.get('位置', '') or '').strip()} {str(it.get('状态', '') or '').strip()}")
                                continue
                            for line in str(val).splitlines():
                                line = line.strip()
                                m = re.match(r"^(?:\d+\.\s*|[A-Z]+\d*\s+|[·\-]\s*)?([^:：—]+?)\s*[:：—]\s*(.*)$", line)
                                if m:
                                    registered.setdefault(m.group(1).strip(), m.group(2).strip())
                                pm = re.match(r"^\|\s*P\d+\s*\|\s*([^|]+)\s*\|\s*([^|]*)\s*\|", line)
                                if pm:
                                    registered.setdefault(pm.group(1).strip(), pm.group(2).strip())
            anchor_words, LOC_PATTERNS, KNOWN_NO_CHAR = _load_audit_words(world_dir)
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
            for fp in world_dir.glob("characters/CHAR_*.md"):
                stem = fp.stem[len("CHAR_"):].strip()
                if stem:
                    char_md_names.add(stem)
            # 豁免：非角色专名（场景/组织/道具/系统）+ Guest/玩家 + 已知无档案的叙事称谓
            # 词表来源=audit_words.yaml（缺省内置通用词表·见 _load_audit_words）
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
            print("[GATE] 回合收尾提醒（静默模式）：正文只含叙事·回合结束零正文输出（状态摘要/执行汇报/叙事复述/下一步引导一律禁止）", file=sys.stderr)
            return

    # ── 批次类闸门（dramatist/storyliner/director/actor/keeper）──
    raw = sys.stdin.buffer.read().decode("utf-8")
    if not raw.strip():
        print(f"[GATE] 未提供 {stage_cn} 批次（stdin 为空）——闸门拦截：不进下一阶段", file=sys.stderr)
        sys.exit(1)
    ctx = parse_batch_entries(raw.split("\n"))
    ops, parse_errors = ctx["ops"], ctx["errors"]
    if ctx["stage"] != stage_cn:
        print(f"[GATE] ###STAGE 缺失或与阶段不匹配（声明={ctx['stage'] or '无'}·期望={stage_cn}）——批次首行须为 `###STAGE: {stage_cn}`；若首行看似正确仍报此错，检查文件是否带 BOM/编码损坏", file=sys.stderr)
        sys.exit(1)
    hard, soft = check_batch(ops, world_dir, ctx, enforce_scene_dir=False, via="gate")
    # 回显
    if ctx["stage"]:
        print(f"[GATE] ###STAGE 回显: {ctx['stage']}", file=sys.stderr)
    if ctx["storyline"]:
        print(f"[GATE] ###STORYLINE 回显: {ctx['storyline'][0][0]}", file=sys.stderr)
    if ctx["beat"]:
        print(f"[GATE] ###BEAT 回显: {ctx['beat'][0]}", file=sys.stderr)
    if ctx["action"]:
        sched = ctx["schedule"][0] if ctx["schedule"] else "（无）"
        print(f"[GATE] ###ACTION 回显: {len(ctx['action'])} 条行动卡 · SCHEDULE: {sched}", file=sys.stderr)
    if ctx["meta"]:
        print(f"[GATE] ###META 回显: {ctx['meta'][0]}", file=sys.stderr)
    else:
        print("[GATE] 软性告警: 未检测到 ###META: 静默自查锚点（查询轮/维护轮豁免）", file=sys.stderr)
    for _idx, _msg in soft:
        if _idx != -1 and "预检软提示" in _msg:
            print(f"[GATE] 软性提示: {_msg}", file=sys.stderr)
    # 阶段不匹配 = 硬拦（防把别的阶段批次喂进错误闸门）
    if ctx["stage"] and ctx["stage"] != stage_cn:
        hard.append((-1, f"###STAGE '{ctx['stage']}' 与闸门阶段 {stage_cn} 不匹配——各阶段批次走自己的闸门"))
    # 阶段必含项（soft→硬拦）
    batch_required = [msg for idx, msg in soft if idx == -1 and msg.startswith(f"{stage_cn}批应含")]
    # director：顶点出线核验（advance SL-XX 余波）
    climax_violations = []
    if phase == "director":
        climax_violations, _climax_checked = _check_climax_exit(world_dir, ops, ctx["beat"])
    # storyliner：空拍提醒（软性·建线应预设完整拍序）
    if phase == "storyliner":
        for n, ln in sorted((_load_storylines(world_dir).get(STORYLINE_TOP_KEY) or {}).items()):
            if isinstance(ln, dict):
                for w in _empty_beat_warnings(ln):
                    print(f"[GATE] 提醒: 事件线 {n} {w}", file=sys.stderr)
    hard_msgs = [msg for _, msg in hard]
    if parse_errors or hard_msgs or batch_required or climax_violations:
        print(f"[GATE] {stage_cn}阶段代码化核验失败——批次不合格:", file=sys.stderr)
        for e in parse_errors:
            print(f"  - {e}", file=sys.stderr)
        for msg in hard_msgs:
            print(f"  - {msg}", file=sys.stderr)
        for msg in batch_required:
            print(f"  - {msg}", file=sys.stderr)
        for msg in climax_violations:
            print(f"  - {msg}", file=sys.stderr)
        sys.exit(1)
    # 其余软性提醒打印不拦截
    for idx, msg in soft:
        if idx == -1 and not msg.startswith(f"{stage_cn}批应含"):
            print(f"[GATE] 提醒: {msg}", file=sys.stderr)
    print(f"[GATE] {stage_cn}阶段代码化核验通过（硬性必含项齐备）——人工清单请逐项作答", file=sys.stderr)



def cmd_init_states(world_dir: Path):
    """首次启动物化（幂等·缺什么补什么·已存在跳过）——session_recovery.md 第二章 Step 0 的脚本化：
    - states/conflicts.yaml     ← 物化 story_architecture/CONFLICTS_SEED.md（复制+头注释·只落结构字段）
    - states/world_state.yaml   ← templates/world_state.yaml（叙事约定为空时提示 LLM 按世界设定填写）
    - states/world_map.yaml     ← templates/world_map.yaml（有 regions/ 时随后自动 map-sync 对账）
    - scenes/{焦点场景}/pending_actions.yaml ← 场景初始化（init_scene.py）创建（states/ 不物化·场景级）
    - states/CHAR_{名}_state.yaml ← templates/CHAR_state.yaml 骨架（自主性初始值解析自 CHAR_.md
      「世界法则·循环注册」；外部者/管理者角色删除自主性行）
    全部 LF 行尾（newline=""）。LLM 后续按加载序列继续（读静态/动态→校验→循环核对→描绘）。"""
    states = world_dir / "states"
    states.mkdir(parents=True, exist_ok=True)
    tpl_dir = SKILL_DIR / "templates"
    created = []

    def write_lf(fp: Path, text: str):
        with open(fp, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    # 1. conflicts.yaml ← CONFLICTS_SEED.md（只物化结构字段——种子本身即结构字段；节拍留空由戏剧家首轮填充）
    conflicts_fp = states / "conflicts.yaml"
    seed_fp = world_dir / "story_architecture" / "CONFLICTS_SEED.md"
    if conflicts_fp.exists():
        print("[SKIP] conflicts.yaml 已存在（唯一权威·不覆盖）")
    elif not seed_fp.exists():
        print("[ERR] 缺 story_architecture/CONFLICTS_SEED.md——先按第一章创建世界", file=sys.stderr)
        return 1
    else:
        header = (
            "# conflicts.yaml — CT 注册表（上帝视角·禁代词·人名）\n"
            "# 物化自 story_architecture/CONFLICTS_SEED.md（首次启动·init-states）——SEED 只读不改，本文件自此为唯一权威\n"
            "# CT 状态字段（关系状态/内部状态/相位）由①戏剧家每轮结算填充；事件线结构=storylines.yaml（###STORYLINE·②编剧）；演出指针=direction.yaml（###BEAT·③导演）\n\n"
        )
        write_lf(conflicts_fp, header + seed_fp.read_text(encoding="utf-8").rstrip() + "\n")
        created.append("conflicts.yaml ← CONFLICTS_SEED.md")

    # 2-4. 模板复制（world_state / world_map / storylines / direction）——pending_actions 为场景级·随场景初始化创建
    for tpl_name in ("world_state.yaml", "world_map.yaml", STORYLINES_FILE, DIRECTION_FILE):
        fp = states / tpl_name
        if fp.exists():
            print(f"[SKIP] {tpl_name} 已存在")
        else:
            write_lf(fp, (tpl_dir / tpl_name).read_text(encoding="utf-8"))
            created.append(f"{tpl_name} ← templates/{tpl_name}")

    # 5. CHAR_state 骨架（按 characters/CHAR_*.md）
    chars_dir = world_dir / "characters"
    if chars_dir.is_dir():
        for cmd_fp in sorted(chars_dir.glob("CHAR_*.md")):
            name = cmd_fp.stem[len("CHAR_"):]
            if not name:
                continue
            cs_fp = states / f"CHAR_{name}_state.yaml"
            if cs_fp.exists():
                print(f"[SKIP] CHAR_{name}_state.yaml 已存在")
                continue
            tpl_text = (tpl_dir / "CHAR_state.yaml").read_text(encoding="utf-8")
            md_text = cmd_fp.read_text(encoding="utf-8", errors="ignore")
            m_type = re.search(r"\*\*角色类型\*\*[:：]\s*(\S+)", md_text)
            m_auto = re.search(r"\*\*自主性初始值\*\*[:：]\s*(\S+)", md_text)
            is_loop = bool(m_type and "循环角色" in m_type.group(1))
            auto_val = m_auto.group(1) if m_auto else ""
            if is_loop and auto_val in ("脚本", "漂移", "觉醒", "变质"):
                tpl_text = re.sub(r"^自主性:.*$", f"自主性: {auto_val}", tpl_text, flags=re.M)
                note = f"自主性={auto_val}"
            else:
                tpl_text = re.sub(r"^自主性:.*\n?", "", tpl_text, flags=re.M)
                note = "外部者（无自主性行）" if not is_loop else f"自主性初始值非法/缺失（{auto_val or '空'}）——已删行，LLM 按档案补判"
            write_lf(cs_fp, tpl_text)
            created.append(f"CHAR_{name}_state.yaml ← templates/CHAR_state.yaml（{note}）")

    # 6. 有 regions/ → 镜像层对账（补全目录树节点）
    cmd_map_sync(world_dir)

    # 7. 叙事约定为空 → 提示 LLM 填写（创作决策·脚本不代填）
    ws_fp = states / "world_state.yaml"
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8")) or {}
            if not str(ws.get("叙事约定", "") or "").strip():
                print("[TODO] world_state.叙事约定 为空——LLM 按世界设定填写（POV 视角/叙事人称/认知边界）")
        except Exception:
            pass

    if created:
        print(f"[OK] init-states 物化 {len(created)} 个文件:")
        for c in created:
            print(f"  + {c}")
    else:
        print("[OK] init-states: 全部动态文件已存在（幂等·零写入）")
    return 0


def cmd_map_sync(world_dir: Path):
    """world_map 对账补全（镜像层）：遍历 regions/ 目录树 → 缺失节点补入（类型/档案从档案复制·层级镜像目录树）
    有 regions/ 目录时 world_map=镜像层·节点/层级/类型/档案全部由此命令派生；validate 报告缺失时运行本命令。"""
    wm_fp = world_dir / "states" / "world_map.yaml"
    regions_dir = world_dir / "regions"
    if not regions_dir.is_dir():
        print("[SKIP] 无 regions/ 目录——world_map 走迷雾制·无需对账")
        return
    wm = {}
    if wm_fp.exists():
        try:
            wm = yaml.safe_load(wm_fp.read_text(encoding="utf-8")) or {}
        except Exception:
            wm = {}
    if not isinstance(wm, dict) or "已探索区域" not in wm:
        wm = {"已探索区域": {}}
    explored = wm["已探索区域"]
    added = []

    def ensure_node(parent, name, rel_path):
        """在 parent dict 中找/建节点；parent=None 表示顶层 explored"""
        if parent is None:
            node = explored.get(name)
        else:
            node = (parent.get("子区域") or {}).get(name)
        if node is None or not isinstance(node, dict):
            node = {}
            arch = f"regions/{rel_path}/REGION.md"
            txt = (world_dir / arch).read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^\s*-\s*类型:\s*(\S+)", txt, re.M)
            if m:
                node["类型"] = m.group(1)
            node["档案"] = arch
            if parent is None:
                explored[name] = node
            else:
                parent.setdefault("子区域", {})[name] = node
            added.append(f"已探索区域.{rel_path}")
        return node

    def walk(d, parent, rel):
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            name = sub.name
            sub_rel = f"{rel}/{name}" if rel else name
            if not (sub / "REGION.md").is_file():
                continue
            node = ensure_node(parent, name, sub_rel)
            walk(sub, node, sub_rel)

    walk(regions_dir, None, "")
    if added:
        wm["已探索区域"] = explored
        wm_fp.write_text(yaml.dump(wm, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8", newline="")
        print(f"[OK] world_map 对账补全 {len(added)} 个缺失节点:")
        for a in added:
            print(f"  + {a}")
    else:
        print("[OK] world_map 已与 regions/ 目录树同步（无缺失节点）")


def cmd_validate(world_dir: Path):
    scene_dir = get_scene_dir(world_dir)
    files = discover_files(world_dir, scene_dir)
    errors = []
    for key, fp in sorted(files.items()):
        try:
            data = yaml.safe_load(fp.read_text(encoding="utf-8"))
            if data is None:
                errors.append(f"{key}: 空文件")
        except yaml.YAMLError as e:
            errors.append(f"{key}: YAML 解析错误: {e}——修复提示: 字段值含半角冒号+空格（': '）或列表语法时需用引号包裹（对齐同字段正常写法·如 scene_state 关键场景信息参考 S05 的 '区域档案: ...' 单引号格式）；坏文件无法被 write-raw 解析时会拒绝写入——先用编辑器直接修复引号后再走 write-raw")
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
            if fp.parent == world_dir:
                yaml_fp = world_dir / "states" / (fp.stem + ".yaml")
            else:
                yaml_fp = fp.with_suffix(".yaml")
            if not yaml_fp.exists():
                errors.append(f"{fp.name}: 仍为 .md 格式，未转换为 .yaml")
    # ── 内容级检查（警告，不阻断）──
    warnings = []
    # 1. conflicts.yaml 顶层键应为 CT-XX（v0.12：节拍表已迁 storylines——残留=未迁移）
    conflicts_fp = world_dir / "states" / "conflicts.yaml"
    if conflicts_fp.exists():
        try:
            cdata = yaml.safe_load(conflicts_fp.read_text(encoding="utf-8"))
            if isinstance(cdata, dict):
                for k in cdata:
                    if str(k) == PRESSURE_KEY:
                        pv = str(cdata[k] or "").strip()
                        if pv and pv not in PRESSURE_ENUM:
                            warnings.append(f"conflicts.yaml: {PRESSURE_KEY} '{pv}' 非法（枚举: {'/'.join(PRESSURE_ENUM)}）")
                        continue
                    if not re.match(r"^CT-\d{2}$", str(k)):
                        extra = f"（v0.11 节拍表残留——执行 worldctl.py {world_dir.name} migrate）" if str(k) == BEAT_TOP_KEY else ""
                        warnings.append(f"conflicts.yaml: 顶层键 '{k}' 不符合 CT-XX 格式{extra}")
                st = _load_storylines(world_dir)
                sl_map = st.get(STORYLINE_TOP_KEY) or {}
                # 1-legacy. CT 已迁移字段残留检测 + 事件线引用有效性
                for k, cv in cdata.items():
                    if not re.match(r"^CT-\d{2}$", str(k)) or not isinstance(cv, dict):
                        continue
                    legacy_hit = [f for f in CT_LEGACY_KEYS if f in cv]
                    if legacy_hit:
                        warnings.append(f"conflicts.yaml: {k} 含已迁移字段 {legacy_hit}（→ storylines+direction+CHAR_state——执行 worldctl.py {world_dir.name} migrate）")
                    refs = cv.get("事件线引用")
                    if isinstance(refs, list):
                        bad = [str(r) for r in refs if str(r) not in sl_map]
                        if bad:
                            warnings.append(f"conflicts.yaml: {k}.事件线引用 指向不存在的事件线 {bad}")
                # 1b. direction ↔ storylines 三方对账（当前拍指针权威=direction·结构权威=storylines）
                dr = _load_direction(world_dir)
                if dr:
                    cur_sl = str(dr.get("当前事件线", "") or "").strip()
                    cur_beat = str(dr.get("当前拍", "") or "").strip()
                    if not cur_sl and sl_map:
                        warnings.append("direction.yaml: 当前事件线为空但 storylines 有事件线——指针未设（③导演 ###BEAT: set）")
                    elif cur_sl and cur_sl not in sl_map:
                        warnings.append(f"direction.yaml: 当前事件线 '{cur_sl}' 不在 storylines.事件线 中")
                    elif cur_sl:
                        line = sl_map.get(cur_sl) or {}
                        names = [str(b.get("拍名", "")) for b in (line.get("拍序") or []) if isinstance(b, dict)]
                        if cur_beat and cur_beat not in names:
                            warnings.append(f"direction.yaml: 当前拍 '{cur_beat}' 不在事件线 {cur_sl} 的拍序中（拍序: {names}）")
                        q_dr = str(dr.get("当前戏剧问题", "") or "").strip()
                        q_st = ""
                        for b in (line.get("拍序") or []):
                            if isinstance(b, dict) and str(b.get("拍名", "") or "").strip() == cur_beat:
                                q_st = str(b.get("戏剧问题", "") or "").strip()
                                break
                        if q_dr and q_st and q_dr != q_st:
                            warnings.append(f"direction.yaml: 当前戏剧问题与 storylines 事件线 {cur_sl} 拍 '{cur_beat}' 不一致（缓存漂移·以 storylines 为准）")
                    perf = str(dr.get("演出状态", "") or "").strip()
                    if perf and perf not in PERF_STATES:
                        warnings.append(f"direction.yaml: 演出状态 '{perf}' 非法（枚举: {'/'.join(PERF_STATES)}）")
                    # 1b-2. 顶点基线落档存在性（软性·消息中性——不出具对比面字段清单）
                    if cur_sl and cur_beat == "顶点" and not _climax_baseline_fp(world_dir, cur_sl).exists():
                        warnings.append("direction.yaml: 当前拍=顶点 但基线落档缺失（进入顶点拍时脚本自动记录·私有落档）——出线核验将拦截·先 beat set/advance 顶点 建档")
                # 1c. 顶点约束结构（storylines·Vertex Constraint 校验 + 旧字段残留告警）
                for n, ln in sl_map.items():
                    if not isinstance(ln, dict) or not ln:
                        continue
                    for b in (ln.get("拍序") or []):
                        if not isinstance(b, dict) or str(b.get("拍名", "") or "").strip() != "顶点":
                            continue
                        if "顶点落点" in b:
                            warnings.append(f"storylines.yaml: 事件线 {n} 顶点拍用旧字段 顶点落点（答题式 Outcome·已废弃）——rewrite 为 顶点约束")
                            continue
                        cons = b.get(CLIMAX_CONSTRAINT_KEY)
                        if not isinstance(cons, dict):
                            warnings.append(f"storylines.yaml: 事件线 {n} 顶点拍缺 顶点约束（关系主体/核心张力/变化维度/非玩家爆破）")
                            continue
                        principals = [str(x).strip() for x in (cons.get("关系主体") or []) if str(x).strip()]
                        if len(set(principals)) < 2:
                            warnings.append(f"storylines.yaml: 事件线 {n}.顶点约束.关系主体 需 ≥2 去重角色（顶点单位=关系）")
                        if not str(cons.get("核心张力", "") or "").strip():
                            warnings.append(f"storylines.yaml: 事件线 {n}.顶点约束.核心张力 为空")
                        dims = [str(d).strip() for d in (cons.get("变化维度") or []) if str(d).strip()]
                        if not dims or any(d not in DIM_ENUM for d in dims):
                            warnings.append(f"storylines.yaml: 事件线 {n}.顶点约束.变化维度 非法或为空（枚举: {'/'.join(DIM_ENUM)}）")
                        blasters = [str(x).strip() for x in (cons.get("非玩家爆破") or []) if str(x).strip()]
                        if not blasters:
                            warnings.append(f"storylines.yaml: 事件线 {n}.顶点约束.非玩家爆破 为空（≥1 外部角色或事件·压力供应方·防死锁）")
        except Exception:
            pass
    # 2. world_state.焦点场景（唯一权威源）↔ INDEX + 场景目录一致性
    index_fp = world_dir / "scenes" / "INDEX.md"
    ws_fp = world_dir / "states" / "world_state.yaml"
    focus_id = ""
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8"))
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
            index_text = index_fp.read_text(encoding="utf-8")
            if not re.search(rf"\|[ ]*{re.escape(focus_id)}[ ]*\|", index_text):
                warnings.append(f"焦点场景 '{focus_id}' 未在 scenes/INDEX.md 的表格行中找到")
            active_rows = re.findall(r"^\|\s*(S\d+)\s*\|.*\|\s*ACTIVE\s*\|", index_text, re.M)
            if active_rows and active_rows != [focus_id]:
                warnings.append(f"INDEX ACTIVE 行 {active_rows} 与 world_state.焦点场景 '{focus_id}' 不一致")
    elif ws_fp.exists() and index_fp.exists() and not focus_id:
        active_rows = re.findall(r"^\|\s*(S\d+)\s*\|.*\|\s*ACTIVE\s*\|", index_fp.read_text(encoding="utf-8"), re.M)
        if active_rows:
            warnings.append(f"world_state.焦点场景 为空，但 INDEX 标记 {active_rows} 为 ACTIVE——焦点场景唯一权威源缺失")
    # 3. CHAR_*_state.yaml 应有对应 CHAR_*.md
    for sf in sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        md_fp = world_dir / "characters" / (sf.name[: -len(CHAR_STATE_SUFFIX)] + ".md")
        if not md_fp.exists():
            warnings.append(f"{sf.name}: 无对应 {md_fp.name}")
    # 4. world_state.yaml 必要键
    ws_fp = world_dir / "states" / "world_state.yaml"
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8"))
            if isinstance(ws, dict):
                for need in ("焦点场景", "时间", "全局标记"):
                    if need not in ws:
                        warnings.append(f"world_state.yaml: 缺顶层键 {need}")
        except Exception:
            pass
    # 4b. world_state 键表外字段（软性警告——无语义定义的漂移字段）
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8"))
            if isinstance(ws, dict):
                WS_TOP_KEYS = {"焦点场景", "轮次", "时间", "外部倒计时", "全局标记", "时间线", "重置记录", "叙事约定"}
                WS_TIME_KEYS = {"基准时间", "具体时间", "时间流速比", "前情描述"}
                for k in ws:
                    if k not in WS_TOP_KEYS:
                        warnings.append(f"world_state.yaml: 未知顶层键 '{k}'（键表: 焦点场景/轮次/时间/外部倒计时/全局标记/时间线/重置记录/叙事约定）")
                t = ws.get("时间")
                if isinstance(t, dict):
                    for k in t:
                        if k not in WS_TIME_KEYS:
                            warnings.append(f"world_state.yaml: 未知时间子键 '{k}'（键表: 基准时间/具体时间/时间流速比/前情描述）")
                loc = ws.get("地点")
                if isinstance(loc, dict):
                    for k in loc:
                        warnings.append(f"world_state.yaml: 地点.{k} 已废弃（当前区域→scene 区域关联·已探索区域→world_map 镜像·请删除该字段）")
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
    # 4c2. scene_card 区域关联检查（镜像层：区域行 ∈ regions/ 目录树·必填）
    regions_dir = world_dir / "regions"
    if regions_dir.is_dir():
        for card in sorted(world_dir.glob("scenes/*/scene_card.md")):
            txt = card.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"^\|\s*区域\s*\|\s*([^|]+?)\s*\|", txt, re.M)
            if not m:
                warnings.append(f"{card.relative_to(world_dir)}: 缺「区域」行（scene_card 模板必填·完整路径·从 regions/ 目录树引用既有档案）")
            else:
                arch = m.group(1).strip()
                if not (world_dir / arch).is_file():
                    warnings.append(f"{card.relative_to(world_dir)}: 区域指针悬空（{arch} 不存在——先核对 regions/ 既有档案·指针引用既有路径·确无档案才新建）")
    # 4c'. 焦外断线兜底（软警告·低频）：焦点场景 pending_actions 活跃中为空，但 调度单 点名焦外角色 → 提示补迁移/注册
    if scene_dir is not None and (scene_dir / "pending_actions.yaml").exists():
        try:
            _pa = yaml.safe_load((scene_dir / "pending_actions.yaml").read_text(encoding="utf-8")) or {}
            _act = _pa.get("活跃中")
            active_empty = not bool(isinstance(_act, dict) and _act)
        except Exception:
            active_empty = True
        if active_empty and re.search(r"焦外\s*=\s*(?!无)", _direction_schedule_text(world_dir)):
            warnings.append("焦点场景 pending_actions 活跃中为空，但 调度单 点名焦外角色——检查是否漏迁移/注册（见 scene_management 场景切换流程第6步）")
    # 4e. 已知地点后缀匹配（镜像层：条目 ∈ regions/ 目录树某节点路径的后缀——角色认知根开始·如 Sweetwater/Main Street）
    regions_dir = world_dir / "regions"
    if regions_dir.is_dir():
        tree_paths = [p.parent.relative_to(regions_dir).as_posix() for p in regions_dir.rglob("REGION.md")]
        for sf in sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
            try:
                sd = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            places = sd.get("已知地点")
            if not isinstance(places, list):
                continue
            for pl in places:
                s = str(pl or "").strip()
                if not s:
                    continue
                if not any(p == s or p.endswith("/" + s) for p in tree_paths):
                    warnings.append(f"{sf.name}: 已知地点 '{s}' 不在 regions/ 目录树（后缀路径应从目录节点名·角色认知根开始·如 Sweetwater/Main Street）")
    # 4d. 事件触发重置强制校验（loop_machinery §4 触发管道之二）——CHAR_state 当前状态含「重置完成/校准完成」类
    #     字段但该角色无 重置记录 → 叙事演了重置、文件未执行联动表（补执行: worldctl.py <世界> reset-cycle --asset <角色>）
    reset_names = set()
    if ws_fp.exists():
        try:
            _ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8"))
            if isinstance(_ws, dict):
                _rr = _ws.get("重置记录")
                if isinstance(_rr, dict):
                    reset_names = {str(k) for k in _rr}
        except Exception:
            pass
    RESET_DONE_RE = re.compile(r"重置完成|校准完成")
    for sf in sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            sd = yaml.safe_load(sf.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        name = sf.name[len(CHAR_STATE_PREFIX):-len(CHAR_STATE_SUFFIX)]
        if name in reset_names:
            continue
        blob = " ".join(str(sd.get(k, "") or "") for k in ("核心状态", "情绪", "决策状态", "位置"))
        if RESET_DONE_RE.search(blob):
            warnings.append(f"{sf.name}: 当前状态含『重置完成/校准完成』但无 重置记录——事件触发重置未执行联动表（补执行: worldctl.py {world_dir.name} reset-cycle --asset {name}）")
    # 5. world_map.yaml（可选增强层·迷雾制·多层嵌套）——缺失时静默跳过，不影响运行
    wm_fp = world_dir / "states" / "world_map.yaml"
    if wm_fp.exists():
        try:
            wm = yaml.safe_load(wm_fp.read_text(encoding="utf-8"))
            if not isinstance(wm, dict) or "已探索区域" not in wm:
                warnings.append("world_map.yaml: 缺顶层键 已探索区域（迷雾制地图，初始应为 {}）")
            else:
                scenes_dir = world_dir / "scenes"
                WM_KEYS = {"类型", "方位", "连接", "发现于", "备注", "子区域", "档案"}
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
                # regions/ 档案对账（可选增强层：有 regions/ 目录才检查）——已登记节点有 档案 指针 →
                # ① 指针悬空告警 ② 类型与档案不一致告警（单向派生对账·软告警·不是双权威）
                regions_dir = world_dir / "regions"
                if regions_dir.is_dir():
                    def walk_archive(node, path):
                        arch = str(node.get("档案", "") or "").strip()
                        if arch:
                            afp = world_dir / arch
                            if not afp.is_file():
                                warnings.append(f"world_map.yaml {path}.档案: 指针悬空（{arch} 不存在——先核对 regions/ 既有档案·指针引用既有路径·确无档案才新建）")
                            else:
                                txt = afp.read_text(encoding="utf-8", errors="ignore")
                                m = re.search(r"^\s*-\s*类型:\s*(\S+)", txt, re.M)
                                if m and node.get("类型") and m.group(1) != str(node.get("类型")):
                                    warnings.append(f"world_map.yaml {path}.类型: 与档案 {arch} 不一致（档案={m.group(1)}，map={node.get('类型')}——派生登记应从档案复制）")
                        for k, sub in (node.get("子区域") or {}).items():
                            walk_archive(sub, f"{path}.{k}")
                    for name, sub in (wm.get("已探索区域") or {}).items():
                        walk_archive(sub, f"已探索区域.{name}")
                    # 缺失节点报告（镜像层）：目录树节点不在 world_map → 提示运行 map-sync 对账补全
                    def _node_exists(node, parts):
                        cur = node
                        for p in parts:
                            if not isinstance(cur, dict):
                                return False
                            nxt = cur.get(p)
                            if nxt is None:
                                kids = cur.get("子区域") or {}
                                nxt = kids.get(p)
                                if nxt is None:
                                    return False
                            cur = nxt
                        return True
                    missing = []
                    def walk_tree(d, rel):
                        for sub in sorted(d.iterdir()):
                            if not sub.is_dir():
                                continue
                            name = sub.name
                            sub_rel = f"{rel}/{name}" if rel else name
                            if not (sub / "REGION.md").is_file():
                                continue
                            if not _node_exists(wm.get("已探索区域") or {}, sub_rel.split("/")):
                                missing.append(sub_rel)
                            walk_tree(sub, sub_rel)
                    walk_tree(regions_dir, "")
                    if missing:
                        shown = ", ".join(missing[:5]) + ("..." if len(missing) > 5 else "")
                        warnings.append(f"world_map.yaml: {len(missing)} 个目录树节点缺失——运行 `worldctl.py {world_dir.name} map-sync` 对账补全（镜像层·节点从目录树派生·禁止手写）: {shown}")
        except Exception:
            pass
    # 5b. foreshadow.yaml 伏笔闭环检查（可选文件·仅世界有该文件时检查）
    fs_fp = world_dir / "states" / "foreshadow.yaml"
    if fs_fp.exists():
        try:
            fdata = yaml.safe_load(fs_fp.read_text(encoding="utf-8"))
            f_list = fdata.get("伏笔", []) if isinstance(fdata, dict) else None
            if f_list is None:
                errors.append("foreshadow.yaml: 缺顶层键 伏笔（应为列表）")
            elif not isinstance(f_list, list):
                errors.append("foreshadow.yaml: 顶层键 伏笔 应为列表")
            else:
                cur_round = 0
                if ws_fp.exists():
                    try:
                        ws_cur = yaml.safe_load(ws_fp.read_text(encoding="utf-8"))
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
    # 5c. scene_state 结构化字段校验（场景时间线带轮次·道具按 ID——旧字符串格式软提示迁移）
    scene_dir2 = get_scene_dir(world_dir)
    if scene_dir2 and (scene_dir2 / "scene_state.yaml").exists():
        try:
            sd2 = yaml.safe_load((scene_dir2 / "scene_state.yaml").read_text(encoding="utf-8")) or {}
        except Exception:
            sd2 = {}
        tl = sd2.get("场景时间线", "")
        if isinstance(tl, list):
            bad = [it for it in tl if not isinstance(it, dict) or not str(it.get("轮次", "") or "").strip()
                   or not str(it.get("时间", "") or "").strip() or not str(it.get("事件", "") or "").strip()]
            if bad:
                warnings.append(f"{scene_dir2.name}/scene_state.yaml: 场景时间线 {len(bad)} 条缺 轮次/时间/事件 子字段（结构: 轮次/时间/事件）")
            rounds_seen = [str(it.get("轮次", "") or "") for it in tl if isinstance(it, dict)]
            dup_r = [r for r in set(rounds_seen) if rounds_seen.count(r) > 1]
            if dup_r:
                warnings.append(f"{scene_dir2.name}/scene_state.yaml: 场景时间线 轮次重复 {dup_r}（一轮一条·同轮多事件并入一条或注明）")
        elif isinstance(tl, str) and tl.strip():
            warnings.append(f"{scene_dir2.name}/scene_state.yaml: 场景时间线 仍是旧字符串格式（· 连接）——结构化迁移：- 轮次/时间/事件（回退裁剪需按轮次字段）")
        props = sd2.get("道具", "")
        if isinstance(props, list):
            pids = [str(it.get("ID", "") or "") for it in props if isinstance(it, dict)]
            dup_p = [i for i in set(pids) if pids.count(i) > 1]
            if dup_p:
                warnings.append(f"{scene_dir2.name}/scene_state.yaml: 道具 ID 重复 {dup_p}（ID 唯一）")
        elif isinstance(props, str) and props.strip():
            warnings.append(f"{scene_dir2.name}/scene_state.yaml: 道具 仍是旧表格字符串（|P1|…|）——结构化迁移：- ID/名称/位置/状态")

    # 6. CHAR_state 字段级校验（键表/人际动态档位/废弃键/全知视角/轨迹方向/decision 结构/偏离计数）
    CHAR_ALLOWED_KEYS = {"位置", "已知地点", "名字", "核心状态", "情绪", "人际动态", "决策状态",
                         "压力水平", "防御有效性", "防御形态", "崩溃表现", "信念演化", "记忆锚点", "反应轨迹",
                         "连续行动轨迹", "decision",
                         "偏离登记",
                         "自主性",
                         "服装", "健康", "随身"}
    RELATION_TIERS = {"稳固", "信任", "中立", "防备", "破裂", "待重建"}
    OMNI_PATTERN = re.compile(r"[他她]不知道")
    # 3b 前置（补实现·reset-cycle 注释已声称）：偏离登记 ≥2 需有「法则」型 CT 承接（Host vs 法则·冲突化窗口归零）
    _c3b = {}
    try:
        _c3b = yaml.safe_load((world_dir / "states" / "conflicts.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        _c3b = {}
    _has_law_ct = any(isinstance(v, dict) and "法则" in str(v.get("对抗双方", "") or "") for v in _c3b.values())
    for cfp in sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            cdata = yaml.safe_load(cfp.read_text(encoding="utf-8"))
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
        # 豁免：防御重构进行中（防御形态非空 且 防御=正在失效=人格修复弧线的回升形态）——压力低是重构后的正常形态，不警告
        in_reconstruction = bool(str(cdata.get("防御形态", "") or "").strip())
        if (isinstance(defense, str) and defense in ("正在失效", "已彻底崩解") and pressure == "低"
                and not (in_reconstruction and defense == "正在失效")):
            warnings.append(f"{cname}: 防御有效性={defense} 但 压力水平=低——防御降级缺压力支撑（loop_machinery §3 影响字段: 压力↑→防御↓·先积累压力再降防）")
        # 6h. decision 结构（v0.12 角色决策状态·子字段软校验——④角色阶段每轮补全）
        dec = cdata.get("decision")
        if dec is not None:
            DEC_SUB = {"当前目标", "当前计划", "当前行动", "行动驱动", "行动对象", "行动窗口", "失败后续", "未完成意图"}
            if not isinstance(dec, dict):
                warnings.append(f"{cname}: decision 应为映射（八子字段：{'/'.join(sorted(DEC_SUB))}）——点路径逐层写（decision.当前目标 等）")
            else:
                missing = [k for k in DEC_SUB if k not in dec]
                if missing:
                    warnings.append(f"{cname}: decision 缺子字段 {missing}（空值可留空但键应在·④角色阶段补全）")
        # 6i. 连续行动轨迹（v0.12 角色时间线·不裁剪·增长告警+结构校验）
        track = cdata.get("连续行动轨迹")
        if isinstance(track, list) and track:
            total = sum(len(str(it.get("行动", "") or "")) + len(str(it.get("行动结果", "") or "")) for it in track if isinstance(it, dict))
            if total > ACTION_TRACK_LIMIT:
                warnings.append(f"{cname}: 连续行动轨迹 {total} 字 > {ACTION_TRACK_LIMIT} 告警线——角色计划复盘时压缩旧行动为概括条目（轨迹=原始时间线·记忆锚点=蒸馏层）")
            bad = [it for it in track if not isinstance(it, dict) or not str(it.get("轮次", "")).strip() or not str(it.get("行动", "")).strip()]
            if bad:
                warnings.append(f"{cname}: 连续行动轨迹 {len(bad)} 条缺 轮次/行动 子字段（结构: 轮次/行动/行动目的/行动结果/他人反应/计划变化/未完成意图）")
        # 6j. 3b 偏离登记计数（补实现）：≥2 次行动级偏离 且 无「法则」型 CT 承接 → 告警
        dev = cdata.get("偏离登记")
        if isinstance(dev, list) and len(dev) >= 2 and not _has_law_ct:
            warnings.append(f"{cname}: 偏离登记 {len(dev)} 次 ≥2 但 conflicts 无「法则」型 CT——行动级偏离 1 次即应注册「Host vs 法则」CT（冲突化窗口归零·loop_machinery §5.1）")

    # 7. world_state.时间线 粗粒度摘要校验（脚本校验线：条目≤10 | 单场景≤3转折点 | 总字数≤2500——超限告警，提示场记执行压缩维护）
    ws_fp = world_dir / "states" / "world_state.yaml"
    if ws_fp.exists():
        try:
            ws = yaml.safe_load(ws_fp.read_text(encoding="utf-8"))
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
    for cfp in sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            cdata = yaml.safe_load(cfp.read_text(encoding="utf-8"))
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
        ws_data = yaml.safe_load((world_dir / "states" / "world_state.yaml").read_text(encoding="utf-8")) or {}
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
            warnings.append("循环机制完整性: SETTING 声明循环/重置机制但外部倒计时无周期条目（含空表）——周期倒计时未初始化登记（见 session_recovery.md §第二章启动世界·循环机制核对）")
    except Exception:
        pass
    reset_rec = ws_data.get("重置记录") or {}
    if isinstance(reset_rec, dict):
        for rname, rspec in reset_rec.items():
            if not isinstance(rspec, dict):
                continue
            # 豁免记录（触发=豁免）不触发压缩校验——豁免=记忆保留·非重置压缩（2026-08-17 加入）
            if str(rspec.get("触发", "")).strip() == "豁免":
                continue
            rlvl = str(rspec.get("档位", "")).strip()
            cfp = world_dir / "states" / f"{CHAR_STATE_PREFIX}{rname}{CHAR_STATE_SUFFIX}"
            if not cfp.exists():
                continue
            try:
                cdata = yaml.safe_load(cfp.read_text(encoding="utf-8")) or {}
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
        ws_fp2 = world_dir / "states" / "world_state.yaml"
        if ws_fp2.exists():
            ws2 = yaml.safe_load(ws_fp2.read_text(encoding="utf-8")) or {}
            focus_id2 = str(ws2.get("焦点场景", "") or "").strip()
            if focus_id2 and scene_dir and scene_dir.is_dir():
                nf = scene_dir / "narrative.md"
                if nf.exists():
                    if nf.stat().st_mtime < ws_fp2.stat().st_mtime - 300:  # 早于 world_state 5 分钟以上
                        warnings.append(f"叙事新鲜度: {scene_dir.name}/narrative.md 修改时间早于 world_state.yaml——叙事可能未落盘（每轮阶段2 叙事应经 write_narrative.py 写入，缺失=连续性断裂）")
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

    # 8e. 区域一致性（场景切换主判据·机械复核——硬拦在 round-check，此处仅提示）
    try:
        rc_fail = _region_consistency(world_dir)
        if rc_fail:
            warnings.append(rc_fail)
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

# ── STORYLINE / BEAT（v0.12：结构归②编剧·指针归③导演）─────────────
def _storyline_usage():
    print("用法: worldctl.py <世界> storyline <子命令> [参数]   ← 事件线结构（states/storylines.yaml·②编剧唯一通道）", file=sys.stderr)
    print("  show [SL-XX]       读事件线（全部 / 指定）", file=sys.stderr)
    print("  add                stdin YAML 建线（id 自动递增 SL-XX·结构蓝图无当前拍——指针由③导演 ###BEAT: set 落 direction）", file=sys.stderr)
    print("  rewrite SL-XX      stdin YAML 重规划（现实不承接·判线仍有继续价值时）", file=sys.stderr)
    print("  close SL-XX        收束（当前拍=余波·线已演完）——stdin YAML 必含一行 收束摘要；保留 名称/类型＋状态=已收束·清拍序·指针复位", file=sys.stderr)
    print("  clear SL-XX        废弃（不承接且无继续价值）——整条抹为空锚点·direction 指针自动复位", file=sys.stderr)
    print("add/rewrite stdin 事件线 YAML 骨架（拍序含顶点拍时须带 顶点约束 五字段）:", file=sys.stderr)
    print("  名称: 事件标识", file=sys.stderr)
    print("  类型: 对峙/追逃/营救/关系转折…", file=sys.stderr)
    print("  状态: 活跃", file=sys.stderr)
    print("  拍序:", file=sys.stderr)
    print("  - 拍名: 接触", file=sys.stderr)
    print("    空间: 地点 / 时间: 时刻 / 戏剧问题: 本拍必须回答的、有边界的戏剧问题", file=sys.stderr)
    print("    兑现形态: 证据易手/被迫承认/控制权转移/关系定性/退路封死", file=sys.stderr)
    print("  - 拍名: 顶点", file=sys.stderr)
    print("    空间: 地点 / 时间: 待定 / 戏剧问题: …", file=sys.stderr)
    print("    顶点约束:", file=sys.stderr)
    print("      关系主体:            # ≥2 去重·不区分玩家/NPC——顶点单位=关系", file=sys.stderr)
    print("      - 角色A", file=sys.stderr)
    print("      - 角色B", file=sys.stderr)
    print("      核心张力: 必须被推至临界的未决问题——点名赌注所在", file=sys.stderr)
    print("      变化维度: [关系, 认知, 决策, 资源 中选]  # 创作意图声明——想推动什么类型的转变·非验收映射", file=sys.stderr)
    print("      非玩家爆破:            # ≥1 外部角色或事件——压力供应方（主体全静止时逼上悬崖）", file=sys.stderr)


def _beat_usage():
    print("用法: worldctl.py <世界> beat <子命令> [参数]        ← 演出指针（states/direction.yaml·③导演唯一通道）", file=sys.stderr)
    print("  show               读 direction（当前事件线/当前拍/演出状态/guidance）", file=sys.stderr)
    print("  set SL-XX 拍名     初始指针（建线后由③导演设定起点拍·进入顶点时自动记录基准快照）", file=sys.stderr)
    print("  stay SL-XX         停留当前拍（戏剧问题未兑现·有兑现进展·确认无写入）", file=sys.stderr)
    print("  advance SL-XX 拍名 推进指针（校验拍名在拍序中·禁回退·重规划走 storyline rewrite）", file=sys.stderr)


def _validate_storyline(line) -> str | None:
    """校验单条事件线结构（结构蓝图——无 当前拍·指针权威在 direction）。返回错误描述，None=通过。"""
    if not isinstance(line, dict):
        return "事件线必须是映射（名称/类型/状态/拍序）"
    if "名称" not in line or not str(line.get("名称", "")).strip():
        return "缺 名称（当前跨轮展开的戏剧事件标识）"
    seq = line.get("拍序")
    if not isinstance(seq, list) or not seq:
        return "拍序 必须是非空 yaml 列表（元素: 拍名/空间/时间/戏剧问题/兑现形态）"
    names = []
    for b in seq:
        if not isinstance(b, dict):
            return "拍序 元素必须是映射（拍名/空间/时间/戏剧问题）"
        nm = str(b.get("拍名", "")).strip()
        if nm not in BEAT_ENUM:
            return f"拍名 '{nm}' 非法（枚举: {'/'.join(BEAT_ENUM)}）"
        if nm in names:
            return f"拍名 '{nm}' 重复"
        names.append(nm)
        ev = str(b.get("戏剧问题", "") or "").strip()
        if not ev:
            return f"拍名 '{nm}' 缺戏剧问题（本拍必须回答的、有边界的戏剧问题·禁止空值）"
        if any(word in ev for word in ("加剧", "深化", "持续", "不断")) and not any(mark in ev for mark in ("？", "?")):
            return f"拍名 '{nm}' 的戏剧问题是无界持续描述（改写为可回答的戏剧问题）"
    return None


def _storyline_landing_error(line) -> str | None:
    """顶点约束（Vertex Constraint）校验（add/rewrite 时硬性·当场反馈）：
    拍序含顶点拍时必须有 顶点约束——关系主体 ≥2（去重·不区分玩家/NPC·顶点单位=关系）/
    核心张力非空（未决问题·点名赌注所在）/ 变化维度 ⊆ 枚举且非空 / 非玩家爆破 ≥1（外部角色或事件·加压力量）。
    五个字段声明的是临界本身——实现形式由现场演出决定。
    拍序无顶点拍 → 放行；旧字段 顶点落点（角色/内部变量/预期形态）在场 → 拒绝（rewrite 迁移）。"""
    for b in line.get("拍序") or []:
        if not isinstance(b, dict) or str(b.get("拍名", "") or "").strip() != "顶点":
            continue
        if "顶点落点" in b:
            return "顶点拍仍在用旧字段 顶点落点（答题式 Outcome·已废弃）——改写为 顶点约束（关系主体/核心张力/变化维度/非玩家爆破）后 rewrite"
        cons = b.get(CLIMAX_CONSTRAINT_KEY)
        if not isinstance(cons, dict):
            return "顶点拍缺 顶点约束（五字段：关系主体≥2/核心张力/变化维度/非玩家爆破≥1/基准快照）"
        principals = [str(x).strip() for x in (cons.get("关系主体") or []) if str(x).strip()]
        if len(set(principals)) < 2:
            return "顶点约束.关系主体 需 ≥2 去重角色（顶点的单位是关系不是单人·不区分玩家/NPC）"
        if not str(cons.get("核心张力", "") or "").strip():
            return "顶点约束.核心张力 为空（必须被推至临界的未决问题——一句话点名赌注所在）"
        dims = [str(d).strip() for d in (cons.get("变化维度") or []) if str(d).strip()]
        bad = [d for d in dims if d not in DIM_ENUM]
        if not dims or bad:
            return f"顶点约束.变化维度 非法（{bad or '空'}——枚举: {'/'.join(DIM_ENUM)}·立场/承诺/信息由认知·关系承载）"
        blasters = [str(x).strip() for x in (cons.get("非玩家爆破") or []) if str(x).strip()]
        if not blasters:
            return "顶点约束.非玩家爆破 为空（≥1 外部角色或事件——主体静止时的加压力量·防死锁）"
        if CLIMAX_BASELINE_KEY in cons:
            return f"顶点约束.{CLIMAX_BASELINE_KEY} 已改为脚本私有落档（.climax_baseline_*.yaml·自动记录）——从约束中移除该字段"
        break
    return None


def _next_storyline_id(beats: dict) -> str:
    """下一个事件线编号（SL-XX·数字递增两位；兼容旧纯数字 N）。"""
    max_n = 0
    for k in beats:
        m = re.match(r"^(?:SL-)?(\d+)$", str(k), re.IGNORECASE)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"{STORYLINE_ID_PREFIX}{max_n + 1:02d}"


def _empty_beat_warnings(line) -> list[str]:
    """检查事件线拍序：空间/时间/戏剧问题 任一为空的拍 → 警告列表。
    建线应预设完整拍序内容（拍=规划蓝图）；推进/换线后空拍仍在 = 现实与该拍无法承接（需 rewrite 补填或明确留空）。"""
    warns = []
    seq = line.get("拍序") or []
    if not isinstance(seq, list):
        return warns
    for b in seq:
        if not isinstance(b, dict):
            continue
        nm = str(b.get("拍名", "") or "").strip()
        missing = [f for f in ("空间", "时间", "戏剧问题") if not str(b.get(f, "")).strip()]
        if missing:
            warns.append(f"拍 '{nm}' 内容不完整（缺: {'/'.join(missing)}）——建线应预设完整拍序·现实与空拍无法承接·需 rewrite 补填")
    return warns


def _warn_empty_beats(n: str, line) -> None:
    """对单条事件线打印空拍警告（add/rewrite 后调用·软性不拦截）。"""
    for w in _empty_beat_warnings(line):
        print(f"[WARN] {STORYLINE_TOP_KEY} 事件线 {n} {w}", file=sys.stderr)


def cmd_storyline(world_dir: Path, extra: list[str], stdin_text: str | None = None):
    """事件线结构维护（states/storylines.yaml）——②编剧唯一通道（###STORYLINE 自动执行·LLM 不直接改 YAML）。
    结构/枚举校验后机械写入。stdin_text: write-raw 自动执行时传入 add/rewrite 的事件线 YAML。"""
    fp = world_dir / "states" / STORYLINES_FILE
    data = _load_storylines(world_dir)
    beats = data.get(STORYLINE_TOP_KEY)
    if beats is None:
        beats = {}
    if not isinstance(beats, dict):
        print(f"[ERR] {STORYLINE_TOP_KEY} 已存在但非映射结构: {type(beats).__name__}", file=sys.stderr)
        sys.exit(1)

    if not extra or extra[0] in ("--help", "-h"):
        _storyline_usage()
        sys.exit(0 if extra else 1)
    sub = extra[0]

    if sub == "show":
        sid = _norm_sl_id(extra[1]) if len(extra) > 1 else None
        if sid is not None:
            line = beats.get(sid)
            if line is None:
                print(f"[ERR] {STORYLINE_TOP_KEY} 无事件线 {sid}", file=sys.stderr)
                sys.exit(1)
            out = {sid: line}
        else:
            out = beats
        yaml.dump(out, sys.stdout, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)
        return

    if sub == "add":
        line = yaml.safe_load(stdin_text if stdin_text is not None else _read_stdin_utf8())
        err = _validate_storyline(line) or _storyline_landing_error(line)
        if err:
            print(f"[ERR] 事件线结构校验失败: {err}", file=sys.stderr)
            sys.exit(1)
        n = _next_storyline_id(beats)
        beats[n] = line
        data[STORYLINE_TOP_KEY] = beats
        write_yaml(fp, data)
        print(f"[OK] {STORYLINE_TOP_KEY} 事件线 {n} 已建（{sub}）——起点指针由③导演 ###BEAT: set {n} <起点拍> 落 direction")
        _warn_empty_beats(n, line)
        return

    if sub in ("rewrite", "close", "clear"):
        if len(extra) < 2:
            _storyline_usage()
            sys.exit(1)
        n = _norm_sl_id(extra[1])
        if n not in beats:
            print(f"[ERR] {STORYLINE_TOP_KEY} 无事件线 {n}", file=sys.stderr)
            sys.exit(1)
        dr = _load_direction(world_dir)
        ptr_on_line = str(dr.get("当前事件线", "") or "").strip() == n
        cur_beat = str(dr.get("当前拍", "") or "").strip()
        if sub == "close":
            if not ptr_on_line:
                print(f"[ERR] direction 指针不在事件线 {n}（当前: {dr.get('当前事件线', '')}/{cur_beat}）——close 只收束当前演完的线", file=sys.stderr)
                sys.exit(1)
            if cur_beat != "余波":
                print(f"[ERR] 当前拍='{cur_beat}' 非余波——线未演完不收束（中途放弃走 clear·继续演出走 stay）", file=sys.stderr)
                sys.exit(1)
            pl = yaml.safe_load(stdin_text if stdin_text is not None else _read_stdin_utf8())
            summary = str(pl.get("收束摘要", "")).strip() if isinstance(pl, dict) else ""
            if not summary:
                print("[ERR] close 缺 收束摘要（一行结局定性——不想留档说明该走 clear 废弃）", file=sys.stderr)
                sys.exit(1)
            old = beats[n] if isinstance(beats.get(n), dict) else {}
            closed = {"名称": str(old.get("名称", "") or "").strip() or n}
            ltype = str(old.get("类型", "") or "").strip()
            if ltype:
                closed["类型"] = ltype
            closed["状态"] = "已收束"
            closed["收束摘要"] = summary
            beats[n] = closed
            bfp = _climax_baseline_fp(world_dir, n)
            if bfp.exists():
                bfp.unlink()
                print(f"[OK] 基线落档已清理（{bfp.name}）", file=sys.stderr)
            dr["当前事件线"] = ""
            dr["当前拍"] = ""
            dr["当前戏剧问题"] = ""
            _save_direction(world_dir, dr)
            data[STORYLINE_TOP_KEY] = beats
            write_yaml(fp, data)
            print(f"[OK] {STORYLINE_TOP_KEY} 事件线 {n} 已收束（状态=已收束·留 名称/类型/收束摘要）——direction 指针已复位·当轮须 add 后继线并由③导演 set 新起点（否则 round-check FAIL）")
            return
        if sub == "clear":
            if ptr_on_line and cur_beat == "余波":
                print(f"[WARN] 当前拍='余波'——线已演完·应走 close 收束留档（本次按废弃抹除执行）", file=sys.stderr)
            if ptr_on_line:
                dr["当前事件线"] = ""
                dr["当前拍"] = ""
                dr["当前戏剧问题"] = ""
                _save_direction(world_dir, dr)
                print(f"[OK] direction 指针已复位（事件线 {n} 废弃）", file=sys.stderr)
            beats[n] = {}
            bfp = _climax_baseline_fp(world_dir, n)
            if bfp.exists():
                bfp.unlink()
                print(f"[OK] 基线落档已清理（{bfp.name}）", file=sys.stderr)
        else:
            line = yaml.safe_load(stdin_text if stdin_text is not None else _read_stdin_utf8())
            err = _validate_storyline(line) or _storyline_landing_error(line)
            if err:
                print(f"[ERR] 事件线结构校验失败: {err}", file=sys.stderr)
                sys.exit(1)
            beats[n] = line
            _warn_empty_beats(n, line)
            bfp = _climax_baseline_fp(world_dir, n)
            if bfp.exists():
                bfp.unlink()
                print(f"[WARN] 旧基线落档已清理（{bfp.name}·结构替换后过期）——若停在顶点拍·需 beat set {n} 顶点 重拍", file=sys.stderr)
        data[STORYLINE_TOP_KEY] = beats
        write_yaml(fp, data)
        print(f"[OK] {STORYLINE_TOP_KEY} 事件线 {n} 已更新（{sub}）")
        return

    _storyline_usage()
    sys.exit(1)


def cmd_beat(world_dir: Path, extra: list[str]):
    """演出指针维护（states/direction.yaml）——③导演唯一通道（###BEAT 自动执行·LLM 不直接改 YAML）。
    set=初始指针 / stay=停留确认（无写入）/ advance=推进（禁回退·进入顶点自动记录基准快照）。"""
    if not extra or extra[0] in ("--help", "-h"):
        _beat_usage()
        sys.exit(0 if extra else 1)
    sub = extra[0]
    st = _load_storylines(world_dir)
    beats = st.get(STORYLINE_TOP_KEY) or {}
    dr = _load_direction(world_dir)

    if sub == "show":
        yaml.dump(dr, sys.stdout, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)
        return

    if sub not in ("set", "stay", "advance") or len(extra) < (3 if sub in ("set", "advance") else 2):
        _beat_usage()
        sys.exit(1)
    sid = _norm_sl_id(extra[1])
    line = beats.get(sid)
    if not isinstance(line, dict) or not (line.get("拍序") or []):
        print(f"[ERR] 事件线 {sid} 不存在或无拍序（先 ###STORYLINE: add 建线）", file=sys.stderr)
        sys.exit(1)
    names = [str(b.get("拍名", "")) for b in line.get("拍序", []) if isinstance(b, dict)]

    if sub == "stay":
        if str(dr.get("当前事件线", "") or "").strip() != sid or not str(dr.get("当前拍", "") or "").strip():
            print(f"[ERR] direction 指针不在事件线 {sid}（当前: {dr.get('当前事件线', '')}/{dr.get('当前拍', '')}）——stay 需已有指针（先 set）", file=sys.stderr)
            sys.exit(1)
        print(f"[OK] direction 事件线 {sid} 停留当前拍 {dr.get('当前拍')}（stay·下轮继续）", file=sys.stderr)
        return

    target = extra[2]
    if target not in names:
        print(f"[ERR] 拍名 '{target}' 不在事件线 {sid} 的拍序中（拍序拍名: {names}）", file=sys.stderr)
        sys.exit(1)
    if sub == "advance":
        cur_line = str(dr.get("当前事件线", "") or "").strip()
        cur = str(dr.get("当前拍", "") or "").strip()
        if cur_line == sid and cur and cur in names and names.index(cur) > names.index(target):
            print(f"[ERR] 当前拍回退（{cur}→{target}）不允许——节拍只向前推进（重规划走 ###STORYLINE: rewrite {sid}）", file=sys.stderr)
            sys.exit(1)
    dr["当前事件线"] = sid
    dr["当前拍"] = target
    # 当前戏剧问题缓存（validate 对账 storylines·防复制漂移）
    for b in line.get("拍序", []):
        if isinstance(b, dict) and str(b.get("拍名", "") or "").strip() == target:
            dr["当前戏剧问题"] = str(b.get("戏剧问题", "") or "").strip()
            break
    _save_direction(world_dir, dr)
    if target == "顶点":
        _snapshot_climax_baseline(line, world_dir, sid)
        st.setdefault(STORYLINE_TOP_KEY, {})[sid] = line
        write_yaml(world_dir / "states" / STORYLINES_FILE, st)
        print(f"[OK] 顶点约束.基准快照 已记录（事件线 {sid} 进入顶点拍·仅关系主体·按声明维度字段族）", file=sys.stderr)
    print(f"[OK] direction 事件线 {sid} 当前拍 → {target}（{sub}）", file=sys.stderr)


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


# ── LINT / FIX 引号/类型规范化 ────────────────────────────────────
_LEADING_SPECIAL = re.compile(r"^[\s]*(- |[\-\[\{\"#&*!|>%@`,? ])")
_YAML_BOOL_NULL = re.compile(r"^(yes|no|on|off|true|false|~|null)$", re.IGNORECASE)
_NUM_RE = re.compile(r"^(0[xXoO][0-9a-fA-F]+|\d+([.]\d*)?([eE][+-]?\d+)?|[+-]?\d+([.]\d*)?([eE][+-]?\d+)?)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?$")


def _strip_yaml_inline_comment(raw: str) -> str:
    """从 raw 值中剥离尾部 YAML 行内注释（# ...），保留引号包裹的实际值。
    处理：'...' # comment / "..." # comment / 无引号值尾部 # comment。"""
    raw_s = raw.rstrip()
    if not raw_s:
        return raw_s
    if raw_s.startswith("'"):
        i = 1
        while i < len(raw_s):
            if raw_s[i] == "'":
                if i + 1 < len(raw_s) and raw_s[i + 1] == "'":
                    i += 2
                else:
                    rest = raw_s[i + 1:].strip()
                    if not rest or rest.startswith("#"):
                        return raw_s[:i + 1]
                    return raw_s
            i += 1
    elif raw_s.startswith('"'):
        i = 1
        while i < len(raw_s):
            if raw_s[i] == "\\":
                i += 2
            elif raw_s[i] == '"':
                rest = raw_s[i + 1:].strip()
                if not rest or rest.startswith("#"):
                    return raw_s[:i + 1]
                return raw_s
            i += 1
    else:
        # 无引号值：剥离尾部 ` #...` 注释（YAML 规范：# 前须有空白才起注释）
        m = re.search(r"\s+#", raw_s)
        if m:
            candidate = raw_s[:m.start()].rstrip()
            if candidate:
                return candidate
    return raw_s


def _check_raw_needs_quoting(raw: str) -> tuple[bool, str]:
    """判断裸值是否需要引号包裹。返回 (needs_quote, reason)。"""
    if not raw:
        return False, ""
    # 先剥离注释再判断——注释不影响引号/类型安全
    clean = _strip_yaml_inline_comment(raw)
    # 已有引号包裹（单引号/双引号）→ 值安全，不需额外引号
    if (clean.startswith("'") and clean.endswith("'") and len(clean) >= 2) or \
       (clean.startswith('"') and clean.endswith('"') and len(clean) >= 2):
        return False, ""
    # 空容器 / block scalar 标记（去注释后）
    if clean in ("{}", "[]", "|", ">"):
        return False, ""
    # 以特殊字符开头 → 需引号
    if _LEADING_SPECIAL.match(clean):
        return True, "以特殊字符开头"
    # 含半角冒号+空格（YAML key: value 分隔符）→ 需引号
    if ":" in clean:
        for m in re.finditer(r":\s", clean):
            if m.start() > 0:
                return True, "含半角冒号+空格"
    # 隐式类型
    if _YAML_BOOL_NULL.match(clean):
        return True, "隐式类型(bool/null)"
    if _NUM_RE.match(clean) and not clean.startswith("0x") and not clean.startswith("0o"):
        return True, "隐式类型(数字)"
    if _DATE_RE.match(clean):
        return True, "隐式类型(日期)"
    return False, ""


def _to_single_quoted(val: str) -> str:
    escaped = val.replace("'", "''")
    return f"'{escaped}'"


def _detect_raw_needs_quoting(file_text: str) -> list[dict]:
    """逐行扫描原始 YAML 文本，报告需要引号包裹的值。"""
    issues = []
    in_block = False
    block_indent = 0
    in_multiline_quote = False  # 多行引号值（'...' 跨行）
    for lineno, line in enumerate(file_text.splitlines(), 1):
        if in_block:
            stripped = line.lstrip()
            if stripped and not stripped.startswith("#"):
                cur_indent = len(line) - len(stripped)
                if cur_indent <= block_indent:
                    in_block = False
                else:
                    continue
            elif not stripped:
                continue
            else:
                continue
        if in_multiline_quote:
            # 多行引号值：寻找闭合引号
            if "'" in line or '"' in line:
                # 简化检测：如果本行有闭合引号，退出多行模式
                for q in ("'", '"'):
                    if q in line:
                        # 检查是否有不被转义的闭合引号
                        count = line.count(q) - line.count(q * 2)
                        if count % 2 == 1:
                            in_multiline_quote = False
                            break
            continue
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^(\s*)(- )?(\S.*?)(:)(\s+.+)?$", line)
        if not m:
            continue
        indent, dash, key, colon, raw_part = m.groups()
        raw = (raw_part or "").strip() if raw_part else ""
        if raw in ("|", ">"):
            in_block = True
            block_indent = len(indent) + (2 if dash else 0) + len(key) + 1
            continue
        if not raw:
            continue
        if raw.startswith("[") and raw.endswith("]"):
            continue
        if raw.startswith("{") and raw.endswith("}"):
            continue
        # 检测多行引号值（起始引号但本行无闭合引号）
        if (raw.startswith("'") and not raw.endswith("'")) or \
           (raw.startswith('"') and not raw.endswith('"')):
            in_multiline_quote = True
            continue
        needs, reason = _check_raw_needs_quoting(raw)
        if needs:
            issues.append({"line": lineno, "key": key.strip(), "raw": raw, "reason": reason})
    return issues


def _fix_yaml_text(data: dict | list | None, original_text: str) -> str:
    """规范化 YAML：修复所有字符串值的引号/类型，保留 key 顺序、注释、block scalar。"""
    lines = original_text.splitlines(keepends=True)
    result = []
    in_block = False
    block_indent = 0
    in_multiline_quote = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if in_block:
            cur_indent = len(line) - len(stripped) if stripped else 999
            if stripped and not stripped.startswith("#"):
                if cur_indent <= block_indent:
                    in_block = False
                else:
                    result.append(line)
                    i += 1
                    continue
            elif not stripped:
                result.append(line)
                i += 1
                continue
            else:
                result.append(line)
                i += 1
                continue
        if in_multiline_quote:
            # 多行引号值：等待闭合引号
            result.append(line)
            if ("'" in line or '"' in line):
                for q in ("'", '"'):
                    if q in line:
                        count = line.count(q) - line.count(q * 2)
                        if count % 2 == 1:
                            in_multiline_quote = False
                            break
            i += 1
            continue
        if not stripped or stripped.startswith("#"):
            result.append(line)
            i += 1
            continue
        m = re.match(r"^(\s*)(- )?(\S.*?)(:)(\s+.+)?$", line.rstrip("\n"))
        if not m:
            result.append(line)
            i += 1
            continue
        indent, dash, key, colon, raw_part = m.groups()
        raw = (raw_part or "").strip() if raw_part else ""
        if raw in ("|", ">"):
            in_block = True
            block_indent = len(indent) + (2 if dash else 0) + len(key) + 1
            result.append(line)
            i += 1
            continue
        if not raw or (raw.startswith("[") and raw.endswith("]")) or (raw.startswith("{") and raw.endswith("}")):
            result.append(line)
            i += 1
            continue
        # 检测多行引号值（起始引号但本行无闭合引号）
        if (raw.startswith("'") and not raw.endswith("'")) or \
           (raw.startswith('"') and not raw.endswith('"')):
            in_multiline_quote = True
            result.append(line)
            i += 1
            continue
        already_quoted = (raw.startswith("'") and raw.endswith("'") and len(raw) >= 2) or \
                         (raw.startswith('"') and raw.endswith('"') and len(raw) >= 2)
        if already_quoted:
            inner = raw[1:-1]
            expected = _to_single_quoted(inner)
            if raw != expected:
                prefix = f"{indent}{dash or ''}{key}{colon} "
                result.append(f"{prefix}{expected}\n")
                i += 1
                continue
            result.append(line)
            i += 1
            continue
        needs_q, _ = _check_raw_needs_quoting(raw)
        if needs_q:
            prefix = f"{indent}{dash or ''}{key}{colon} "
            result.append(f"{prefix}{_to_single_quoted(raw)}\n")
            i += 1
            continue
        result.append(line)
        i += 1
    return "".join(result)


def cmd_lint(world_dir: Path):
    """lint: 逐文件报告 YAML 引号/类型问题（只读）。"""
    scene_dir = get_scene_dir(world_dir)
    files = discover_files(world_dir, scene_dir)
    total_issues = 0
    broken_files = 0
    for key in sorted(files):
        fp = files[key]
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[ERR] {key}: 读取失败: {e}")
            continue
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as e:
            print(f"[BROKEN] {key}: YAML 解析错误: {e}")
            broken_files += 1
            continue
        issues = _detect_raw_needs_quoting(text)
        if issues:
            for iss in issues:
                print(f"  L{iss['line']:3d}  {iss['key']}:  {iss['raw'][:40]}  → {iss['reason']}")
            total_issues += len(issues)
            print(f"[WARN] {key}: {len(issues)} 个值需要引号/类型修复")
        else:
            print(f"[OK] {key}: 无问题")
    print(f"\n汇总: {len(files)} 个文件, {broken_files} 个坏文件（需手动修复）, {total_issues} 个值需要引号/类型修复")
    if broken_files:
        print("坏文件无法被 write-raw 解析·拒绝写入——先用编辑器直接修复引号后再走 write-raw")


def cmd_fix(world_dir: Path):
    """fix: 规范化重写所有 YAML 状态文件（snap 自动备份 + validate）。"""
    scene_dir = get_scene_dir(world_dir)
    files = discover_files(world_dir, scene_dir)
    fixed = 0
    skipped = 0
    broken = 0
    for key in sorted(files):
        fp = files[key]
        try:
            text = fp.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[ERR] {key}: 读取失败: {e}")
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            print(f"[SKIP] {key}: YAML 解析错误（坏文件·需手动修复）: {e}")
            broken += 1
            continue
        if data is None:
            print(f"[SKIP] {key}: 空文件")
            skipped += 1
            continue
        fixed_text = _fix_yaml_text(data, text)
        if fixed_text == text:
            skipped += 1
            continue
        bak = fp.with_suffix(".yaml.fix.bak")
        bak.write_text(text, encoding="utf-8", newline="")
        fp.write_text(fixed_text, encoding="utf-8", newline="")
        print(f"[FIX] {key}: 已修复（备份 → {bak.name}）")
        fixed += 1
    if fixed:
        print(f"\n已修复 {fixed} 个文件，跳过 {skipped} 个，坏文件 {broken} 个")
        print("正在 validate...")
        cmd_validate(world_dir)
    else:
        print(f"\n无需修复（{skipped} 个文件已是最新，坏文件 {broken} 个）")


def cmd_reset_cycle(world_dir: Path, world_name: str, asset: str = None):
    """循环世界重置——周期重置（循环日终/到期点）或事件触发重置（单角色 --asset）。
    周期（缺省）：机械重置全员·登记重置记录·重建周期倒计时。
    事件触发（--asset <角色>）：只机械重置指定角色·登记事件触发重置记录·不重建周期倒计时（叙事事件不移动周期重置点）。
    触发：周期=write-raw audit ④b 顶回后执行（或恢复序列 4.6②）；事件触发=叙事中角色被系统强制重置（loop_machinery §4 触发管道之二）。
    脚本做机械部分：
    反应轨迹清空 / 记忆锚点按自主性档位压缩（脚本全清·漂移/觉醒压缩+输出保留候选·变质保留）/
    状态字段回基线占位 / 压力防御回默认（觉醒/变质保留防御崩解）/ 人际动态与决策清空（LLM 按 LOOPS 补写）/
    信念演化与自主性保留 / 自动存档（snap.py save _before_）/ 登记重置记录 / 周期模式重建周期倒计时（到期时刻+1 周期）。
    LLM 只做：保留候选确认/微调 + 状态字段按 LOOPS 补写 + CT 节拍核查 + 重置叙事。"""
    ws_fp = world_dir / "states" / "world_state.yaml"
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
        print("[WARN] 未找到含 到期时刻 的周期倒计时——重置仍执行（周期倒计时登记见 session_recovery.md §第二章启动世界·循环机制核对）", file=sys.stderr)

    # 0. 自动存档（可回滚）
    import subprocess
    snap_script = Path(__file__).parent / "snap.py"
    # 安全加固：world_name 必须为合法世界目录名（禁空/路径分隔符/..·与 snap.py validate_name 同规则）——防非法名传入外部脚本
    if not world_name or re.search(r"[\\/]|\.\.", world_name):
        print(f"[ERR] 非法世界名 '{world_name}'——拒绝调用 snap.py（禁止路径分隔符/../相对路径穿越）", file=sys.stderr)
        sys.exit(1)
    snap_name = f"_before_reset_{'asset_' + asset if asset else 'cycle_' + world_name}_{_ts()}"
    try:
        r = subprocess.run([sys.executable, str(snap_script), world_name, "save", snap_name],
                           capture_output=True, text=True, timeout=120)
        print(f"[OK] 自动存档: {snap_name}（{r.stdout.strip()[:200] if r.stdout.strip() else 'snap.py 输出为空'}）")
    except Exception as e:
        print(f"[WARN] 自动存档失败（继续执行）: {e}", file=sys.stderr)

    # 机械重置（周期=全员含焦外·事件触发=单角色 --asset）
    candidates = []          # (角色, 档位, 被压缩条目) 保留候选
    key_anchor_kw = ("承诺", "命名", "关系转折", "决定", "记得", "承诺", "他/她")
    if asset:
        cfps = [world_dir / "states" / f"{CHAR_STATE_PREFIX}{asset}{CHAR_STATE_SUFFIX}"]
        if not cfps[0].exists():
            print(f"[ERR] 未找到角色状态文件: {cfps[0].name}（--asset 用角色名·如 Angela）", file=sys.stderr)
            return 1
    else:
        cfps = sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}"))
    for cfp in cfps:
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
        # 豁免记录（2026-08-17 加入）：重置记录 触发=豁免 且 重置日期=当前重置点日期 → 本轮跳过（园区维护人员按指示跳过该资产）
        #   豁免一次性：按重置日期精确匹配——只覆盖登记的那一轮·后续重置点不匹配 → 照常重置；豁免角色不登记周期记录（保留豁免标记·validate 8b 跳过）
        _rname = cfp.stem[len(CHAR_STATE_PREFIX):-len("_state")]
        _rr = ws.get("重置记录") or {}
        if isinstance(_rr, dict) and _rname in _rr and isinstance(_rr[_rname], dict) \
                and str(_rr[_rname].get("触发", "")) == "豁免" \
                and str(_rr[_rname].get("重置日期", "")) == f"第{cur_day}日":
            print(f"[SKIP] {cfp.stem}: 本轮豁免（重置记录·触发=豁免·维护人员跳过）")
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
        # 轨迹清空（联动表·新循环从零累积；反应轨迹=旧字段兼容·连续行动轨迹=v0.12 角色时间线）
        cdata["反应轨迹"] = ""
        cdata["连续行动轨迹"] = []
        # decision 重置（v0.12 联动表扩展）：当前计划回 LOOPS 基线（LLM 按 LOOPS 补写）·当前行动/未完成意图/行动窗口清空
        if isinstance(cdata.get("decision"), dict):
            for subk in ("当前计划", "当前行动", "未完成意图", "行动窗口"):
                cdata["decision"][subk] = ""
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

    # 登记重置记录（{档位/轮次/重置日期/触发}——周期=全员循环角色·事件触发=仅 asset）
    reset_rec = ws.get("重置记录") or {}
    if not isinstance(reset_rec, dict):
        reset_rec = {}
    for cfp in cfps:
        try:
            cdata = yaml.safe_load(cfp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        # 豁免者（无自主性字段·外部者/管理者）不登记重置记录
        if "自主性" not in cdata or not str(cdata.get("自主性", "") or "").strip():
            continue
        name = cfp.stem[len(CHAR_STATE_PREFIX):-len("_state")]
        # 本轮豁免角色（重置记录 触发=豁免 且 重置日期=当日）不登记周期记录——保留豁免标记（validate 8b 跳过·豁免过期由后续重置自然覆盖）
        _rr0 = ws.get("重置记录") or {}
        if isinstance(_rr0, dict) and name in _rr0 and isinstance(_rr0[name], dict) \
                and str(_rr0[name].get("触发", "")) == "豁免" \
                and str(_rr0[name].get("重置日期", "")) == f"第{cur_day}日":
            continue
        lvl = str(cdata.get("自主性", "") or "").strip()
        reset_rec[name] = {"档位": lvl, "轮次": cur_round, "重置日期": f"第{cur_day}日", "触发": "事件触发" if asset else "周期"}
    ws["重置记录"] = reset_rec

    # 重建周期倒计时（到期时刻 +1 周期·仅周期重置——事件触发不移动周期重置点）
    if cd_id is not None and asset is None:
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
    print("\n【重置完成】" + ("（事件触发·单角色）" if asset else "（周期·全员）"))
    print(f"  时间 {cur_time} · 轮次 {cur_round} · 重置记录 {len(reset_rec)} 角色")
    print("【LLM 后续动作（非脚本）】")
    print("  1. 状态字段（核心状态/情绪/决策状态/人际动态/已知地点）按该角色 CHAR_ 默认循环时间线当前时段补写")
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


def _region_consistency(world_dir: Path) -> str | None:
    """区域一致性检查（场景切换主判据·机械复核）：
    POV 角色位置的 REGION 节点 vs 焦点场景 scene_card「区域」节点——不一致=空间已变但场景切换未执行。
    判据来源：scene_management §移动场景协议 主判据（有 regions/ 目录树时机械接管）。
    返回 FAIL 消息字符串；PASS 或无法判定（无目录树/路径解析不了→迷雾制世界走 LLM 三层规则判断）返回 None。"""
    regions_dir = world_dir / "regions"
    if not regions_dir.is_dir():
        return None
    tree_paths = sorted(
        (p.parent.relative_to(regions_dir).as_posix() for p in regions_dir.rglob("REGION.md")),
        key=len, reverse=True,
    )
    if not tree_paths:
        return None
    # 焦点场景区域节点（scene_card「区域」行）
    scene_dir = get_scene_dir(world_dir)
    if scene_dir is None:
        return None
    card_fp = scene_dir / "scene_card.md"
    if not card_fp.exists():
        return None
    m = re.search(r"^\|\s*区域\s*\|\s*([^|]+?)\s*\|", card_fp.read_text(encoding="utf-8", errors="ignore"), re.M)
    if not m:
        return None
    am = re.search(r"regions/(.+?)/REGION\.md$", m.group(1).strip().replace("\\", "/"))
    if not am:
        return None
    scene_node = am.group(1)
    # POV 角色定位：叙事约定 POV=… 优先，CHAR_Guest* 兜底
    try:
        ws = yaml.safe_load((world_dir / "states" / "world_state.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        ws = {}
    states_dir = world_dir / "states"

    def _char_state(name: str):
        fp = states_dir / f"{CHAR_STATE_PREFIX}{name}{CHAR_STATE_SUFFIX}"
        return fp if fp.exists() else None

    pov_fp = None
    mm = re.search(r"POV\s*=\s*([^；;\n]*)", str(ws.get("叙事约定", "") or ""))
    if mm:
        seg = mm.group(1)
        cands = re.findall(r"[（(]([^（）()]+)[)）]", seg) + [t for t in re.split(r"[·,，、\s]+", seg) if t]
        for c in cands:
            pov_fp = _char_state(c.strip())
            if pov_fp:
                break
    if pov_fp is None:
        guests = sorted(states_dir.glob(f"{CHAR_STATE_PREFIX}Guest*{CHAR_STATE_SUFFIX}"))
        pov_fp = guests[0] if guests else None
    if pov_fp is None:
        return None
    try:
        cs = yaml.safe_load(pov_fp.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    pos = re.sub(r"[（(][^（）()]*[)）]", "", str(cs.get("位置", "") or "")).strip().replace("\\", "/").strip("/")
    if not pos:
        return None
    # 后缀匹配（对齐 validate 4e：位置从角色认知根开始·不含顶层园区前缀）
    hits = [p for p in tree_paths if p == pos or p.endswith("/" + pos)]
    pos_node = hits[0] if len(hits) == 1 else (max(hits, key=len) if hits else None)
    if pos_node is None:
        return None
    if pos_node != scene_node:
        pov_name = pov_fp.name[len(CHAR_STATE_PREFIX):-len(CHAR_STATE_SUFFIX)]
        return (
            f"区域一致性 FAIL——POV '{pov_name}' 所在区域节点 '{pos_node}' ≠ 焦点场景 {scene_dir.name} "
            f"区域节点 '{scene_node}'（空间已变·场景切换未执行——按 scene_management §移动场景协议 主判据先执行场景切换流程再继续落盘）"
        )
    return None


def cmd_round_check(world_dir: Path):
    """轮完整性检查（⑤场记收尾调用·每轮）——六阶段分批写入后的状态一致性对账：
    ① direction 已写（或无事件线世界声明豁免）② world_state 三件套（时间/轮次/前情）
    ③ 焦点场景 场景时间线非空 ④ direction↔storylines↔CT.事件线引用 对账。
    输出逐项 PASS/FAIL；任一 FAIL exit 1（场记本阶段修复或上报）。"""
    fails = []
    st = _load_storylines(world_dir)
    sl_map = st.get(STORYLINE_TOP_KEY) or {}
    dr = _load_direction(world_dir)
    # ① direction
    if sl_map:
        if not dr:
            fails.append("direction.yaml 缺失——storylines 有事件线但导演状态文件不存在（③导演未写）")
        else:
            cur_sl = str(dr.get("当前事件线", "") or "").strip()
            if not cur_sl:
                fails.append("direction.当前事件线 为空——③导演本轮未写指针")
            elif cur_sl not in sl_map:
                fails.append(f"direction.当前事件线 '{cur_sl}' 不在 storylines 中")
            if dr and not str(dr.get("承接判断", "") or "").strip():
                fails.append("direction.承接判断 为空——③导演回判留痕缺失（核心三件之一）")
    else:
        print("[ROUND] storylines 无事件线——①direction 检查豁免（无事件线世界/首轮）")
    # ② world_state 三件套
    try:
        ws = yaml.safe_load((world_dir / "states" / "world_state.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        ws = {}
    for k, label in (("轮次", "轮次"), ("前情描述", "时间.前情描述")):
        if not str(ws.get(k, "") if k == "轮次" else (ws.get("时间", {}) or {}).get("前情描述", "") or "").strip():
            fails.append(f"world_state.{label} 缺失——⑤场记收尾未写")
    if not str((ws.get("时间", {}) or {}).get("具体时间", "") or "").strip():
        fails.append("world_state.时间.具体时间 缺失——⑤场记收尾未写")
    # ③ 焦点场景时间线
    scene_dir = get_scene_dir(world_dir)
    if scene_dir is None:
        fails.append("无法定位焦点场景目录——world_state.焦点场景 缺失或目录不存在")
    else:
        sfp = scene_dir / "scene_state.yaml"
        if not sfp.exists():
            fails.append(f"{scene_dir.name}/scene_state.yaml 不存在")
        else:
            try:
                sd = yaml.safe_load(sfp.read_text(encoding="utf-8")) or {}
                tl = str(sd.get("场景时间线", "") or "").strip()
                if not tl:
                    fails.append(f"{scene_dir.name}/scene_state.场景时间线 为空——⑤场记未追加本轮事件")
            except Exception:
                fails.append(f"{scene_dir.name}/scene_state.yaml 解析失败")
    # ④ CT 引用对账
    try:
        cd = yaml.safe_load((world_dir / "states" / "conflicts.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        cd = {}
    for k, cv in cd.items():
        if re.match(r"^CT-\d{2}$", str(k)) and isinstance(cv, dict):
            refs = cv.get("事件线引用")
            bad = [str(r) for r in (refs if isinstance(refs, list) else ([refs] if isinstance(refs, str) and refs.strip() else [])) if str(r) not in sl_map]
            if bad:
                fails.append(f"conflicts.{k}.事件线引用 悬空: {bad}")
    # ⑤ 区域一致性（场景切换主判据·机械复核）
    rc_fail = _region_consistency(world_dir)
    if rc_fail:
        fails.append(rc_fail)
    if fails:
        print(f"[ROUND] 轮完整性检查 FAIL（{len(fails)} 项）:", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print("[ROUND] 轮完整性检查通过 ✅（direction/世界三件套/场景时间线/引用对账）")


def cmd_in_track(world_dir: Path):
    """只读查询：按各循环角色预设时间线，输出此刻各循环角色应在哪/做什么（供导演调度参考·不改任何角色）。"""
    cur = {}
    try:
        cur = yaml.safe_load((world_dir / "states" / "world_state.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    t = str((cur.get("时间") or {}).get("具体时间") or "")
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    cur_min = (int(m.group(1)) * 60 + int(m.group(2))) if m else None
    print(f"# 世界时间: {t or '(未知)'}")
    chars_dir = world_dir / "characters"
    if not chars_dir.is_dir():
        print("# 无 characters/ 目录")
        return
    for cfp in sorted(chars_dir.glob("CHAR_*.md")):
        try:
            lines = cfp.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        in_table = False
        rows = []
        for ln in lines:
            if "默认循环时间线" in ln:
                in_table = True
                continue
            if not in_table:
                continue
            s = ln.strip()
            if s.startswith("|") and s.count("|") >= 3:
                cells = [c.strip() for c in s.strip("|").split("|")]
                if len(cells) >= 3:
                    sm = re.search(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", cells[0])
                    if sm:
                        rows.append((int(sm.group(1)) * 60 + int(sm.group(2)),
                                     int(sm.group(3)) * 60 + int(sm.group(4)), cells[1], cells[2]))
            elif s and not s.startswith("#") and "|" not in s:
                break
        name = cfp.stem[len("CHAR_"):].replace("_state", "").strip()
        if not rows:
            print(f"- {name}: 无可用时间线")
            continue
        if cur_min is None:
            s0, e0, loc, ac = rows[0]
            print(f"- {name}: {loc} · {ac}（时间未解析·取最早段）")
            continue
        hit = next(((loc, ac) for s0, e0, loc, ac in rows if s0 <= cur_min <= e0), None)
        if hit:
            print(f"- {name}: {hit[0]} · {hit[1]}")
        else:
            print(f"- {name}: {rows[0][2]} · {rows[0][3]}（时段外·取最早段）")


def cmd_migrate(world_dir: Path, world_name: str):
    """v0.11 → v0.12 数据迁移（一次性·幂等检测）：
    ① conflicts.顶层节拍表 → states/storylines.yaml（事件→戏剧问题·字段平移·id N→SL-XX）
    ② CT.当前节拍.拍名 → states/direction.yaml（当前事件线/当前拍）；CT.当前节拍.{关系状态,内部状态,相位} → CT 顶层
    ③ CT.角色反应 / 下一个节拍(推荐) → 收集到迁移报告（LLM 辅助翻译进 CHAR_state.连续行动轨迹 / direction.guidance）
    ④ conflicts 清除已迁移字段 ⑤ validate 全通过。
    自动 snap 存档（_before_migrate_）可回滚。"""
    conflicts_fp = world_dir / "states" / "conflicts.yaml"
    if not conflicts_fp.exists():
        print("[ERR] conflicts.yaml 不存在——无需迁移", file=sys.stderr)
        return 1
    try:
        cdata = yaml.safe_load(conflicts_fp.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[ERR] conflicts.yaml 解析失败: {e}", file=sys.stderr)
        return 1
    if not isinstance(cdata, dict):
        cdata = {}
    beats = cdata.get(BEAT_TOP_KEY)
    has_legacy_ct = any(isinstance(v, dict) and any(f in v for f in ("当前节拍", "下一个节拍(推荐)"))
                        for v in cdata.values() if isinstance(v, dict))
    if not isinstance(beats, dict) and not has_legacy_ct:
        print("[OK] 未检测到 v0.11 结构（无节拍表/无当前节拍）——无需迁移")
        return 0
    if (world_dir / "states" / STORYLINES_FILE).exists() and (world_dir / "states" / DIRECTION_FILE).exists() and not has_legacy_ct:
        print("[SKIP] storylines/direction 已存在且无旧字段残留——迁移已完成（幂等）")
        return 0

    # 0. 自动存档（可回滚）
    import subprocess
    snap_script = Path(__file__).parent / "snap.py"
    if not world_name or re.search(r"[\\/]", world_name):
        print(f"[ERR] 非法世界名 '{world_name}'", file=sys.stderr)
        sys.exit(1)
    snap_name = f"_before_migrate_{world_name}_{_ts()}"
    try:
        r = subprocess.run([sys.executable, str(snap_script), world_name, "save", snap_name],
                           capture_output=True, text=True, timeout=120)
        print(f"[OK] 迁移前自动存档: {snap_name}")
    except Exception as e:
        print(f"[WARN] 自动存档失败（继续执行）: {e}", file=sys.stderr)

    report_lines: list[str] = ["# v0.11 → v0.12 迁移报告（LLM 辅助步骤）", ""]
    # ① 节拍表 → storylines
    st = _load_storylines(world_dir)
    sl_map = st.get(STORYLINE_TOP_KEY)
    if sl_map is None:
        sl_map = {}
    if isinstance(beats, dict) and beats:
        for n, ln in beats.items():
            if not isinstance(ln, dict) or not ln:
                continue
            sid = _norm_sl_id(n)
            new_ln = dict(ln)
            new_ln["名称"] = str(ln.get("事件线", "") or f"事件线{sid}").strip() or f"事件线{sid}"
            # 字段映射：事件 → 戏剧问题
            for b in (new_ln.get("拍序") or []):
                if isinstance(b, dict) and "事件" in b and "戏剧问题" not in b:
                    b["戏剧问题"] = b.pop("事件")
            new_ln.pop("事件线", None)
            new_ln.pop("当前拍", None)  # 指针迁 direction
            new_ln.setdefault("类型", "")
            new_ln.setdefault("状态", "活跃")
            sl_map[sid] = new_ln
            print(f"[OK] 节拍表.{n} → storylines.事件线.{sid}（戏剧问题映射·当前拍迁 direction）")
        st[STORYLINE_TOP_KEY] = sl_map
        write_yaml(world_dir / "states" / STORYLINES_FILE, st)

    # ② CT 迁移 + ③ 报告收集 + ④ 清除
    dr = _load_direction(world_dir)
    changed = False
    for k, cv in list(cdata.items()):
        if not re.match(r"^CT-\d{2}$", str(k)) or not isinstance(cv, dict):
            continue
        cp = cv.pop("当前节拍", None)
        if isinstance(cp, dict):
            beat_name = str(cp.get("拍名", "") or "").strip()
            for fld in ("关系状态", "内部状态", "相位"):
                if fld in cp:
                    cv[fld] = cp[fld]
            nxt = cv.pop("下一个节拍(推荐)", None)
            m = re.match(r"^(\d+)[-·](.+)$", beat_name)
            if m:
                sid = _norm_sl_id(m.group(1))
                dr["当前事件线"] = sid
                dr["当前拍"] = m.group(2).strip()
                cv.setdefault("事件线引用", [sid])
                print(f"[OK] {k}.当前节拍.拍名 '{beat_name}' → direction（{sid}/{dr['当前拍']}）·关系状态/内部状态/相位 升 CT 顶层")
            if cp.get("角色反应"):
                report_lines.append(f"## {k}.角色反应（待 LLM 翻译进对应 CHAR_state.连续行动轨迹 七子字段）")
                report_lines.append(str(cp["角色反应"]))
                report_lines.append("")
            if nxt:
                report_lines.append(f"## {k}.下一个节拍(推荐)（待 LLM 提炼进 direction.guidance·只写问题+张力方向）")
                report_lines.append(str(nxt))
                report_lines.append("")
            changed = True
        elif "下一个节拍(推荐)" in cv:
            nxt = cv.pop("下一个节拍(推荐)")
            report_lines.append(f"## {k}.下一个节拍(推荐)（待 LLM 提炼进 direction.guidance）")
            report_lines.append(str(nxt))
            report_lines.append("")
            changed = True
    if isinstance(beats, dict) and BEAT_TOP_KEY in cdata:
        cdata.pop(BEAT_TOP_KEY)
        changed = True
    if changed:
        write_yaml(conflicts_fp, cdata)
    if dr:
        dr.setdefault("演出状态", "持续")
        _save_direction(world_dir, dr)
    # ⑤ 决策状态 prose 报告（LLM 辅助结构化为 decision）
    for cfp in sorted(world_dir.glob(f"states/{CHAR_STATE_PREFIX}*{CHAR_STATE_SUFFIX}")):
        try:
            sd = yaml.safe_load(cfp.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if isinstance(sd, dict) and str(sd.get("决策状态", "") or "").strip():
            report_lines.append(f"## {cfp.name}.决策状态（待 LLM 结构化为 decision 八子字段）")
            report_lines.append(str(sd["决策状态"]))
            report_lines.append("")
    report_fp = world_dir / "tmp" / "migrate_report.md"
    report_fp.parent.mkdir(parents=True, exist_ok=True)
    report_fp.write_text("\n".join(report_lines), encoding="utf-8", newline="")
    print(f"[OK] 迁移报告: {report_fp.relative_to(world_dir)}（LLM 辅助步骤：角色反应→连续行动轨迹·下一个节拍→guidance·决策状态→decision）")
    print("[下一步] 运行 validate → 按迁移报告完成 LLM 辅助翻译 → 再跑 validate 全通过")
    cmd_validate(world_dir)
    return 0


# ── CLI ───────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="WorldSim 批量状态管理 V2")
    parser.add_argument("world", help="世界名")
    parser.add_argument("action", choices=["read", "write", "write-raw", "append-raw", "delete", "convert", "validate", "audit", "grep", "scan", "gate", "storyline", "beat", "reset-cycle", "round-check", "migrate", "tmp-clean", "map-sync", "init-states", "lint", "fix", "in-track"])
    parser.add_argument("--files", help="read 时限定文件 key 列表，逗号分隔")
    parser.add_argument("--full", action="store_true", help="write 时全量覆写")
    parser.add_argument("--batch", action="store_true", help="write-raw/append-raw 批量模式：stdin 为 ###FILE/###KEY/###APPEND 记录格式（⚠非幂等：APPEND 重复执行会重复追加·同一批次只执行一次·验证用 read/validate/--dry-run）")
    parser.add_argument("--dry-run", action="store_true", help="write-raw/append-raw 预演：解析+audit+对比磁盘差异，不落盘（重跑批次前先对比）")
    parser.add_argument("--check", action="store_true", help="gate 代码化核验模式：从 stdin 读 change set（dramatist）或叙事（writer），运行可代码化检查，不合格 exit 1")
    parser.add_argument("--live", action="store_true", help="scan 仅当前文件（排除历史轮转 narrative.*.md 与 archive）")
    parser.add_argument("--force", action="store_true", help="write-raw/append-raw --batch: 显式回退轮·绕过 audit ④ 轮次单调/⑬b 轨迹覆盖写（其余硬性检查照常·回退后必做残留扫描+validate）")
    parser.add_argument("--asset", help="reset-cycle: 事件触发重置指定角色（单角色模式·登记事件触发重置记录·不重建周期倒计时）")
    parser.add_argument("extra", nargs="*", help="write-raw/append-raw 的额外参数: <文件key> <YAML键路径> [内容]")
    # storyline/beat 子命令 help 直达（argparse 内建 --help 会拦截并打印全局 help）
    argv = sys.argv[1:]
    if len(argv) >= 3 and argv[1] in ("storyline", "beat") and argv[2] in ("--help", "-h"):
        fn = cmd_storyline if argv[1] == "storyline" else cmd_beat
        fn(get_world_dir(argv[0]), ["--help"])
        sys.exit(0)
    args = parser.parse_args()

    world_dir = get_world_dir(args.world)

    if args.action == "read":
        # 文件过滤：--files a,b,c 或位置参数（commands.md：位置参数=文件 key 过滤）
        files_filter = None
        if args.files:
            files_filter = args.files.split(",")
        elif args.extra:
            files_filter = [a for a in args.extra if not a.startswith("-")]
        cmd_read(world_dir, files_filter)
    elif args.action == "write":
        cmd_write(world_dir, full_replace=args.full)
    elif args.action == "write-raw":
        cmd_write_raw(world_dir, args.extra, batch=args.batch, dry_run=args.dry_run, force=args.force)
    elif args.action == "append-raw":
        cmd_write_raw(world_dir, args.extra, batch=args.batch, append_mode=True, dry_run=args.dry_run, force=args.force)
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
    elif args.action == "storyline":
        cmd_storyline(world_dir, args.extra)
    elif args.action == "beat":
        cmd_beat(world_dir, args.extra)
    elif args.action == "reset-cycle":
        sys.exit(cmd_reset_cycle(world_dir, args.world, asset=args.asset))
    elif args.action == "round-check":
        cmd_round_check(world_dir)
    elif args.action == "migrate":
        sys.exit(cmd_migrate(world_dir, args.world) or 0)
    elif args.action == "map-sync":
        cmd_map_sync(world_dir)
    elif args.action == "init-states":
        sys.exit(cmd_init_states(world_dir) or 0)
    elif args.action == "tmp-clean":
        cmd_tmp_clean(world_dir)
    elif args.action == "lint":
        cmd_lint(world_dir)
    elif args.action == "fix":
        cmd_fix(world_dir)
    elif args.action == "in-track":
        cmd_in_track(world_dir)

if __name__ == "__main__":
    main()
