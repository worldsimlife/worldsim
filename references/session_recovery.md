# WorldSim — 世界生命周期（创建 / 首次启动 / 跨 Session 恢复）

> 世界生命周期三流程：**创建新世界**（脚手架+创作）→ **首次启动**（yaml 物化）→ **跨 Session 恢复**（加载→校验→描绘→停住）。不逐轮加载。

---

## 第一章 创建新世界

**触发：** 用户提出新世界概念（主题/核心设定），且 worlds/ 下无同名世界。SKILL.md 会话首轮硬规则「世界不存在 → 询问是否创建」在此展开。

**脚手架（create_world.sh）：** `sh scripts/create_world.sh <世界名>` —— 只生成 .md 静态骨架，**零 yaml**：
- `worlds/{世界名}/SETTING.md`（从 templates/ 复制）
- `worlds/{世界名}/CONFLICTS_SEED.md`（从 templates/ 复制）
- 创建角色时从 `templates/CHAR_.md` 复制改名 `CHAR_{名字}.md` 填写

**创作填充顺序：**
1. **SETTING.md** —— 世界名称/背景/地理/势力/规则/基调/核心高压法则/故事弧线（可选）
2. **CHAR_*.md** —— 每角色一个档案：六变量内核（Desire/Fear/Belief/Defense/Value Boundary/Reaction Style）+ 外在特征 + 表演叙事线
3. **CONFLICTS_SEED.md** —— 2-5 条冲突种子（每条核心高压法则至少覆盖一条；只写结构字段：描述/对抗双方/被争夺资源/紧迫度/关联角色；对抗双方禁抽象·抽象方须附显现机制）
4. **LOOPS.md / CROSS_NARRATIVES.md** —— 可选（循环世界必填 LOOPS：声明循环机制+各角色默认循环；隐藏交叉线可选）

**校验（收尾自查）：** SETTING.md 含核心高压法则；CHAR_*.md ≥1；CONFLICTS_SEED.md 可物化（对抗双方能画出对峙图、资源有载体/持有者）。

**收尾：** 提示用户「用『启动世界』进入首次启动」。

---

## 第二章 首次启动（全新 / 重置后）

**触发：** 世界刚创建 或 reset_world.sh 重置后，用户说「启动/继续/恢复世界」类词。
**与跨 Session 恢复的区别：** 动态 yaml 全部缺失（需物化）、无 scenes、无 CHAR_state、轮次 0。

**加载序列（按此顺序执行，不跳过不交换）：**

0. **动态文件物化**（缺失时从 templates/ 生成）：
   - `conflicts.yaml` ← 物化 `CONFLICTS_SEED.md`（复制+头注释）——只落结构字段（描述/对抗双方/被争夺资源/紧迫度/关联角色），`当前节拍` 与 `下一个节拍` 留空，由戏剧家首轮按首场景填充后正常演化。CONFLICTS_SEED.md 只读不改；conflicts.yaml 自此为唯一权威
   - `world_state.yaml` ← `templates/world_state.yaml`（初始态模板）
   - `world_map.yaml` ← `templates/world_map.yaml`（迷雾制·初始为空）
   - `off_focus/pending_actions.yaml` ← `templates/pending_actions.yaml`
   - 每个 `CHAR_*.md` 角色 → `CHAR_{name}_state.yaml` ← `templates/CHAR_state.yaml`（干净骨架·已存在跳过；骨架字段由戏剧家首轮 change set 填充；自主性初始值见 CHAR_.md「世界法则·循环注册」——Guest 等外部者角色删除该行）
1. 批量读取 SETTING.md + 所有 CHAR_*.md + CONFLICTS_SEED.md → 全局静态设定
2. 批量读取动态文件：所有 *.yaml → 世界、场景、角色等动态状态记录
3. 执行 scene_management.md §状态校验（validate + 内容核查 + 修复）

**描绘：** 无当前场景 → 按 POV 角色（Guest/玩家）档案的视角锚点沉浸描绘世界入口 → **停在起点·不推进剧情**。
首场景创建 / CHAR_state 初始化 / world_state 起点确立 → 由用户下一条输入后的首轮完整推进完成。

---

## 第三章 跨 Session 恢复

**触发：** 新会话/断线恢复后的第一条输入——如「继续世界」「恢复」「开始」；或世界已存在时用户要求进入该世界。判定失败时：优先按恢复处理（加载→校验→描绘→停住），不推进剧情；用户随后明确要求推进时再进入每轮流程。

**加载序列：**
1. 批量读取 SETTING.md + 所有 CHAR_*.md + CONFLICTS_SEED.md（如存在）→ 全局静态设定
2. 冲突种子物化（conflicts.yaml 缺失 且 CONFLICTS_SEED.md 存在时）——同第二章第 0 步
3. 批量读取动态文件：所有 *.yaml → 世界、场景、角色等动态状态记录
4. 执行 scene_management.md §状态校验（validate + 内容核查 + 修复）

加载后 → 以沉浸方式描绘前情提要和当前场景发给用户。不推进剧情。
