# WorldSim — 命令速查（commands.md）

> **本文件 = 全部命令的唯一速查**（worldctl.py 子命令 / shell 脚本 / 用户命令）。命令不会用时来这里查，不需要逐轮执行。
> 行为指令在 SKILL.md（编排·每轮必读）+ references/phase_*.md（阶段规则·阶段开始前必读）；键表/写语义在 references/keys.md；写入批次格式在 references/write_protocol.md。
> **Windows 平台（PowerShell）备注：** 下方 heredoc 管道（`cat <<'EOF' \| python3 …`）为 Unix 写法——Windows PowerShell 下直接照搬，UTF-8 中文会经控制台 GBK 码页被破坏（写入内容变 `?`）。替代写法：把批次写入 UTF-8 临时文件，再用 `cmd /c "python3 {skill_dir}/scripts/worldctl.py <世界> … < 临时文件"` 重定向喂 stdin（落点/命名/清理见 references/write_protocol.md「临时文件协议」小节·全局唯一权威）。

---

## worldctl.py 子命令

| 子命令 | 用法 |
|--------|------|
| read（默认·核心集） | `python3 {skill_dir}/scripts/worldctl.py <世界> read` | 加载世界必读：world_state/conflicts/焦点场景 scene_state/焦内 CHAR_state（CHAR 按需补读） |
| read（指定文件） | `python3 {skill_dir}/scripts/worldctl.py <世界> read world_state conflicts` | 位置参数=文件 key 过滤（或 `--files a,b,c`） |
| read（全量） | `python3 {skill_dir}/scripts/worldctl.py <世界> read --all` | 调试用全量（23 文件） |
| write（增量合并） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write` |
| write（全量覆写） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write --full` |
| write-raw（单字段） | `python3 {skill_dir}/scripts/worldctl.py <世界> write-raw <文件key> <YAML键> "内容"` |
| write-raw（批量·推荐） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write-raw --batch` | **change set 写入通道**——内置 audit 语义检查（硬性违规单字段顶回·软性警告 validate 汇总）+ 写入后自动轻量校验 |
| write-raw（批量·预演） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write-raw --batch --dry-run` | 解析+audit+对比磁盘差异（新增/覆盖/无变化/顶回），**不落盘**——重跑批次/脚本改过 change set 后先跑这个 |
| append-raw（单字段追加） | `python3 {skill_dir}/scripts/worldctl.py <世界> append-raw <文件key> <YAML键> "内容"` |
| audit（预检） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> audit` | 只校验不落盘；通过 → `AUDIT OK`；硬性违规 → 列出全部 exit 1；仅软性警告 → 打印警告 exit 0 |
| validate | `python3 {skill_dir}/scripts/worldctl.py <世界> validate` | YAML 格式报错 + 内容级警告（load 后/跨 Session 恢复后必跑；含同物理地点场景元素继承检查） |
| init-states | `python3 {skill_dir}/scripts/worldctl.py <世界> init-states` | **启动世界动态文件物化（幂等·缺什么补什么·LF）**——conflicts←SEED / 模板三件 / CHAR_state 骨架（自主性解析自 CHAR_.md·外部者无该行）+ regions/ 自动对账；叙事约定为空时提示 LLM 填写（session_recovery.md 第二章 Step 0 唯一入口） |
| map-sync | `python3 {skill_dir}/scripts/worldctl.py <世界> map-sync` | world_map 镜像层对账（regions/ 目录树→补缺失节点·init-states 自动调用·validate 报缺失时也可单独跑） |
| grep | `python3 {skill_dir}/scripts/worldctl.py <世界> grep <关键词>` | 全仓（含所有场景 scene_state）搜索元素注册原文——**使用已有元素前核对形态/位置/状态/性质的标准工具（D11/W4 前置·防凭印象改写元素）**；无匹配=未注册=使用即幻觉 |
| delete | `python3 {skill_dir}/scripts/worldctl.py <世界> delete <文件key> <键路径>` | 删整条 CT / pending 条目；批量流支持 `###DELETE:` |
| beatsheet show | `python3 {skill_dir}/scripts/worldctl.py <世界> beatsheet show [N]` | 读节拍表（全部 / 指定事件线 N） |
| beatsheet add | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> beatsheet add`（stdin=单条事件线 YAML：事件线/当前拍/拍序） | **节拍表唯一写入入口**——建线=全新事件线（追加 `节拍表.{N}`·N 自动递增·脚本机械落盘+结构/枚举校验·LLM 不直接改 YAML·**顶点拍须含 `顶点落点`（缺则拒绝 exit 1）**） |
| beatsheet stay | `python3 {skill_dir}/scripts/worldctl.py <世界> beatsheet stay N` | 停留当前拍（本拍戏剧问题未被当前冲突兑现·随批写明本轮兑现进展·无进展=当前轮设计作废·退回重做） |
| beatsheet advance | `python3 {skill_dir}/scripts/worldctl.py <世界> beatsheet advance N 拍名` | 推进事件线 N 到指定拍（写 当前拍·校验拍名在拍序中·禁回退·顶点出线=advance N 余波 受 gate 收束核验（顶点落点+基准值+双方关键状态实质变化·形态可带可不带）；停留用 stay N） |
| beatsheet rewrite | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> beatsheet rewrite N`（stdin=新事件线 YAML） | 换线/重规划（现实与该线当前拍不承接·判线仍有继续价值时·顶点拍同步重填 `顶点落点`·缺则拒绝 exit 1） |
| beatsheet clear | `python3 {skill_dir}/scripts/worldctl.py <世界> beatsheet clear N` | 清线（当前拍=余波 或 现实与当前拍不承接时·清空该条保留字段名·CT 照常在 conflicts 演化·新冲突内核可清后建） |
| convert（.md→.yaml） | `python3 {skill_dir}/scripts/worldctl.py <世界> convert` | 旧 .md 状态文件转 .yaml |

