#!/usr/bin/env python3
"""
import_card.py — SillyTavern 兼容角色卡提取（解析+完整留存+预览）

用法:
  python scripts/import_card.py <世界名> <角色卡.png> [更多.png ...]
  python scripts/import_card.py <世界名> <角色卡.json>          ← 也支持纯 JSON 角色卡
  python scripts/import_card.py <世界名> --dry-run <角色卡.png> ← 只解析预览，不落盘

职责分工（脚本=机械提取 · Agent LLM=综合生成）:
  脚本:
    1. 解析 PNG tEXt chunk（keyword: chara / ccv3）中的 base64 JSON，或直接读 .json 文件
    2. 格式归一化: V1 平铺 / V2 {spec,data} / V3 extensions.ccv3 → 统一字典
    3. 【完整字段留存】全部字段（含 alternate_greetings / character_book / creator_notes /
       metadata / character_version 等一个不丢）→ <世界>/import/{名}.card.json
    4. 打印结构化摘要（字段+内容预览）供 LLM 综合
  脚本【不】生成 CHAR.md——不做性格词表/职业正则/字段分发等死代码理解。
  综合生成由 Agent LLM 完成（读 card.json 全部原文 → 按 templates/CHAR_.md 结构：
    description 拆分发到 性格/整体形象/外貌/背景；personality 提炼性格+生平；
    alternate_greetings → 情景与叙事·备用开场白；character_book → 背景知识条目；
    八变量从性格/背景综合提炼，无依据留空）。

约束:
  - 已有 CHAR_{名}.md 的卡片 → 跳过（防覆盖——CHAR.md 生成后运行中不修改）
  - 角色名按 Windows 文件名规范消毒（\\/:*?"<>| → -），含空格保留空格
  - 素材文件放 <世界>/import/（已 gitignore），不干扰 validate/scan

路径推导: 基于脚本相对位置或 WORLDSIM_DIR 环境变量，禁止硬编码。
"""
import sys, os, re, json, base64, struct
from pathlib import Path

SKILL_DIR = Path(os.environ.get("WORLDSIM_DIR", Path(__file__).resolve().parent.parent))
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')

# 与 WorldSim 引擎语义冲突、永不导入的字段（仍在 card.json 完整留存供溯源，不注入引擎）
NOT_IMPORTED = ["system_prompt", "post_history_instructions"]


def get_world_dir(world: str) -> Path:
    wd = SKILL_DIR / "worlds" / world
    if not wd.is_dir():
        print(f"[ERR] 世界 '{world}' 不存在: {wd}", file=sys.stderr)
        print(f"      提示: 先执行 'sh scripts/create_world.sh <世界名>' 创建世界，或确认世界名正确", file=sys.stderr)
        sys.exit(1)
    return wd


def sanitize_name(name: str, fallback: str) -> str:
    """角色名消毒：去首尾空白 + Windows 非法字符替换。空名回退到文件名。"""
    name = (name or "").strip()
    if not name:
        name = fallback
    return INVALID_FILENAME_CHARS.sub("-", name)


def read_card_text(png_path: Path) -> str | None:
    """从 PNG tEXt chunk 提取角色卡 JSON 文本。非 PNG → None。"""
    if png_path.suffix.lower() == ".json":
        return None
    data = png_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        print(f"[WARN] '{png_path.name}' 不是 PNG 文件——跳过", file=sys.stderr)
        return None
    pos = 8
    try:
        while pos < len(data):
            ln = struct.unpack(">I", data[pos:pos + 4])[0]
            typ = data[pos + 4:pos + 8].decode("latin1")
            if typ == "tEXt":
                payload = data[pos + 8:pos + 8 + ln]
                sep = payload.find(b"\x00")
                if sep == -1:
                    continue
                keyword = payload[:sep].decode("latin1", "replace")
                if keyword in ("chara", "ccv3"):
                    return payload[sep + 1:].decode("latin1", "replace")
            elif typ == "IEND":
                break
            pos += 12 + ln
    except Exception:
        pass
    return None


def normalize_card(raw: dict) -> tuple[dict, str]:
    """V1/V2/V3 → 统一字典 + 版本标签。"""
    if isinstance(raw, dict) and raw.get("spec") == "chara_card_v3":
        d = raw.get("data")
        return (d if isinstance(d, dict) else raw), "V3"
    if isinstance(raw, dict) and raw.get("spec") == "chara_card_v2":
        d = raw.get("data")
        return (d if isinstance(d, dict) else raw), "V2"
    if isinstance(raw, dict) and isinstance(raw.get("extensions"), dict):
        v3 = raw["extensions"].get("ccv3")
        if isinstance(v3, dict):
            d = v3.get("data")
            return (d if isinstance(d, dict) else v3), "V3"
    return raw, "V1"


