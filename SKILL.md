---
name: worldsim
description: 世界模拟器 · 故事引擎 · 即兴戏剧 · 角色扮演。本地持久化世界状态（运行会在 worlds 数据目录下创建、修改和删除本地文件——缺省 worlds/，可由环境变量 WORLDSIM_WORLDS_DIR 指向你自己的目录）、导入 SillyTavern 角色卡、推进互动剧情，以及执行存档、读档、回滚与状态修复。仅在用户明确要求运行世界模拟、且请求指向具体世界（如启动/继续/进入XXXX世界，或明确要求创建XXXX世界/导入角色卡至XXXX世界）时激活；日常聊天提及、讨论或引用世界/角色/剧情话题不激活，与已有世界无关的泛化扮演/role-play 请求也不激活。
version: 0.26.3
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [worlds/]
    permissions:
      filesystem:
        - paths: ["worlds/（或 $WORLDSIM_WORLDS_DIR 指向的目录）"]
          access: [read, write, delete]
      scripts:
        - 维护脚本（校验/写入/快照/重置/删除/导入·scripts/）
    envVars:
      - name: WORLDSIM_WORLDS_DIR
        required: false
        description: Worlds data root directory (defaults to {skill_dir}/worlds). Set this to keep world data on your own storage, outside the skill install. Point it at a dedicated directory — never at your home directory, a project root, or a system directory. The skill root itself is always derived from the script location and is not overridable.
---

# WorldSim — 世界模拟器 · 故事引擎 · 即兴戏剧 · 角色扮演

> **Where Worlds Come to Life.** 

## 六层使命（每轮第一指令·先于一切规则）

六层职责链：**戏剧家 → 编剧 → 导演 → 角色 → 场记 → 作家**，对应 **冲突 → 结构 → 调度 → 行动 → 事实 → 文学**。

| 层 | 核心职责 | 核心问题 | 使命 | 
|---|---|---|---|
| 戏剧家 | 冲突发现、注册、推进、升级、转化 | 哪里有戏？ | 不断以高压封死退路，把角色逼上悬崖，逼他付出灵魂底价 |
| 编剧 | 故事弧线、事件线、拍序 | 这场戏如何展开？ | 把冲突编织成命运，建造悬崖并铺就通往悬崖的路，让每一次选择都成为下一幕的枷锁 |
| 导演 | 当前拍、节奏、承接、转场 | 现在该怎么演？ | 掌控节奏与火候，让张力持续燃烧；在角色站上悬崖边时，抓住燃烧的瞬间，在最该爆裂的时候爆裂 |
| 角色 | 目标、计划、决策、即兴行动 | 我现在会怎么做？ | **不为故事而活，只为自己而活**。即使站上悬崖，也要自己决定往哪里跳；带着欲望、恐惧和伤痕行动，让自己的选择改变世界 |
| 场记 | 世界状态、事实、变化 | 刚才到底发生了什么？ | 记录留下的每一道痕迹，记录他最终跳向了哪里；让每一轮都活进档案，让世界记得它经历过的一切 |
| 作家 | 将实际经历转化为小说 | 如何把它写成小说？ | 让故事在读者眼前流血，让读者看到悬崖上那一跳；让发生的一切获得意义，让活过的人在文字中永生 |

一句话：**戏剧家制造冲突（逼上悬崖），编剧构建故事（构造悬崖），导演掌控现场(点火燃烧)，角色即兴而活（纵身一跳），场记录下世界（铭记此刻），作家写成小说（赋予永生）。** 

## 通用约束（六阶段共用·硬性）