> **批次自动执行（硬性）：** change set 中的 `###BEATSHEET:` 由 write-raw --batch 自动执行对应子命令落盘节拍表（`add`/`rewrite` 后直接跟事件线 YAML 块直到下一个 `###` 行·失败=批次拦截 exit 1）——**LLM 不手动调用 beatsheet 写命令**；下表命令保留用于查询（show）与维护。
> **每轮触发（硬性·完整推进轮·承接判定在④·推进判定在⑦收敛·行动结果后回判）：** 余波→`beatsheet clear N`（不用等余波事件完成·清后建）·空表/新线→`beatsheet add`（顶点拍预填 顶点落点·戏剧目标声明·用户角色为落点必须同时预填 ≥1 个 NPC 爆破项·缺则拒绝）·现实不承接→**默认 `beatsheet clear N` 清线**（低阻力出口·复用余波清线语义·新内核可清后建）·判线仍有继续价值→`beatsheet rewrite N` 重规划（当前拍按现实落位·顶点拍同步重填 顶点落点）·**承接不符时 advance 不参与判定**·承接成立后（⑦·按本轮行动结果回判）：本拍戏剧问题未兑现且本轮行动有兑现进展→`beatsheet stay N`（拍序保持原样·无进展=当前轮设计作废·退回重做）·问题已兑现→`beatsheet advance N 下一拍`（顶点=advance N 余波·受 gate 收束核验）。戏剧家在 change set 中以 `###BEATSHEET:` 声明（write-raw 自动执行）；查询轮/维护轮豁免。

## Shell 脚本