def brief(value, limit: int = 120) -> str:
    """摘要显示：字符串截断 / 列表计数 / 字典计数。"""
    if isinstance(value, str):
        return f"{len(value)}字 | {value.strip()[:limit]}"
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(v, str) for v in value):
            return f"{len(value)}项 | " + "，".join(str(v) for v in value)[:limit]
        return f"{len(value)}项（结构）"
    if isinstance(value, dict):
        return f"{len(value)}键（结构）"
    return str(value)[:limit]


def build_material_json(card: dict, version: str) -> dict:
    """素材文件：完整字段留存（一个不丢）+ 导入元信息。"""
    material = dict(card)  # 全部字段完整留存（含嵌套结构如 character_book 的 entries）
    material["_import_notes"] = {
        "format_version": version,
        "not_imported": NOT_IMPORTED,
        "note": "本文件为角色卡完整原始素材留存（全部字段）。正式档案 CHAR_{名}.md 由 LLM "
                "综合生成：description 拆分发（性格/整体形象/外貌/背景）、personality 提炼性格+生平、"
                "alternate_greetings→备用开场白、character_book→背景知识、八变量综合提炼（无依据留空）。"
                "system_prompt/post_history_instructions 与 WorldSim 引擎语义冲突，永不导入。",
    }
    return material


def process_one(world_dir: Path, png_path: Path, dry_run: bool) -> int:
    print(f"── 处理: {png_path}")
    if png_path.suffix.lower() == ".json":
        try:
            raw = json.loads(png_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ERR] JSON 解析失败: {e}", file=sys.stderr)
            return 1
    else:
        card_text = read_card_text(png_path)
        if card_text is None:
            print("[ERR] 未在 PNG tEXt chunk 中找到角色卡数据（keyword: chara/ccv3）", file=sys.stderr)
            return 1
        try:
            raw = json.loads(base64.b64decode(card_text.encode("latin1")))
        except Exception as e:
            print(f"[ERR] 角色卡 JSON 解码失败: {e}", file=sys.stderr)
            return 1

    card, version = normalize_card(raw)
    fallback = png_path.stem.strip() or "Unknown"
    name = sanitize_name(card.get("name"), fallback)
    material = build_material_json(card, version)
    import_dir = world_dir / "import"
    json_target = import_dir / f"{name}.card.json"

    target = world_dir / f"CHAR_{name}.md"
    if target.exists():
        print(f"[SKIP] 已有档案 CHAR_{name}.md——不覆盖（CHAR.md 生成后运行中不修改）。"
              f"如需重新综合生成，先删旧档案再导入", file=sys.stderr)
        return 1

    # ── 结构化摘要（供 LLM 综合生成 CHAR.md 使用） ──
    print(f"\n=== 角色卡提取: {name}（{version}）===")
    print(f"源: {png_path.name}")
    for key in card:
        if key in NOT_IMPORTED:
            continue
        print(f"  · {key:22s} → {brief(card[key])}")
    print(f"\n-- 综合提示 --")
    print(f"  description 混合性格/气质/经历/外貌 → 按模板拆分发；personality 提炼性格+生平；")
    print(f"  alternate_greetings → 情景与叙事·备用开场白；character_book → 背景知识条目；")
    print(f"  八变量/外貌/能力/叙事描写等可从原文综合提炼，无依据留空。")

    if dry_run:
        print(f"\n  [DRY-RUN] 未落盘。将留存素材: {json_target.relative_to(world_dir)}")
        print(f"  [DRY-RUN] CHAR_{name}.md 由 LLM 综合生成（脚本不生成）")
        return 0

    import_dir.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(material, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  [OK] 素材已留存: {json_target.relative_to(world_dir)}")
    print(f"  → 下一步: LLM 读素材全部原文，按 templates/CHAR_.md 结构综合生成 CHAR_{name}.md")
    return 0


def main():
    args = [a for a in sys.argv[1:]]
    dry_run = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if len(args) < 2:
        print(__doc__)
        sys.exit(2)
    world = args[0]
    paths = args[1:]
    world_dir = get_world_dir(world)
    bad = 0
    for p in paths:
        pp = Path(p)
        if not pp.is_file():
            print(f"[ERR] 文件不存在: {p}", file=sys.stderr)
            bad += 1
            continue
        bad += process_one(world_dir, pp, dry_run)
    if bad:
        sys.exit(1)
    print("提取完成。")


if __name__ == "__main__":
    main()
