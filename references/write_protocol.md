# WorldSim — 写入方式参考（write_protocol.md）

> **各阶段通用写入协议。** 命令不会用时来此查格式；不逐轮加载。

---

## 流程

1. **叙事已落盘完成后输出（⑥作家·write_narrative）——不再重复输出叙事**，其余字段静默写入。
2. **先过语义检查，再批量写入状态文件**：
   - 可选预检：`worldctl.py {世界名} audit`（stdin 传 change set 草案，只查不写）
   - 正式写入：`worldctl.py {世界名} write-raw --batch`——**内置 audit 语义检查**（硬性违规 → **单字段顶回**，其余字段照写，不整批拒绝；软性警告 → 不拦截，写入后由 validate 汇总）
   - 写入后**自动触发轻量校验**（quick_validate 摘要）——每轮必跑，无需手动调用
   - **非幂等（硬性）：** `write-raw --batch` 是副作用命令——`###APPEND:` 重复执行会**重复追加**累积字段（记忆锚点/场景时间线等）。**同一批次只执行一次**。执行后的确认只用只读手段（`read` / `validate` / 重跑 `--dry-run` 对比磁盘差异），**禁止重放 write 命令**做验证（轮次/时间等幂等字段会被 audit 顶回，但 APPEND 字段会静默重复追加）。
3. **收尾自查（每轮必做·write-raw 后）：** 按 references/phase_keeper.md「场记三问收尾自查」逐条核对——①痕迹完整：时间/轮次/前情→world_state · CT→conflicts · 出场/退场角色逐一→CHAR_state（退场=位置转焦外）· 道具线索→scene_state · 焦外→pending_actions · 新区域→world_map；②落点=焦点场景目录；③连续性=时间/轮次/存档一致。**validate 通过 ≠ 自查通过**（audit 只查格式违规，查不出「该写的角色没写」这类语义漏痕）。
4. **回退是低频例外·每轮零额外动作**——回退不走 write-raw（audit 拦截「轮次非单调」）；回退 = `snap.py load`（快照·主动存档）或手工重建（详见 references/rollback.md）。关键节点（场景切换/剧情转折）主动 `snap.py save` 一次，比任何自动机制都便宜。

**audit 语义不变量（对应闸门中可代码化的部分）：** 硬性（写入时单字段顶回）——① 行动卡四件套（`###ACTION:` 行 驱动/情绪/强度/代价 缺一拒绝，`代价:` 后为空拒绝·④角色批）；② 被争夺资源必须含 `当前载体=`/`当前持有者=`；④ `world_state.轮次` 单调递增；⑤ `scene_state` 落点必须有焦点场景目录——**落点校验在执行路径（write-raw 写入时）强制**；独立 audit 预检与 gate 仅软提示（场景目录由启动序列入场物化（初始场景）/⑤场记 init_scene（切换场景）创建·先于批次写入·见 session_recovery.md 第二章 / scene_management.md §场景切换流程）。软性（不拦截·validate 汇总）——③ 记忆锚点单条 ≤100 字、写入后总量 ≤3000。

stdout 回传无需任何处理，直接忽略。不向用户发送消息。**唯一例外：回显含 `?` 替身（如 `回显: ???`）= 内容已在管道中损坏——立即中止本批自查修正，禁止继续写入。** 静默模式（全局默认）下回复正文同样不输出（见 SKILL.md「输出模式」）——各阶段写入照常执行，落盘错误（[FAIL]/[ERR]）必须报告，不可静默。

---

## 阶段批次规范（每阶段直写各自文件）