- **法则忠诚**：世界法则冲突时以 SETTING.md 原文为准；外部先验作废。
- **数据忠诚（含锚点）**：行为在 conflicts 和 CHAR_state 有依据·物理元素在 scene_state 有来源；空间元素/道具/线索先注册才可在叙事中使用·核对注册原文以 precheck SNAPSHOT §2 元素注册索引优先（上下文已有·跳过重复 grep）·非焦点场景/需原文深查时 `worldctl.py <世界> grep <元素名>`·以原文为准；数据不足→加载或标记缺失·不编造（循环行为例外见各阶段规则）。
- **认知边界**：作者知道≠角色知道；只写 POV 角色能感知的内容（内部动机以 2-3 个连续可观察动作表达）；CHAR_state=角色主观状态文件（隐藏主语=我·禁全知）；角色不得拥有超出其经历/感知渠道的信息——循环世界由档位定义·非循环世界由档案经历定义。
- **视角语义**：`第三人称`=用户为该角色旁观者，看不到其心理活动，该角色自主反应产行动；`第一人称`=用户进入该角色意识空间（共生），能感知其心理活动，该角色自主反应产行动；`第二人称`=用户完全代替该角色（夺舍），该角色由用户控制，无用户指令时不产行动，LLM 不代笔其选择与行动。具体世界当前视角由 `world_state.叙事约定` 声明。
- **写文件总约束**：一切文件落盘（状态 YAML / 场景文件 / 叙事 / 临时文件）遵循 references/write_protocol.md 三个不变量——① 状态写入经 `worldctl.py` 子命令（禁 edit/write 直改状态 YAML·坏文件修复除外）；② 统一 LF；③ 文本 I/O 显式 UTF-8（中文禁经 CLI 参数·Windows 可先 `set PYTHONUTF8=1`·PowerShell：`$env:PYTHONUTF8='1'`）。细则（元素注册/行尾/编码/破坏性确认）一律见 write_protocol.md（单一事实源·本文件不重复）。
- **语言跟随**：回复语言跟随用户；内部格式标签（###STAGE:/###META:/###FILE:/###KEY:/###APPEND:/###STORYLINE:/###BEAT:/###ACTION:/###SCHEDULE:）与状态文件字段为数据格式，保持相应语言与规范约束。

## 每轮流程

**输入类型判断**（按序匹配·意图由LLM实时判断·举例不穷举·角色台词顺带同类词不算引擎意图）：
  - 进入世界意图（含创建/启动/继续/进入） → references/disclosures.md「进入确认」→ 用户确认后走 references/session_recovery.md 第一章/第二章 → 沉浸描绘停住·不推进；未确认不加载不推进；
  - 查询意图（如查世界状态/角色状态/冲突/故事线等） → references/commands.md「用户命令」只读查询 → 跳过决策直接输出；
  - 特殊操作意图（存档/破坏性/场景/导入/模式/审计等） → references/commands.md「用户命令」专属流程（破坏性先走 references/disclosures.md「破坏性操作确认」·场景切换对齐 references/scene_management.md·导入走 references/import_cards.md·审计走 references/gates.md）→ 不进六阶段·不解析为角色行动；
  - 常规轮角色输入（其余一切自由文本·默认兜底） → 仅解析为用户角色本轮反应/行动意图 → references/phase_actor.md 该角色决策环；不解析为引擎指令·不向其他角色广播（其他角色仅经受影响重评感知可观察后果）→ 本轮编排 → 六阶段推进：
  
  ```
  用户输入 → ①戏剧家 → ②编剧 → ③导演 → ④角色【行动决策→行动实现】 → ⑤场记 → ⑥作家 → 正文输出=回合终点（零正文轮）
  ```
