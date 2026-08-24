# WorldSim — 命令速查（commands.md）

> **本文件 = 全部命令的唯一速查**（worldctl.py 子命令 / shell 脚本 / 用户命令）。命令不会用时来这里查，不需要逐轮执行。
> 行为指令在 SKILL.md（编排·每轮必读）+ references/phase_*.md（阶段规则·阶段开始前必读）；键表/写语义在 references/keys.md；写入批次格式在 references/write_protocol.md。
> **Windows 平台（PowerShell）备注：** 下方 heredoc 管道（`cat <<'EOF' \| python3 …`）为 Unix 写法——Windows PowerShell 下直接照搬，UTF-8 中文会经控制台 GBK 码页被破坏（写入内容变 `?`）。替代写法：把批次写入 UTF-8 临时文件，再用 `cmd /c "python3 {skill_dir}/scripts/worldctl.py <世界> … < 临时文件"` 重定向喂 stdin（落点/命名/清理见 references/write_protocol.md「临时文件协议」小节·全局唯一权威）。**worldctl.py 全部 stdin 读取路径（write/write-raw --batch/storyline/单字段回退）均已统一为 `sys.stdin.buffer` 显式 UTF-8 解码——上述 cmd /c 重定向写法对所有子命令成立。**

---

## worldctl.py 子命令