> **每阶段产出自己的 write-raw --batch 批次**（Single Writer per State）——批次首行 `###STAGE: <阶段名>`（戏剧家/编剧/导演/角色/场记·声明后 audit 按该阶段必含项与写入矩阵检查·越权硬拦）；各阶段格式与示例见对应 phase_*.md；本文件承载通用格式与写入协议。
> **批次级元数据行（不产生写入 ops·不落盘）**：`###STAGE:` 阶段声明｜`###META:` 静默自查锚点｜`###STORYLINE:` 结构动作（add/rewrite 后跟事件线 YAML 块·②编剧·写 storylines）｜`###BEAT:` 演出指针动作（set/stay/advance·③导演·写 direction）｜`###ACTION:` 行动卡（四件套+耗时·④角色·audit ①①b 检查对象）｜`###SCHEDULE:` 调度单（受影响链留痕）。`###STORYLINE/###BEAT` 由 write-raw 自动执行对应子命令（失败=批次拦截 exit 1·LLM 不手动调用）。
> **KEY / APPEND 语义边界（硬性）：** `###KEY:` = **字段级全量替换**——结构化列表字段（记忆锚点/已知地点/信念演化/偏离登记）content 为合法 yaml 列表文本（`- item` / `[]`）时解析为列表写入，否则原始文本覆盖；`###APPEND:` = **结构化增量**（列表元素 `- item` / 串行元素 `· item`）。列表初值：APPEND（空字段=建列表）或 KEY 全量替换；列表全量重写：KEY 覆盖列表文本；列表清空：KEY 覆盖 `[]`（禁用 `''`——会留空串·被后续 APPEND 误解为旧锚点·生成脏 dict）。
> **白名单之外的结构化字段（硬性）：** 上述四个列表字段之外、值为 `- item` 列表的字段（`world_map.已探索区域` 及其子区域）**禁用 write-raw**——content 会被当原始文本覆盖，把列表写成字符串（类型损坏）→ 一律走 `write`（YAML diff 合并·见 §⑤/§结构化短字段）。
> 顺序 = 工作流顺序：决策先行（conflicts），世界收尾（world_state）。write-raw --batch 本身无执行顺序要求（代码按分组写盘），本顺序是规范层约定——让 LLM 按工作流组织输出，降低决策与执行脱节风险。

### ① conflicts.yaml（决策·完整推进轮 ≥1 条）

| 项 | 键路径 | 写语义 | 触发 |
|----|--------|--------|------|
| CT 推进 | CT-XX.{关系状态/内部状态/相位/被争夺资源/紧迫度} | KEY 覆盖 | 每轮至少一条（①戏剧家·D1 硬性） |
| 事件线引用 | CT-XX.事件线引用（如 [SL-01]） | KEY | 关联结构（②编剧建线后①下轮结算补挂·validate 对账·悬空告警） |
| CT 列表字段 | CT-XX.关联角色 / CT-XX.事件线引用 | KEY 覆盖·多行 YAML 列表（逐行 `- 名字` / `[SL-XX]`·全量含保留项+新增项）——单行文本/###APPEND 被 audit ⑮ 硬拦；名单与 characters/ 档案自动对账（无唯一匹配=软警告） | 补挂关联角色 / 建线后补挂引用 |
| CT 注册 | CT-XX（六字段全量） | KEY | 扫描发现/兜底/目击增殖 |
| 紧迫度冷却/升级 | CT-XX.紧迫度 | KEY 覆盖（🔴→🟡→🟢→休眠） | 本轮未推进降级；客观紧急直接🔴 |
| 删除（休眠2轮/解决） | CT-XX | DELETE | 生命周期到期 |
| Value Boundary 标记 | CT-XX.紧迫度=🔴 + 相位=🔄 | KEY 覆盖 | 行为动词命中 |

> 行动卡四件套（驱动/情绪/强度/代价·###ACTION 行）由 audit ①①b 硬性检查（④角色批）；`代价:` 字段是标准模式回复正文「本轮代价」行来源（静默模式该行不输出，字段仍硬性检查）。

### ② CHAR_{X}_state.yaml（决策落点·焦点角色必含核心状态/情绪）