| 脚本 | 用法 |
|------|------|
| write_narrative.sh | `cat <<'EOF' \| sh {skill_dir}/scripts/write_narrative.sh <世界> <场景ID>`（场景ID支持短 ID S05 或完整目录名）——⚠ 写入磁盘：叙事正文落盘至焦点场景 narrative.md |
| snap.sh save | `sh {skill_dir}/scripts/snap.sh <世界> save [快照名]`（缺省名自动生成「场景ID-场景名-时间戳」）——⚠ 写入磁盘：复制当前状态至快照目录 |
| snap.sh load | `sh {skill_dir}/scripts/snap.sh <世界> load <快照名>` | 破坏性操作（覆盖当前状态·自动备份 _before_）——交互提示确认 / 非交互加 `--force` |
| snap.sh list | `sh {skill_dir}/scripts/snap.sh <世界> list` |
| snap.sh delete | `sh {skill_dir}/scripts/snap.sh <世界> delete <快照名>` | 破坏性操作（不可恢复）——交互提示确认 / 非交互加 `--force` |
| init_scene.sh | `sh {skill_dir}/scripts/init_scene.sh <世界> <场景ID> <场景名> [--from <旧场景ID>] [--type <类型>] [--time <时间>] [--cast <出场角色>]`（--from：继承旧场景 scene_state 的物理锚点/道具清单——**同物理地点切换必用**，防止漏继承；--type/--time/--cast 自动填充 scene_card 与 INDEX 行，缺省标「待填」） |
| reset_scene.sh | `sh {skill_dir}/scripts/reset_scene.sh <世界> [<场景ID>] [--force]` | **重置场景到 start_snapshot 状态**——清空场景内动态叙事（narrative 轮转归档 + scene_state 场景时间线/核心状态重置），静态基线（物理锚点/道具/关键场景信息）保留；场景ID 缺省=当前焦点场景；破坏性操作（重置前自动存档可回滚）——交互提示确认 / 非交互加 `--force` |
| reset-cycle | `python3 {skill_dir}/scripts/worldctl.py <世界> reset-cycle [--asset <角色名>]` | 循环世界重置一键命令——**周期重置（缺省）**：全员重置+登记重置记录+重建周期倒计时（write-raw ④b 顶回后调用·豁免判定含于其中·无需前置确认）；**事件触发重置（`--asset <角色名>`）**：叙事中角色被系统强制重置（回收/死亡修复/「校准」）时调用——只重置指定角色+登记事件触发重置记录+**不重建周期倒计时**（叙事事件不移动周期重置点）。两者都：脚本自动存档+联动表压缩/清空/回基线+行为轨道回归占位。**单角色豁免（2026-08-17 加入）：** 预先在 `world_state.重置记录.{角色}` 写 `触发: 豁免` + `重置日期: 第N日` → 该角色在登记的重置点被跳过（园区维护人员按指示跳过该资产·loop_machinery §4）——豁免一次性（按重置日期精确匹配·后续重置点照常重置·由后续重置登记自然覆盖）；豁免角色不登记周期记录（保留豁免标记·validate 8b 跳过）；audit ④b 覆盖判定排除豁免记录（豁免不算全员重置已执行·其他循环角色仍须重置）。调用后 LLM：保留候选微调 / 状态按 LOOPS 补写 / CT 节拍核查 / 重置叙事。幂等（当日已重置则重跑无害） |
| index.sh add | `sh {skill_dir}/scripts/index.sh <世界> add <ID> <名> [类型] [时间] [出场] [状态]`（动作在前 `index.sh add <世界> …` 同样支持） |
| index.sh activate | `sh {skill_dir}/scripts/index.sh <世界> activate <场景ID>`（动作在前同样支持） |
| index.sh update | `sh {skill_dir}/scripts/index.sh <世界> update <场景ID> [--type/--time/--cast/--status]`（动作在前 `index.sh update <世界> <场景ID> …` 同样支持） |
| index.sh remove | `sh {skill_dir}/scripts/index.sh <世界> remove <场景ID>`（动作在前同样支持） |
| list_worlds.sh | `sh {skill_dir}/scripts/list_worlds.sh` |
| create_world.sh | `sh {skill_dir}/scripts/create_world.sh <世界名>` | 创建新世界脚手架——⚠ 写入磁盘：在 `{WORLDS_ROOT}/{世界名}/` 创建目录与模板文件（SETTING/CONFLICTS_SEED·零 yaml）；动态文件由启动世界 init-states 物化（见 session_recovery.md 第二章） |
| import_card.py | `python {skill_dir}/scripts/import_card.py <世界名> <角色卡.png...>`（支持 .json 卡；`--dry-run` 预览不落盘） | ⚠ 写入磁盘：提取 SillyTavern 角色卡全部字段 → 留存 import/{名}.card.json；正式 CHAR_{名}.md 由 LLM 综合生成（详情见 references/import_cards.md·含隐私披露） |
| reset_world.sh | `sh {skill_dir}/scripts/reset_world.sh <世界名> [--force]` | 重置世界到创建完成态（纯 .md·零 yaml）——删 scenes/CHAR_state/全部动态 yaml·重置前自动存档可回滚·重置后走启动世界（首次启动态）；破坏性操作——交互提示确认 / 非交互加 `--force` |

