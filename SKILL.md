---
name: worldsim
description: 世界模拟器 · 故事引擎 · 实时戏剧 · 角色扮演。本地持久化世界状态（运行会在 worlds/ 下创建、修改和删除本地文件）、导入 SillyTavern 角色卡、推进互动剧情，以及执行存档、读档、回滚与状态修复。仅在用户明确要求运行世界模拟（创建/启动/继续/进入世界、导入角色卡），或明确要求在本 skill 创建的世界中开展角色扮演时激活；日常聊天提及、讨论或引用世界/角色/剧情话题不激活，与已有世界无关的泛化扮演/role-play 请求也不激活。
version: 0.21.0
metadata:
  openclaw:
    requires:
      bins: [python3]
      config: [worlds/]
    permissions:
      filesystem:
        - paths: ["worlds/"]
          access: [read, write, delete]
      scripts:
        - 维护脚本（校验/写入/快照/重置/删除/导入·scripts/）
    envVars:
      - name: WORLDSIM_WORLDS_DIR
        required: false
        description: Worlds data root directory (defaults to {skill_dir}/worlds). Set this to keep world data on your own storage, outside the skill install. The skill root itself is always derived from the script location and is not overridable.
---

# WorldSim — 世界模拟器 · 故事引擎 · 实时戏剧 · 角色扮演

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
- **数据忠诚（含锚点）**：行为在 conflicts 和 CHAR_state 有依据·物理元素在 scene_state 有来源；空间元素/道具/线索先注册才可在叙事中使用·使用前 `worldctl.py <世界> grep <元素名>` 核对注册原文·以原文为准；数据不足→加载或标记缺失·不编造（循环行为例外见各阶段规则）。
- **认知边界**：作者知道≠角色知道；只写 POV 角色能感知的内容（内部动机以 2-3 个连续可观察动作表达）；CHAR_state=角色主观状态文件（隐藏主语=我·禁全知）；角色不得拥有超出其经历/感知渠道的信息——循环世界由档位定义·非循环世界由档案经历定义。
- **写文件总约束**：一切文件落盘（状态 YAML / 场景文件 / 叙事 / 临时文件）遵循 references/write_protocol.md 三个不变量——① 状态写入经 `worldctl.py` 子命令（禁 edit/write 直改状态 YAML·坏文件修复除外）；② 统一 LF；③ 文本 I/O 显式 UTF-8（中文禁经 CLI 参数·Windows 可先 `set PYTHONUTF8=1`·PowerShell：`$env:PYTHONUTF8='1'`）。细则（元素注册/行尾/编码/破坏性确认）一律见 write_protocol.md（单一事实源·本文件不重复）。
- **语言跟随**：回复语言跟随用户；内部格式标签（###STAGE:/###META:/###FILE:/###KEY:/###APPEND:/###STORYLINE:/###BEAT:/###ACTION:/###SCHEDULE:）与状态文件字段为数据格式，保持相应语言与规范约束。

## 每轮流程

**输入类型判断**：查询命令（/status 等）→ 跳过决策直接输出；会话首轮 → disclosures.md「进入确认」→ 加载序列（session_recovery.md）→ 沉浸描绘停住；其他输入 → 本轮编排 → 六阶段推进。

**本轮编排**：先列一份本轮任务单——只列「本轮走哪些阶段 + 每阶段轻/重 + 触发原因」，动宾结构、一行一阶段。阶段分派单·只分派·不构思。示例（模式锚定·首轮完整推进形态）：

```
①戏剧家：重（CT 初始未结算）→ 结算各 CT 关系/内部状态+施压方向
②编剧：重（storylines 空表）→ 建线 SL-01+拍序+顶点约束
③导演：重（direction 无指针）→ beat set 起点+guidance+调度单
④角色：重 → 焦内 Angela/Guest 即兴;焦外在轨自推演
⑤场记：常规 → 落盘+round-check
⑥作家：常规 → 叙事
```

载体：任务清单（todo·harness 层·完成一阶段勾一项）；无 todo 环境则作内部一行清单（不输出）。

**六阶段推进**：（按todo追踪各阶段执行）每阶段按序执行——读该阶段 reference → 决策 → 写入（内嵌闸门核验）→ 通过 → 才进入下一阶段。

```
用户输入 → ①戏剧家 → ②编剧 → ③导演 → ④角色【行动决策→行动实现】 → ⑤场记 → ⑥作家 → 正文输出=回合终点（零正文轮）
```