| 项 | 键路径 | 写语义 | 触发 |
|----|--------|--------|------|
| 核心状态/情绪 | 核心状态 / 情绪 | KEY 覆盖（纯快照·隐藏主语=我） | 焦点角色每轮 |
| 记忆入锚 | 记忆锚点 | APPEND（yaml 列表元素·`轮次/时间/对象/内容`·写前同类融合·内容≤100） | 高刺激事件且角色会记住 |
| 已知地点登记 | 已知地点 | APPEND（yaml 列表元素·元素=地点名·只增不删·写前查重·循环重置按联动表回基线/保留） | 首次到达/被告知/目睹某地点（认知边界机械锚点·keys.md） |
| 连续行动轨迹 | 连续行动轨迹 | APPEND 追加本轮（④角色·七子字段·不裁剪·跨轮保留；**覆盖写须保留旧值首末轮次标记**·audit ⑬b 硬性拦截；增长控制=validate 告警+计划复盘压缩） | 角色本轮有行动 |
| 人际动态 | 人际动态 | KEY 覆盖全貌 | 关系变化/管道A |
| 信念演化 | 信念演化 | APPEND（yaml 列表元素·`轮次/时间/触发事件/旧→新`） | 变质判定留痕/管道B（均为信念演化写入时机·不涉及升级） |
| 位置/名字/决策/压力/防御 | 对应键 | KEY 覆盖 | 状态质变 |
| 自主性升级 | 自主性 | KEY 覆盖 + 同轮追加信念演化 + **同轮 `压力水平` 回落至世界当前水平（KEY 覆盖·戏剧家估定·非清零·默认非临界）·`防御有效性` 不动（保持崩解）** | 变质判定（仅循环角色·状态达标：压力临界+防御崩解·audit ⑧） |
| 防御重构 | 防御形态 / 崩溃表现 / 防御有效性 | KEY 覆盖（防御形态/崩溃表现：重构后的新防御·空=档案默认） | 重构事件（三条件齐备：威胁源解除+支持性关系介入+信念重构·①戏剧家判定+flag·④角色执行写入·见 references/phase_actor.md §落盘） |
| 锚点淘汰/融合 | 记忆锚点 | KEY 覆盖（有依据） | 同类≥2 / 超 3000 校验线 |

### ③ scene_state.yaml（场景痕迹·完整推进轮必含时间线追加）

| 项 | 键路径 | 写语义 | 触发 |
|----|--------|--------|------|
| 场景时间线追加 | 场景时间线 | APPEND（结构化元素：轮次/时间/事件·按 轮次+时间 查重） | 每轮必写 |
| 核心状态 | 核心状态 | KEY 覆盖 | 场景层面有变化 |
| 道具/线索变化 | 道具 / 关键场景信息 | KEY / APPEND | 叙事中移动/发现 |
| 场景冻结 | 全部字段锁存 + 时间线提炼 | KEY | 场景切换时 |

> **元素注册（硬性）：** `物理锚点`/`道具`/`关键场景信息` 的新增与变化是**⑤场记批产物**（###KEY: 物理锚点 / ###KEY: 道具 / ###KEY: 关键场景信息）——⑥作家只使用已注册元素；叙事推进后反填 = 违规；作家「请求场记补加」= 流程倒置 = 违规（作家发现未注册元素 = 退回重写）。**审计发现无来源元素时：先 `worldctl.py <世界> grep <元素名>` 查全仓注册数据——已存在则按注册原文修正（纠错，不是补新锚点），不存在才视为新元素需⑤场记注册；禁止补新锚点匹配叙事（=把幻觉固化进数据）。**

> 落点硬性：写入目标 = world_state.焦点场景 目录（audit ⑤）。

### ④ pending_actions.yaml（焦外事实层·触发式·有变化才写——焦外版 scene_state）

> 与 scene_state 互补（facts 焦内/焦外）：scene_state=焦内·pending_actions=焦外；conflicts=戏剧层（①·冲突张力视角）不与本文件互补。**焦外角色状态由④在轨写 CHAR_state（⑤禁写）·⑤仅据④结果/CHAR_state 记焦外事实。**「有变化才写」仅指⑤记**记录**的触发（有价值的客观焦外事实）；④对焦外 CHAR_state 的主观维护/自推演不在此限——角色持续在轨·非冻结（见 scene_management §焦外背景更新原则）。

| 项 | 键路径 | 写语义 | 触发 |
|----|--------|--------|------|
| 活跃中新增/滚动 | 活跃中.{PA-ID}.当前状态 | KEY 覆盖 | 焦外行动窗口推进/休眠CT焦外演化 |
| 已完成迁移 | 已完成.{PA-ID}（角色/时段/行动/结果/揭示场景） | KEY 覆盖 | 焦外行动被叙事揭示 |

> ⑤ foreshadow.yaml（伏笔登记·触发式·`###FILE: foreshadow` + `###APPEND: 伏笔`·种下/回收两个关键节点触发·规则全文 references/foreshadow.md·键表 keys.md）。

> **结构提醒（硬性）：** pending_actions 是 **dict-of-dicts**（`已完成.{PA-ID}.字段` / `活跃中.{PA-ID}.字段`），**不是 yaml 列表**——批量写入必须用**点路径逐层写**，禁止把整段 `- PA-ID: …` 列表当 KEY 覆盖（会破坏 dict 结构）。写法示例：