| 子命令 | 用法 |
|--------|------|
| read（默认·核心集） | `python3 {skill_dir}/scripts/worldctl.py <世界> read` | 加载世界必读：world_state/conflicts/焦点场景 scene_state/焦内 CHAR_state（CHAR 按需补读） |
| read（指定文件） | `python3 {skill_dir}/scripts/worldctl.py <世界> read world_state conflicts` | 位置参数=文件 key 过滤（或 `--files a,b,c`） |
| read（全量） | `python3 {skill_dir}/scripts/worldctl.py <世界> read --all` | 调试用全量（23 文件） |
| write（增量合并） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write` |
| write（全量覆写） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write --full` |
| write-raw（单字段） | `python3 {skill_dir}/scripts/worldctl.py <世界> write-raw <文件key> <YAML键> "内容"` | 仅限短 ASCII 值；**中文/多行内容一律用 `--batch`**（stdin 直通·唯一编码安全通道·CLI 参数传中文随 locale 解码会损坏文件） |
| write-raw（批量·推荐） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write-raw --batch` | **change set 写入通道**——内置 audit 语义检查（硬性违规单字段顶回·软性警告 validate 汇总）+ 写入后自动轻量校验 |
| write-raw（批量·预演） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write-raw --batch --dry-run` | 解析+audit+对比磁盘差异（新增/覆盖/无变化/顶回），**不落盘**——重跑批次/脚本改过 change set 后先跑这个 |
| write-raw（批量·回退） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> write-raw --batch --force` | **显式回退专用**——绕过 audit ④ 轮次单调/⑬b 轨迹覆盖写（无快照手工重建时用·见 rollback.md）；其余硬性检查照常·非幂等同前·回退后必做残留扫描+validate |
| append-raw（单字段追加） | `python3 {skill_dir}/scripts/worldctl.py <世界> append-raw <文件key> <YAML键> "内容"` |
| audit（预检） | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> audit` | 只校验不落盘；通过 → `AUDIT OK`；硬性违规 → 列出全部 exit 1；仅软性警告 → 打印警告 exit 0 |
| validate | `python3 {skill_dir}/scripts/worldctl.py <世界> validate` | YAML 格式报错 + 内容级警告（load 后/跨 Session 恢复后必跑；含同物理地点场景元素继承检查） |
| init-states | `python3 {skill_dir}/scripts/worldctl.py <世界> init-states` | **启动世界动态文件物化（幂等·缺什么补什么·LF）**——conflicts←SEED / 模板三件 / CHAR_state 骨架（自主性解析自 CHAR_.md·外部者无该行）+ regions/ 自动对账；叙事约定为空时提示 LLM 填写（session_recovery.md 第二章 Step 0 唯一入口） |
| map-sync | `python3 {skill_dir}/scripts/worldctl.py <世界> map-sync` | world_map 镜像层对账（regions/ 目录树→补缺失节点·init-states 自动调用·validate 报缺失时也可单独跑） |
| grep | `python3 {skill_dir}/scripts/worldctl.py <世界> grep <关键词>` | 全仓（含所有场景 scene_state）搜索元素注册原文——**使用已有元素前核对形态/位置/状态/性质的标准工具（D11/W4 前置·防凭印象改写元素）**；无匹配=未注册=使用即幻觉 |
| delete | `python3 {skill_dir}/scripts/worldctl.py <世界> delete <文件key> <键路径>` | 删整条 CT / pending 条目；批量流支持 `###DELETE:` |
| storyline show | `python3 {skill_dir}/scripts/worldctl.py <世界> storyline show [SL-XX]` | 读事件线（全部 / 指定·states/storylines.yaml） |
| storyline add | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> storyline add`（stdin=单条事件线 YAML：名称/类型/状态/拍序） | **storylines 唯一写入入口·②编剧**——建线（id 自动递增 SL-XX·脚本机械落盘+结构/枚举校验·LLM 不直接改 YAML·**顶点拍须含 `顶点约束`（关系主体≥2/核心张力/变化维度/非玩家爆破≥1·缺则拒绝 exit 1）**）；建线后起点指针由③导演 `beat set` 落 direction |
| storyline rewrite | `cat <<'EOF' \| python3 {skill_dir}/scripts/worldctl.py <世界> storyline rewrite SL-XX`（stdin=新事件线 YAML） | 换线/重规划（现实不承接·判线仍有继续价值时·顶点拍同步重填·缺则拒绝） |
| storyline close | `python3 {skill_dir}/scripts/worldctl.py <世界> storyline close SL-XX`（批次中 `###STORYLINE: close SL-XX` 后跟一行 `收束摘要:`） | **收束（线已演完·当前拍=余波）**——保留 名称/类型＋状态=已收束＋收束摘要·清拍序·direction 指针复位；非余波/缺摘要 exit 1。当轮须 add 后继线并由③导演 set 新起点（否则 round-check FAIL） |
| storyline clear | `python3 {skill_dir}/scripts/worldctl.py <世界> storyline clear SL-XX` | 废弃（不承接且无继续价值）——整条抹为空锚点·direction 指针自动复位；当前拍=余波时 WARN 提示应走 close 收束留档 |
| beat show | `python3 {skill_dir}/scripts/worldctl.py <世界> beat show` | 读 direction（当前事件线/当前拍/演出状态/guidance） |
| beat set | `python3 {skill_dir}/scripts/worldctl.py <世界> beat set SL-XX 拍名` | 初始指针（建线后③导演设定起点拍·进入顶点时自动记录基准快照） |
| beat stay | `python3 {skill_dir}/scripts/worldctl.py <世界> beat stay SL-XX` | 停留当前拍（③导演回判确认·无写入） |
| beat advance | `python3 {skill_dir}/scripts/worldctl.py <世界> beat advance SL-XX 拍名` | 推进指针（校验拍名在拍序中·**禁回退**·顶点出线=advance SL-XX 余波 受 gate director 收束核验；停留用 stay） |
| in-track | `python3 {skill_dir}/scripts/worldctl.py <世界> in-track` | 只读查询——按各 CHAR_.md「默认循环时间线」表+world_state 当前时间，输出此刻各循环角色应在哪/做什么（③导演调度单输入之一·循环世界用；无时间线角色报「无可用时间线」·不改任何状态） |
| round-check | `python3 {skill_dir}/scripts/worldctl.py <世界> round-check` | **⑤场记轮完整性收尾**——direction/世界三件套/场景时间线/区域一致性（POV 位置节点 vs 焦点场景区域节点·空间已变未切即 FAIL）/引用对账逐项核对·FAIL exit 1 |
| migrate | `python3 {skill_dir}/scripts/worldctl.py <世界> migrate` | **存量旧世界数据迁移**（节拍表→storylines·CT.当前节拍→direction·旧字段清除+LLM 辅助报告·自动存档可回滚·幂等）——存量旧世界首次使用时提示执行 |
| convert（.md→.yaml） | `python3 {skill_dir}/scripts/worldctl.py <世界> convert` | 旧 .md 状态文件转 .yaml |
| gate | `python3 {skill_dir}/scripts/worldctl.py <世界> gate dramatist\|storyliner\|director\|actor\|keeper\|writer [--check]` | 阶段出口闸门——无 `--check` 打印该阶段人工审计清单（gates.md 同源）；有 `--check` 读 stdin 批次（writer=叙事正文）做可代码化硬性核验，不合格 exit 1 |
| lint | `python3 {skill_dir}/scripts/worldctl.py <世界> lint` | 全部状态文件 YAML 格式/引用问题只读检查（不落盘） |
| fix | `python3 {skill_dir}/scripts/worldctl.py <世界> fix` | 规范化重写全部 YAML 状态文件（snap 自动备份 + validate） |
| scan | `python3 {skill_dir}/scripts/worldctl.py <世界> scan <关键词> [--live]` | 全仓关键词扫描（worlds/<世界>/ 下 .md/.yaml·排除 narrative 轮转与 archive；`--live` 只扫现行文件）——残留扫描/修复验证用；退出码：0=无匹配（已清除）1=有匹配 2=用法错误 |