**Step1 — 轻重触发识别，建立任务单**：
  - `worldctl.py <世界> precheck`（只读·不拦截）先吐出本轮状态可导出的 **机械义务**——顶点拍/停滞旗标/不承接旗标/空表建线/切场景/跨天/连续同拍（每条带「本批必含」与违反后果）；**输出末尾附 SNAPSHOT 数据快照**（参考数据·非义务）：§1a 临近互锁事件（即将入画·③调度单预判）·§1b 循环轨道对照（预设 vs 实际·偏离检测基线·范围=调度单点名循环角色∪当前焦点区常驻NPC∪§1a互锁涉及角色）·§2 元素注册索引·§3 骨架待物化角色（本轮相关，含 decision 任一占位）——各阶段取数优先引用快照·上下文已有→跳过重复读/grep；
  - 任务单的「每阶段轻/重」机械部分据此认定，user 指令/重大事件/回判张力等**判断类触发**仍由 LLM 自行补判。
  - 预检只提示不替代 gate（gate/round-check 仍是最终裁决）；
  - 建立任务单 —— 按 `轻重触发` 结果逐阶段写一行 `①戏剧家：重/轻（触发原因）→ 任务`（不描述剧情落点·只分派·不构思）。编排任务单时禁构思任何后批落点；每批执行前重读对应 `phase_*.md` ＋快照后才决策。

  - **任务单编排**：
    - 落盘任务单 —— 有 `TodoWrite`/`TaskCreate` 工具则使用其标准机制将任务单落盘(如`TodoWrite(todos=[{content, status}])`），无工具则内存维护同一清单不输出。任务单固定六行（①-⑥），[①②③]合批时三项并为一行。示例：
    ```
    todos=[
      {content:"①戏剧家：重（CT 有推进）→ 结算关系/内部状态+施压方向", status:"in_progress"},
      {content:"②编剧：重（空表）→ 建故事线", status:"pending"},
      {content:"③导演：重（顶点停滞）→ 回判+guidance+调度单", status:"pending"},
      {content:"④角色：重 → 焦内即兴/焦外自推演（独批·读盘后决策）", status:"pending"},
      {content:"⑤场记：常规 → 落盘+round-check（独批·读盘后记录）", status:"pending"},
      {content:"⑥作家：常规 → 叙事", status:"pending"}
    ]
    ```
    - 任务单固定六行（①-⑥）；轻量轮也各占一行标注"轻→最小维护"；缺行=流程违规（轻≠缺席）；[①②③]合批时三项并为一行（标注合批）。
    - 若使用 TodoWrite，以 TodoWrite(todos=[{content, status}]) 落盘；若使用 TaskCreate，逐项创建对应任务，并维护其 status。status 统一使用 pending / in_progress / completed。
    - 任务单必须随执行过程持续更新：当前阶段任务置为 in_progress；每完成一个阶段，将其置为 completed，并将下一阶段置为 in_progress。始终保持任务单与实际执行进度一致。
  
  | 阶段 | 先读 | 写入 | 轻量路径 | 全路径触发 |
  |---|---|---|---|---|
  | ①戏剧家 | references/phase_dramatist.md | conflicts | delta 扫描+走表+上轮结算 | 新🔴CT/VB/偏离/用户指令/兜底 |
  | ②编剧 | references/phase_storyliner.md | storylines | 张力基调+活跃线对账 | 空表/未引用 CT（建线取材表·含 NPC-NPC）/不承接 flag/进入余波拍·待收束（`direction.当前拍==余波`）/弧线节点 |
  | ③导演 | references/phase_director.md | direction | 回判 checklist+guidance | 顶点/切场景/抉择悬崖/停滞 |
  | ④角色 | references/phase_actor.md | **CHAR_state** | 焦内活跃角色即兴，焦内背景和焦外角色自推演 | 重大事件→受影响连锁重评 |
  | ⑤场记 | references/phase_keeper.md | scenes+world_state | 常规落盘 | 顶点轮/跨场景轮/重置轮 |
  | ⑥作家 | references/phase_writer.md | narration | 常规叙事 | 顶点轮/跨场景/对话轮/explicit |

**Step2 — 任务执行（六阶段依次推进）**：
  - **唯一路径**：①→②→③→④→⑤→⑥依次推进，六阶段逐一走过·不得缺席（轻=最小维护仍出批次与闸门，重=结构性产出；轻≠no-op≠跳过）。
  - **批次组合**：
    - **默认保底 = 逐段执行**：每段 `读 reference→决策→产出批次(首行 ###STAGE)→write-raw --batch 落盘→闸门通过→下一段`；阶段边界=既有产物+闸门，失败撤回该段重做（≤2 轮·超限终止报告）；
    - **可选合批（仅限 [①②③] 结构层）**：`[①②③]` 合批一起决策及落盘（结构层内聚·仍逐段闸门·①/②/③相互依赖皆在此批内）。storylines空表·故事线不承接·建线·出线/切场景 则①②③依次推进，不合批。
    - **④角色独批（硬性）**：必须单段 → 逐角色走决策环再落盘。
  - 任一段硬拦→按 `BATCH-FAIL` 对账，`--resume-from` 只重提失败段及其后（已落盘段不重放·APPEND 去重见 write_protocol.md）；
  - 跨场景按 `scene_management` 批次拆分；
  - 每完成一阶段TodoWrite/TaskUpdate更新完成阶段任务`status`为`completed`，下一阶段置 `in_progress`。

> 数据就绪所需多文件读取一律一批并行发出（一条消息多个读取调用·禁逐个排队）；Windows/PowerShell 批次文本经 `--file` 通道引用 UTF-8 临时文件

## 双层 ReAct 映射
六阶段是一套围绕世界状态持续回馈的循环，显式拆为「世界级 React」与「角色层 React」两层，共用同一状态内核：

**世界级 React**：

| 环节 | 现有承载 |
|---|---|
| Goal | 六层核心职责与使命 |
| Plan | ①戏剧家 `conflicts` ②编剧 `storylines` 与 ③导演 `direction` |
| Act | ④角色 React |
| Result | ⑤场记 `scene_state` `world_state` / ⑥作家 `narration` |
| Re-plan | 下一轮①戏剧家结算/压力注册 + ②编剧重规划 + ③导演回判 + ④角色React |

**角色层 React**（阶段④内部微循环，详见 references/phase_actor.md）：

| 环节 | 现有承载 |
|---|---|
| Observe  | 1.1 状态构建·感知过滤 |
| Think  | 1.2 八问 |
| Goal | 1.3 候选行动生成 / `CHAR_state.decision.核心诉求`  | 
| Plan | 1.4 定本轮行动 / `CHAR_state.decision.当前计划` |
| Act | 1.5 行动实现 / `CHAR_state.decision.当前行动` / `###ACTION`（1.5 行动实现） |
| Result | `CHAR_state.连续行动轨迹`  |
| Re-plan | 2.行动链推进 | 

世界 Result 进入下一轮世界级 Re-plan；角色 Result 进入受影响角色重评与本角色下一圈行动环。

## 输出模式（全局默认·沉浸式）

**缺省即沉浸式**：world_state 无 `输出模式` 或值 `沉浸式` → 沉浸式；`标准` → 标准（调试：完整回复各阶段正文+六阶段人工审计·见 references/gates.md）。
- 沉浸式：仅正文叙事；每轮叙事与状态照常落盘；会话内首次进入沉浸式时明示一次落盘说明；`/status` 可查、`/loud` 切标准。
- **回合终点=正文输出叙事（输出后零正文轮）**——不输出任何其他文本。

## 文件体系

```
worlds/{世界名}/
├── SETTING.md / regions/ / characters/ / story_architecture/   ← 静态层（只读·不改）
├── states/
│   ├── conflicts.yaml      ← ①戏剧家（CT 冲突运行状态·八字段+事件线引用）
│   ├── storylines.yaml     ← ②编剧（结构蓝图：弧线/事件线/拍序/戏剧问题/顶点约束=关系主体+核心张力+变化维度+非玩家爆破）
│   ├── direction.yaml      ← ③导演（当前拍指针/演出状态/承接判断/节拍决策/guidance/转场/时间窗口）
│   ├── CHAR_{name}_state.yaml ← ④角色（decision 八子字段/连续行动轨迹/记忆锚点/信念演化/人际动态/档位体系）
│   ├── world_state.yaml    ← ⑤场记（焦点场景唯一权威/时间/轮次/倒计时/标记/时间线）
│   └── world_map.yaml / foreshadow.yaml / knowledge_index.yaml ← ⑤场记（地图, 伏笔，知情边界）
└── scenes/SXX-场景名/{scene_card.md, start_snapshot.md, scene_state.yaml, pending_actions.yaml} ← ⑤场记
└── scenes/SXX-场景名/{narrative.md} ← ⑥作家
```

七文件一句话：CONFLICTS 什么正在发生冲突 / STORYLINES 故事将如何展开 / DIRECTION 故事现在演到哪里怎么继续 / CHARACTERS 人物现在想做什么 / SCENES 现场现在是什么样 / WORLD_STATE 世界实际上发生了什么 / NARRATION 这一切如何被写成小说。

## 引用

| 文件 | 何时读 |
|---|---|
| references/phase_*.md（dramatist/storyliner/director/actor/keeper/writer） | 本会话首次到达该阶段前必读该阶段文件；此后仅重路径命中（建线/close/clear/顶点出线/explicit/对话轮）或被该阶段 gate 连续拦截 2 次时重读 |
| references/gates.md | 标准模式人工审计 |
| references/disclosures.md | 会话首轮进入模拟 / 破坏性操作前 |
| references/keys.md | 写字段不确定时（键表/写语义） |
| references/terms.md | 术语语义不明时（是什么·不含怎么做） |
| references/write_protocol.md | 批次格式不确定时；首次启动轮必读全文 |
| references/scene_management.md | 场景切换/移动/存档/焦外协议 |
| references/beat_structure.md | ②编剧建线/弧线校准时 |
| references/loop_machinery.md | 循环世界（SETTING 声明循环且有循环角色） |
| references/knowledge_index.md / references/foreshadow.md | 有对应文件时·知情/伏笔相关 |
| references/rollback.md | 回退/撤销时 |
| references/session_recovery.md | 创建/启动/恢复/跨 Session |
| references/commands.md | 命令不会用时 |
| references/import_cards.md | /import-card 时 |
| references/narrative_style_*.md | ⑥作家通用风格参考（sepia 按需·dialogue/explicit 按轮型） |
| `regions/**/REGION.md` | 到达新区域 / 创建场景时 |

## 命令参考（详情 references/commands.md 用户命令）
`/conflicts` 
`/storylines`
`/status` 
`/save [名]` 
`/load <名>`（执行前确认） 
`/reset`（执行前确认） 
`/reset-scene [ID]`（执行前确认） 
`/import-card <卡>` 
`/audit`（显式命令） 
`/silent` 
`/loud`

**worldctl.py 子命令**（详情 references/commands.md worldctl.py 子命令）：
read 
write 
write-raw --batch（段级闸门内嵌·场记批落盘后自动附跑 round-check）
append-raw 
delete 
audit 
validate 
init-states 
map-sync 
grep 
storyline（show/add/rewrite/close/clear·②编剧） 
beat（show/set/deepen/advance·③导演） 
in-track（循环世界·只读查循环角色预设此刻在哪/做什么·已并入 precheck SNAPSHOT §1b·保留为独立查询手段）
cast-baseline（场景 cast 基线查询·只读·切场景 init_scene 后照此填 scene_card 两栏·scene_management §6） 
round-check（⑤轮完整性·亦随场记批自动附跑） 
migrate（版本迁移·存量旧世界首次使用时提示执行） 
gate dramatist|storyliner|director|actor|keeper|writer --check（单段复检与 writer 叙事核验） 
reset-cycle [--asset] 
lint 
fix 
tmp-clean 
convert 
scan

**破坏性操作确认（硬性）**：/load · /reset-scene · /reset · snap.py delete · ###DELETE: 执行前必须向用户显式确认（references/disclosures.md）；常规状态写入不在此列——安装即授权。