```
###FILE: pending_actions
###KEY: 已完成.PA-01.角色
Malèna
###KEY: 已完成.PA-01.时段
第1日 11:50-12:00
###KEY: 已完成.PA-01.行动
出门前看了一眼门口信箱
###KEY: 已完成.PA-01.结果
依旧空着·对 Nino 归来的确信磨损（CT-03 走表）
###KEY: 已完成.PA-01.揭示场景
S01
###KEY: 活跃中.PA-02.当前状态
泉边闲话滚动·「荡妇」标签酝酿+1
```

### ⑤ world_map.yaml（地图·触发式·可选层）

| 项 | 键路径 | 写语义 | 触发 |
|----|--------|--------|------|
| 新区域登记 | 已探索区域.{大区}.子区域… | write（YAML diff 合并） | 场景切换/位移到达未登记区域 |

### ⑥ world_state.yaml（世界收尾·最后——完整推进轮必含）

| 项 | 键路径 | 写语义 | 触发 |
|----|--------|--------|------|
| 具体时间推进 | 时间.具体时间 | KEY 覆盖（旧值+本轮时长·只增不减·跨天先切场景） | 每轮必写 |
| 轮次 +1 | 轮次 | KEY 覆盖 | 每轮必写（audit ④ 硬性：单调递增） |
| 前情描述 | 时间.前情描述 | KEY 覆盖（≤100字状态短语） | 每轮必写 |
| 倒计时登记/走表/移除 | 外部倒计时.{CD-ID} | KEY / DELETE | 事件确立·走表/到期·**每轮必查（周期倒计时每轮递减=有变化·无变化才跳过）** |
| 全局标记写/删 | 全局标记.{标记名} | KEY / DELETE | 事件可定论→写；进时间线→删 |
| 时间线新转折点 | scene_state.场景时间线 | APPEND（细粒度·每轮必写） | 命名/关系确立/威胁/重大事件 |
| 场景切换全套 | 焦点场景/基准时间/具体时间/地点 | KEY 覆盖 | 物理变化/跨天 |

### FILE key 注册表（###FILE: 取值）

| 文件 | 注册表 key | 兼容写法（自动归一化） |
|------|-----------|----------------------|
| states/conflicts.yaml | `conflicts` | — |
| states/ 各 CHAR_state | `CHAR_{全名}_state`（空格/下划线通用） | 缺 `_state` 后缀自动补 |
| 焦点场景 scene_state.yaml | `scene_state` | — |
| states/world_state.yaml | `world_state` | — |
| states/world_map.yaml | `world_map` | — |
| scenes/{焦点场景}/pending_actions.yaml | `pending_actions` | `scenes/{焦点场景}/pending_actions` / `scenes/{焦点场景}/pending_actions.yaml` |
| states/ 其他 *.yaml | 文件名 stem | 带路径/扩展名写法自动剥离 |

> 未知 FILE key 不再静默丢弃——正式写入报 `[ERR]` + 批量收尾 stdout `[FAIL]` 汇总 + exit 1；DRY-RUN 标 `[未知文件]` 并计入失败统计。注册表外 key 会被拒绝。
>
> **CHAR_* 全名容错：** `###FILE: CHAR_*` 写错全名（缺字/多字/简写）且与现有 `CHAR_*.md` 档案唯一包含匹配时，**自动映射到该角色 state 文件**（如 `CHAR_Maeve_state` → `CHAR_Maeve Millay_state`），dry-run 会标 `[映射]`。无需死记全名；若映射失败则被 `[ERR]` 拦截（不会新建错误文件）。

### 各阶段批次模板（完整示例见对应 phase_*.md）

每阶段批次首行 `###STAGE:`；场记批示例（其余阶段见 phase_dramatist/storyliner/director/actor.md）：

```
###STAGE: 场记
###META: 落点 焦点✓/时间✓/轮次✓/时间线✓ 轮完整✓
###FILE: scene_state
###APPEND: 场景时间线
- 轮次: 4
  时间: 09:30-09:40
  事件: T 藏钥匙·挡抽屉
###FILE: world_state
###KEY: 时间.具体时间
第1日 09:40
###KEY: 轮次
4
###KEY: 时间.前情描述
≤100字状态短语
```