> **批次自动执行（硬性）：** 批次中的 `###STORYLINE:`（②编剧·结构）与 `###BEAT:`（③导演·指针）由 write-raw --batch 自动执行对应子命令落盘（`add`/`rewrite` 后直接跟事件线 YAML 块直到下一个 `###` 行·失败=批次拦截 exit 1）——**LLM 不手动调用 storyline/beat 写命令**；下表命令保留用于查询（show）与维护。
> **每轮触发（硬性·条件跳过）**：②编剧常态 no-op（张力基调一行确认）·触发时 `###STORYLINE: add/rewrite/close/clear`（当前拍=余波→close 必带收束摘要·当轮建后继线；顶点拍预填 顶点约束·缺则拒绝）；③导演每轮回判——已兑现→`###BEAT: advance SL-XX 下一拍`（顶点=advance 余波·受 gate director 收束核验）·未兑现且问题正被逼近→`###BEAT: stay SL-XX`（承接判断须写出逼近路径·上轮节拍决策=继续当前拍而本轮仍 stay→本批必写 escalation_flags.停滞·gate 核验→①次轮加压/兜底·余波拍除外）·不承接/意外事件→escalation flag→②次轮 rewrite/clear；查询轮/维护轮豁免。

## Shell 脚本

| 脚本 | 用法 |
|------|------|
| write_narrative.py | `cat <<'EOF' \| python3 {skill_dir}/scripts/write_narrative.py <世界> <场景ID>`（场景ID支持短 ID S05 或完整目录名）——⚠ 写入磁盘：叙事正文落盘至焦点场景 narrative.md |
| snap.py save | `python3 {skill_dir}/scripts/snap.py <世界> save [快照名]`（缺省名自动生成「场景ID-场景名-时间戳」）——⚠ 写入磁盘：复制当前状态至快照目录 |
| snap.py load | `python3 {skill_dir}/scripts/snap.py <世界> load <快照名>` | 破坏性操作（覆盖当前状态·自动备份 _before_）——交互提示确认 / 非交互加 `--force` |
| snap.py list | `python3 {skill_dir}/scripts/snap.py <世界> list` |
| snap.py delete | `python3 {skill_dir}/scripts/snap.py <世界> delete <快照名>` | 破坏性操作（不可恢复）——交互提示确认 / 非交互加 `--force` |
| init_scene.py | `python3 {skill_dir}/scripts/init_scene.py <世界> <场景ID> <场景名> [--from <旧场景ID>] [--type <类型>] [--time <时间>] [--cast <出场角色>]`（--from：继承旧场景 scene_state 的物理锚点/道具清单——**同物理地点切换必用**，防止漏继承；--type/--time/--cast 自动填充 scene_card 与 INDEX 行，缺省标「待填」） |
| reset_scene.py | `python3 {skill_dir}/scripts/reset_scene.py <世界> [<场景ID>] [--force]` | **重置场景到 start_snapshot 状态**——清空场景内动态叙事（narrative 轮转归档 + scene_state 场景时间线/核心状态重置），静态基线（物理锚点/道具/关键场景信息）保留；场景ID 缺省=当前焦点场景；破坏性操作（重置前自动存档可回滚）——交互提示确认 / 非交互加 `--force` |
| reset-cycle | `python3 {skill_dir}/scripts/worldctl.py <世界> reset-cycle [--asset <角色名>]` | 循环世界重置一键命令——**周期重置（缺省）**：全员重置+登记重置记录+重建周期倒计时（write-raw ④b 顶回后调用·豁免判定含于其中·无需前置确认）；**事件触发重置（`--asset <角色名>`）**：叙事中角色被系统强制重置（回收/死亡修复/「校准」）时调用——只重置指定角色+登记事件触发重置记录+**不重建周期倒计时**（叙事事件不移动周期重置点）。两者都：脚本自动存档+联动表压缩/清空/回基线+行为轨道回归占位。**单角色豁免：** 预先在 `world_state.重置记录.{角色}` 写 `触发: 豁免` + `重置日期: 第N日` → 该角色在登记的重置点被跳过（园区维护人员按指示跳过该资产·loop_machinery §4）——豁免一次性（按重置日期精确匹配·后续重置点照常重置·由后续重置登记自然覆盖）；豁免角色不登记周期记录（保留豁免标记·validate 8b 跳过）；audit ④b 覆盖判定排除豁免记录（豁免不算全员重置已执行·其他循环角色仍须重置）。调用后 LLM：保留候选微调 / 状态按 LOOPS 补写 / CT 节拍核查 / 重置叙事。幂等（当日已重置则重跑无害） |
| index.py add | `python3 {skill_dir}/scripts/index.py <世界> add <ID> <名> [类型] [时间] [出场] [状态]`（动作在前 `index.py add <世界> …` 同样支持） |
| index.py activate | `python3 {skill_dir}/scripts/index.py <世界> activate <场景ID>`（动作在前同样支持） |
| index.py update | `python3 {skill_dir}/scripts/index.py <世界> update <场景ID> [--type/--time/--cast/--status]`（动作在前 `index.py update <世界> <场景ID> …` 同样支持） |
| index.py remove | `python3 {skill_dir}/scripts/index.py <世界> remove <场景ID>`（动作在前同样支持） |
| list_worlds.py | `python3 {skill_dir}/scripts/list_worlds.py` |
| create_world.py | `python3 {skill_dir}/scripts/create_world.py <世界名>` | 创建新世界脚手架——⚠ 写入磁盘：在 `{WORLDS_ROOT}/{世界名}/` 创建目录与模板文件（SETTING/CONFLICTS_SEED·零 yaml）；动态文件由启动世界 init-states 物化（见 session_recovery.md 第二章） |
| import_card.py | `python {skill_dir}/scripts/import_card.py <世界名> <角色卡.png...>`（支持 .json 卡；`--dry-run` 预览不落盘） | ⚠ 写入磁盘：提取 SillyTavern 角色卡全部字段 → 临时素材 tmp/{名}.card.json；LLM 先评估（注入/敏感/版权→披露等确认）再综合生成正式 CHAR_{名}.md，生成后即删临时素材（详情见 references/import_cards.md） |
| reset_world.py | `python3 {skill_dir}/scripts/reset_world.py <世界名> [--force]` | 重置世界到创建完成态（纯 .md·零 yaml）——删 scenes/CHAR_state/全部动态 yaml·重置前自动存档可回滚·重置后走启动世界（首次启动态）；破坏性操作——交互提示确认 / 非交互加 `--force` |