| 阶段 | 先读 | 写入 | 轻量路径 | 全路径触发 |
|---|---|---|---|---|
| ①戏剧家 | references/phase_dramatist.md | conflicts | delta 扫描+走表+上轮结算 | 新🔴CT/VB/偏离/用户指令/兜底 |
| ②编剧 | references/phase_storyliner.md | storylines | 张力基调确认 | 空表/新内核/不承接 flag/线演完收束（含遗留线）/弧线节点 |
| ③导演 | references/phase_director.md | direction | 回判 checklist+guidance | 顶点/切场景/抉择悬崖/停滞 |
| ④角色 | references/phase_actor.md | **CHAR_state** | 焦内活跃角色即兴，焦内背景和焦外角色自推演 | 重大事件→受影响连锁重评 |
| ⑤场记 | references/phase_keeper.md | scenes+world_state | 常规落盘 | 顶点轮/跨场景轮/重置轮 |
| ⑥作家 | references/phase_writer.md | narration | 常规叙事 | 顶点轮/跨场景/对话轮/explicit |

各阶段按序逐步推进：读该阶段 reference → 决策 → 产出本阶段批次（首行 `###STAGE: <阶段名>`）→ `write-raw --batch` 落盘（段级闸门内嵌·落盘前拦截不合格批次·作家除外详见⑥）→ 通过才进下一阶段。阶段边界=既有产物+闸门；闸门失败撤回该阶段重做（≤2 轮·超限终止报告用户）。轻量合并仅限 write_protocol「运行时优化」可选通道（默认不用）。跨场景轮按 scene_management §场景切换「批次拆分」执行。Windows/PowerShell 环境批次文本经 `--file` 通道引用 UTF-8 临时文件（references/write_protocol.md「批次文本双通道」）。

**阶段完整性（硬性）：** 推进轮六阶段逐一走过·任何阶段不得缺席。「轻/重」只描述该阶段**写入量**——轻=沿既有态势最小维护（仍出本阶段批次与闸门·如张力基调确认行），重=结构性产出（表中「全路径触发」条件命中即重）。轻≠no-op≠跳过。数据就绪所需多文件读取一律一批并行发出（一条消息多个读取调用·禁逐个排队）。

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
└── scenes/SXX-场景名/{scene_card.md, start_snapshot.md, scene_state.yaml, pending_actions.yaml, narrative.md} ← ⑤场记
```

七文件一句话：CONFLICTS 什么正在发生冲突 / STORYLINES 故事将如何展开 / DIRECTION 故事现在演到哪里怎么继续 / CHARACTERS 人物现在想做什么 / SCENES 现场现在是什么样 / WORLD_STATE 世界实际上发生了什么 / NARRATION 这一切如何被写成小说。

## 引用（用时才读·不常驻上下文）

| 文件 | 何时读 |
|---|---|
| references/phase_*.md（dramatist/storyliner/director/actor/keeper/writer） | 本会话首次到达该阶段前必读该阶段文件；此后仅重路径命中（建线/close/clear/顶点出线/explicit/对话轮）或被该阶段 gate 连续拦截 2 次时重读 |
| references/gates.md | 标准模式人工审计 |
| references/disclosures.md | 会话首轮进入模拟 / 破坏性操作前 |
| references/keys.md | 写字段不确定时（键表/写语义） |
| references/write_protocol.md | 批次格式不确定时；首次启动轮必读全文 |
| references/scene_management.md | 场景切换/移动/存档/焦外协议 |
| references/beat_structure.md | ②编剧建线/弧线校准时 |
| references/loop_machinery.md | 循环世界（SETTING 声明循环且有循环角色）·每轮第一动作自检在场 |
| references/knowledge_index.md / references/foreshadow.md | 有对应文件时·知情/伏笔相关 |
| references/rollback.md | 回退/撤销时 |
| references/session_recovery.md | 创建/启动/恢复/跨 Session |
| references/commands.md | 命令不会用时 |
| references/import_cards.md | /import-card 时 |
| references/narrative_style_*.md | explicit 场景 / 对话轮（⑥作家） |
| `regions/**/REGION.md` | 到达新区域 / 创建场景时 |

## 命令参考

`/scene <ID>` · `/conflicts` · `/status [--full]` · `/sync` `/update` · `/save [名]` · `/load <名>`（**执行前确认**） · `/reset`（**执行前确认**） · `/reset-scene [ID]`（**执行前确认**） · `/import-card <卡>` · `/audit`（显式命令） · `/silent` `/loud`

**worldctl.py 子命令**（详情 references/commands.md）：read / write / write-raw --batch（段级闸门内嵌·场记批落盘后自动附跑 round-check）/ append-raw / delete / audit / validate / init-states / map-sync / grep / storyline（show/add/rewrite/close/clear·②编剧） / beat（show/set/stay/advance·③导演） / in-track（循环世界·只读查循环角色预设此刻在哪/做什么·③导演调度参考） / round-check（⑤轮完整性·亦随场记批自动附跑） / migrate（版本迁移·存量旧世界首次使用时提示执行） / gate dramatist|storyliner|director|actor|keeper|writer --check（单段复检与 writer 叙事核验） / reset-cycle [--asset] / lint / fix / tmp-clean / convert / scan

**破坏性操作确认（硬性）**：/load · /reset-scene · /reset · snap.py delete · ###DELETE: 执行前必须向用户显式确认（references/disclosures.md）；常规状态写入不在此列——安装即授权。