> **`###META:` 行：** 静默自查锚点——批次内元数据行，解析器识别（不落盘、不产生写入 ops、不打断当前字段），用于各阶段自检留痕；audit/write-raw/gate 执行时**回显该行**，缺失时输出软性警告（查询轮/维护轮豁免）。格式自由，首行为 `###META: 标签 内容`。
>
> **`###STORYLINE:` / `###BEAT:` 行：** 结构/指针动作声明（write-raw 自动执行对应子命令）；`###STORYLINE: add/rewrite` 后跟事件线 YAML 块直到下一个 `###` 行。缺失时对应阶段 gate 硬性拦截（gate storyliner/director --check）。
>
> **`###ACTION:` / `###SCHEDULE:` 行：** ④角色批行动卡与调度单——audit ①①b（四件套/代价可核验）与角色档案存在性检查对象；不落盘（持久记录=CHAR_state.连续行动轨迹）。

查询轮（/status 等）整份豁免。

---

## 批量写入格式（heredoc），无执行顺序要求。

> **以下示例均为 bash 语法**——Windows/PowerShell 下禁止 `$var | python` 形式，一律走下方临时文件协议（UTF-8 临时文件 + `<` 重定向）。

### 临时文件协议（全局唯一权威·批次/叙事落临时文件时必读）

**默认：** 批次与叙事 stdin 直通（heredoc·`'EOF'` 免转义），不落临时文件。

**行尾硬性（所有平台·统一 LF·防值污染）：** 所有写盘（临时文件与持久文件）必须 LF 行尾——脚本写盘统一 `newline=""`（见 scripts/ 各脚本），LLM/手工写临时文件同样必须 LF。**Windows 下缺 LF = 写出 CRLF，worldctl 批次解析器只按 `\n` 切（`raw_stdin.split("\n")`），每行尾部残留 `\r` 污染值（实测：字段值带 `\r`，后续 YAML 解析/校验出错）。** 写临时文件时若用代码生成，须显式 `newline=""`；禁止依赖 os.linesep。

**编码硬性（所有平台·防文件损坏）：** 中文/多行内容**一律经 stdin 写入**（`write-raw --batch` heredoc·或 UTF-8 临时文件重定向）——**禁止把中文内容作为 CLI 参数传给 write-raw / write 单字段**（CLI 参数与 stdin 文本读取随 locale 解码·在非干净 UTF-8 环境会把文件写成非法字节·实测 `0x8c` 损坏致 world_state 拒绝写入）；**唯一编码安全通道 = `--batch`**（`sys.stdin.buffer.read().decode("utf-8")` 原始字节显式 UTF-8·单字段/`write` 均走 locale 解码·脆弱）。

**Windows 平台（PowerShell·UTF-8 中文经控制台 GBK 码页被破坏·写入内容变 `?`）：** 把批次/叙事写入 UTF-8 临时文件，再用 `cmd /c "python3 {skill_dir}/scripts/worldctl.py {世界名} write-raw --batch < 临时文件"`（write_narrative.py 同理）重定向喂 stdin——**`<` 文件重定向 = 字节透传（不经码页·编码安全）；禁止 PowerShell 管道**（`Get-Content <文件> \| python3 …` 会先经 `$OutputEncoding` 转码·5.1 缺省 ASCII·中文必损坏——中文数据一律走 `<` 重定向或 bash heredoc 管道）。

**可选保险（Windows·`PYTHONUTF8=1`）：** 运行脚本前设置 `set PYTHONUTF8=1`（PowerShell：`$env:PYTHONUTF8='1'`）——Python UTF-8 模式使 stdin/stdout 与文件默认编码全为 UTF-8（locale GBK 失效），即使个别地方漏写显式编码也不损坏。

- **落点：** 临时文件一律写 `worlds/{世界名}/tmp/`（世界内目录·无需额外权限）；禁止系统临时目录等 skill 外落点（写入需授权）
- **命名：** `cs_r{轮次}.txt`（批次）/ `narrative_r{轮次}.txt`（叙事）·用后即删
- **清理：** 世界级 tmp/ 由跨会话恢复时 `worldctl.py <世界> tmp-clean` 清理；单次用完即删
- **禁止：** skill 根目录 `tmp/` 不是临时文件落点（规范外目录·勿用）

### 现场临时脚本（LLM 即兴编写时·硬性）

执行中需要脚本处理/核对数据（清洗·转换·统计·比较）时——**优先使用世界文件通道/既有子命令；必须写脚本时按最小 I/O 头模板**：