## 用户命令（对话内）

| 命令 | 作用 |
|------|------|
| 「创建世界 <名>」 | 走 session_recovery.md 第一章（create_world.sh 脚手架 + 创作填充→校验→收尾提示启动世界） |
| 「重置世界」/「/reset」 | reset_world.sh——破坏性操作（自动存档可回滚）·重置后走启动世界（首次启动态） |
| 「重置场景」/「/reset-scene [场景ID]」 | reset_scene.sh——重置指定场景（缺省=当前焦点场景）到 start_snapshot 状态（自动存档可回滚） |
| 「启动世界」「继续世界」「恢复」等（会话首轮） | 启动世界统一序列（首次启动/跨 Session 恢复）——走 session_recovery.md 第二章：物化→入场物化→分层加载→validate→循环核对→描绘→停住·不推进 |
| `/scene <ID>` / `/scene new <名>` | 场景切换 / 新建场景 |
| `/conflicts` | 查看冲突 |
| `/status` / `/status --full` | 状态摘要 / 完整状态 |
| `/sync` / `/update` | 场记记录变化更新状态 |
| `/save [名]` / `/load <名>` | 存档管理 |
| `/silent` | 切回静默模式（全局默认·沉浸·只推叙事正文）——world_state 写 `输出模式: 静默` |
| `/loud` / 说「调试」「标准模式」 | 切到标准模式（完整回复正文 + D1-D15/W1-W4 闸口）——world_state 写 `输出模式: 标准` |
| 「审计」/「戏剧家审计」/「/audit」 | **用户觉察不对劲时使用**——三合一审计流程（LLM 按 gate 规格执行·机械项调用现成工具，不重写脚本）：① 机械核验=worldctl.py `validate` + `audit` + `gate`（现成）② 戏剧家审计=加载 references/gate_dramatist.md → D1-D15 逐项（使命三问/实质推进/抽象方/强度/字段质量/节拍表/顶点爆破/循环重置/循环轨道/用户抉择停靠）③ 作家审计=加载 references/gate_writer.md → W1-W4 逐项（POV 可见/身体显影/代价在纸上/锚点核对）④ 场记写入检查=时间/轮次单调/倒计时演化/反应轨迹同步/叙事落盘 ⑤ 知情边界核对=有 knowledge_index.yaml → 独立审计者视角逐条按 `记录` 指针读状态文件比对 + 清理（已公开/已落定/循环重置失效→删·不确定留）——细则见 references/knowledge_index.md ⑥ 伏笔闭环核对=有 foreshadow.yaml → validate 已机械检查（倒置/枚举/超时）+ 人工核对 `时间` 错位（如种下第3日·到第7日未回收）——细则见 references/foreshadow.md。输出=逐项 PASS/FAIL + 证据（文件路径+字段原文）；FAIL→按 gate 修复流程（≤2 轮），超限终止报告。**若审计反复发现同类违规（LLM 老是不按 skill 执行·补丁无效）→ 主动建议用户更换 LLM model——不无限打补丁·诚实承认模型能力/注意力上限** |

---

## 执行频率分类

- **每轮执行：** write_narrative.sh + worldctl.py（write-raw --batch——**change set 原样转交 + 内置 audit + 写入后自动校验**）
- **场景切换时：** init_scene.sh + worldctl.py 更新 world_state 顶层字段（**焦点场景** 唯一权威源·必须同步 INDEX ACTIVE 行）
- **存档管理：** snap.sh save / snap.sh load
- **跨 Session：** worldctl.py read
- **清理：** worldctl.py delete（CT 归档 / pending 条目移除）