## 用户命令（对话内）

| 命令 | 作用 |
|------|------|
| 「创建世界 <名>」 | 走 session_recovery.md 第一章（create_world.py 脚手架 + 创作填充→校验→收尾提示启动世界） |
| 「重置世界」/「/reset」 | reset_world.py——破坏性操作（自动存档可回滚）·重置后走启动世界（首次启动态） |
| 「重置场景」/「/reset-scene [场景ID]」 | reset_scene.py——重置指定场景（缺省=当前焦点场景）到 start_snapshot 状态（自动存档可回滚） |
| 「启动世界」「继续世界」「恢复」等（会话首轮） | 启动世界统一序列（首次启动/跨 Session 恢复）——走 session_recovery.md 第二章：物化→入场物化→分层加载→validate→循环核对→描绘→停住·不推进 |
| `/scene <ID>` / `/scene new <名>` | 场景切换 / 新建场景 |
| `/conflicts` | 查看冲突 |
| `/status` / `/status --full` | 状态摘要 / 完整状态 |
| `/sync` / `/update` | 场记记录变化更新状态 |
| `/save [名]` / `/load <名>` | 存档管理 |
| `/silent` | 切回静默模式（全局默认·沉浸·只推叙事正文）——world_state 写 `输出模式: 静默` |
| `/loud` / 说「调试」「标准模式」 | 切到标准模式（完整回复正文 + D1-D5/W1-W4 闸口）——world_state 写 `输出模式: 标准` |
| 「审计」/「/audit」 | **用户觉察不对劲时使用**——六阶段审计流程（人工清单=references/gates.md·机械项调用现成工具）：① 机械核验=worldctl.py `validate` + `audit` + `gate <阶段> --check` + `round-check` ② 六阶段人工审计=加载 references/gates.md → D/S/R/A/K/W 清单逐项（默认不通过·找茬制·证据引用）③ 知情边界核对=有 knowledge_index.yaml → 独立审计者视角逐条按 `记录` 指针读状态文件比对 + 清理（已公开/已落定/循环重置失效→删·不确定留）④ 伏笔闭环核对=有 foreshadow.yaml → validate 已机械检查 + 人工核对 `时间` 错位。输出=逐项 PASS/FAIL + 证据；FAIL→修复流程（≤2 轮）超限终止报告。**若审计反复发现同类违规（补丁无效）→ 主动建议用户更换 LLM model——不无限打补丁·诚实承认模型能力/注意力上限** |

---

## 执行频率分类

- **每轮执行：** write_narrative.py + worldctl.py（write-raw --batch——**change set 原样转交 + 内置 audit + 写入后自动校验**）
- **场景切换时：** init_scene.py + worldctl.py 更新 world_state 顶层字段（**焦点场景** 唯一权威源·必须同步 INDEX ACTIVE 行）
- **存档管理：** snap.py save / snap.py load
- **跨 Session：** worldctl.py read
- **清理：** worldctl.py delete（CT 归档 / pending 条目移除）