```python
import sys
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
data = sys.stdin.buffer.read().decode("utf-8")   # 禁止 sys.stdin/input() 直接读
# 文件读写一律 open(path, encoding="utf-8")·写盘加 newline=""
```

- 中文数据禁止经 CLI 参数传递给该脚本（argv 跨 shell 透传编码语义不一）——数据走 stdin/文件
- 一行式 `python -c "…"` 处理中文同样适用：窄场景优先改走文件/manual 通道

**写入 narrative.md：**（持久化文件操作——叙事正文写入当前场景 narrative.md 并轮转归档；安装即授权，用户已被告知）

```bash
cat << 'EOF' | python3 {skill_dir}/scripts/write_narrative.py {世界名} {场景ID}
多行叙事内容……无任何字符需要转义
EOF
```

**写入状态文件（write-raw --batch，推荐）：**

```bash
cat << 'EOF' | python3 {skill_dir}/scripts/worldctl.py {世界名} write-raw --batch
###FILE: scene_state
###KEY: 核心状态
...
###FILE: CHAR_Maeve Millay_state
...
###FILE: world_state
...
###FILE: conflicts
...
EOF
```

> **Windows 平台（PowerShell）备注：** 详见上文「临时文件协议」小节（UTF-8 临时文件 + `cmd /c` 重定向喂 stdin）。
>
> **`--force`（显式回退专用·仅 `--batch`）：** 回退手工重建（无快照）时追加——`write-raw --batch --force` 绕过 audit ④ 轮次单调（轮次可回退）与 ⑬b 轨迹覆盖写（可覆盖裁剪）；其余硬性检查（行动卡四件套/载体/scene_state 落点/记忆留痕）照常拦截。非幂等同前（同一批次只执行一次·验证用 `--dry-run`/read/validate）；回退后必做残留扫描 + validate（见 references/rollback.md）。

`###FILE:` 开始一个文件分组，`###KEY:` 开始一个字段（支持点分隔路径），内容原样写入至下一个 `###FILE`/`###KEY` 或 EOF。**内容允许带 YAML 风格成对包裹引号（`'…'`/`"…"`），解析器自动剥除最外层一对**（时间线事件等多行字符串可放心加引号书写，不会触发「· 」检测误判）；引号本身作为值的一部分时用「」或不加包裹引号。

**嵌套映射键写法（重要·易错）：** 映射型字段（如 `world_state.时间线.{场景ID}` / `外部倒计时.{CD-ID}` / `重置记录.{角色}`）必须用**点路径逐层写**，禁止把整个 dict 当字符串覆盖：

```bash
###FILE: world_state
###KEY: 时间线.S09-Mariposa-清晨.时间     ← 正确：点路径逐层建映射
第3日 06:00
###KEY: 时间线.S09-Mariposa-清晨.事件     ← 正确：事件用「· 」连接粗粒度摘要
· 06:00 黎明重置落地
###KEY: 重置记录.Clementine Pennyfeather  ← 正确：重置登记（映射）
档位: 觉醒
轮次: 87
```

```bash
###KEY: 时间线.S09-Mariposa-清晨          ← 错误：整个映射被当字符串写入 → validate 报「值应为映射」
时间: 第3日 06:00
事件: ...
```

**内容行内嵌标记（硬性错误）：** `###FILE:`/`###KEY:`/`###APPEND:`/`###STORYLINE:`/`###BEAT:` 等全部批次标记必须独占行首。内容行内出现这些标记（不在行首）= 上一字段内容与标记拼接（如脚本替换缺换行）→ audit 报「内容行内嵌标记」，该字段拒绝写入。**用脚本修改批次后必须过 audit 再落盘。**

**修改/去重数据文件的准则（防误删·硬性）——一律走脚本，禁止直接编辑 YAML：**
- 记忆维护/去重（同类融合/淘汰/压缩/去重）→ **`###KEY: 记忆锚点` 覆盖为处理后完整 YAML 列表**（结构化列表覆盖·脚本解析为列表全量替换·见上文 KEY/APPEND 语义边界）——历史单引号折叠字符串字段经此覆盖自动归一为列表，消除解析隐患；新增条目 → `###APPEND: 记忆锚点`（写前同类融合·同 ID+内容 相同条目脚本自动 `[SKIP]` 防重）
- **单条锚点删除 = `###KEY:` 覆盖为剔除该条后的列表**（`###DELETE:` 只支持字典键删除·不支持列表元素删除——删单条锚点/信念演化/偏离登记元素一律用 KEY 覆盖）
- 锚点分组判定不变：按**完整 ID**（方括号内完整标签）分组；**ID+内容完全相同** → 重复事故副本，剔除；**同 ID 不同内容** → 合法多轮条目，保留（如需融合走「同类融合」·戏剧家决策）。**禁止 ID 前缀匹配**——`第3日/Maeve` 会误匹配 `[第3日/Maeve与Guest]`
- **坏文件（脚本拒绝写入）先按 phase_keeper.md 例外① 直接修引号，再回归脚本**；维护批次必须过 `--dry-run` 预演（只读比对磁盘差异）或 audit/validate 后再落盘

**累积字段写语义：** `场景时间线` / `信念演化` / `偏离登记` / `关键场景信息` 默认追加新条目——用 `###APPEND:` 追加到字段末尾（字段不存在时等同新建）。**`world_state.时间线.*.事件` 例外：仅场景 COMPLETE 时压缩写入（###KEY 覆盖·≤3 转折点·每条≤120字·事件内部禁止用「·」·详见 scene_management.md）——禁止每轮 APPEND。** `记忆锚点` **特殊：写前先同类融合（phase_actor.md「记忆锚点」写前五步），融合后追加新条目**。替换用 `###KEY:` 覆盖，需有依据（记忆修正/抹除/压缩/重置/时间线压缩维护）。**记什么/合并什么/遗忘什么的决策归戏剧家**——场记只机械执行 change set，不因字数自行删改。

**覆盖写与追加写可在同一批次混用（每轮场记推荐写法）：**

```bash
cat << 'EOF' | python3 {skill_dir}/scripts/worldctl.py {世界名} write-raw --batch
###FILE: world_state
###KEY: 时间.具体时间
第1日 14:55
###KEY: 轮次
46
###FILE: conflicts
###KEY: CT-07.相位
推进中 ⏩
###FILE: CHAR_Clementine Pennyfeather_state
###KEY: 核心状态
...（覆盖：当前快照）
###APPEND: 连续行动轨迹
- 轮次: N
  行动: 本轮动作序列（追加：④角色·七子字段）
###APPEND: 记忆锚点
- 轮次: N
  时间: 第X日 HH:MM
  对象: 记忆核心人物
  内容: 事实结果 ➔ 主观定性（≤100字·写前先同类融合）
###FILE: scene_state
###APPEND: 场景时间线
- 轮次: N
  时间: 14:45-14:55
  事件: 新事件……
###APPEND: 关键场景信息
· 本轮新线索条目……
EOF
```

**批量删除（write-raw --batch 内）：**

```
###DELETE: conflicts CT-05
###DELETE: pending_actions 已完成.PA-002
```

---

## 结构化短字段 → `write`

```bash
cat << 'YAMLEOF' | python3 {skill_dir}/scripts/worldctl.py {世界名} write
CHAR_Maeve Millay_state:
  位置: "工具棚内"
  压力水平: "中"
YAMLEOF
```

**限制：** 只适合不含 YAML 敏感字符（`：` `——` `"` `'` `{}` `[]` 等）的短字符串和数值。多行内容（如 `人际动态` 当前全貌）用 write-raw。

## 叙事式长文本 → `write-raw`

含以下任一特征 → 强制 `write-raw`：
- 全角冒号 `：`、全角破折号 `——`
- 英文引号 `"` `'`
- 多行/段落级内容
- YAML 语法字符：`{}[]&*?|!%`
- 值超 50 字符 → 推荐 `write-raw`
- 多个字段需 write-raw → 使用 `--batch`

**单字段（仅限短 ASCII 值·中文/多行走 `--batch` 或 heredoc·见「临时文件协议」编码硬性）：**
```bash
python3 {skill_dir}/scripts/worldctl.py {世界名} write-raw scene_state 关键场景信息 "SHERIFF"
```

**长文本 heredoc（中文/多行·编码安全）：**
```bash
cat << 'EOF' | python3 {skill_dir}/scripts/worldctl.py {世界名} write-raw scene_state 核心状态
多行内容……任何字符都不需要转义：——「」"'""{}[]
EOF
```

---

> 全部命令速查（worldctl.py 子命令 / shell 脚本 / 用户命令 / 执行频率分类）见 **references/commands.md**——本文件只承载写入协议，不重复命令表。
