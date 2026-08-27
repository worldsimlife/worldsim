# 阶段⑤ · 场记（事实引擎·阶段开始前必读）

> 职责：**世界事实的唯一连续记录**——记录已经发生的事实。**状态提交者，不是故事创造者**。
> Single Writer：写 场景状态(scene_state/pending_actions) + 世界状态（world_state/world_map/knowledge_index/foreshadow）。
>

## 数据就绪（本阶段开头·读记录依据）

- **③导演 → direction.调度单**：焦内活跃/背景/焦外·焦外→焦内（含 in-track 循环角色预设·决定出场摘要/焦外记录的归属）
- **④角色 → 各 CHAR_state 本轮更新**：焦内活跃角色行动与结果 · 焦外角色自推演状态（事件/摘要/焦外事实的记录依据）
- **scene_state / world_state 旧值**：当前场景事实（锚点/道具/时间线）/ 时间 / 焦点场景 / 倒计时（推进基准·加本轮已耗时间）
- **scene_management.md（场景管理完整手册·本阶段先读对齐）**：出场/位置/登场退场/焦外/场景切换——全程对齐，不只场景切换处引用。

**记录**：本轮事件→场景时间线 · 出场角色→摘要 · 道具/锚点/线索变化 · 时间/轮次/前情推进 · 倒计时走表 · 全局标记 · 焦外→场景级 pending_actions · 新区域→world_map · 伏笔→foreshadow · 知情→knowledge_index · 重置记录 · round-check 通过。
**焦外角色来源（每轮重判定·不沿用上轮）**：③调度单（焦外·焦外→焦内·含循环预设）· ④焦外角色状态（自推演）——筛相关记场景级 pending_actions（焦外角色状态由④写·⑤禁写 CHAR_state·Single Writer）。
**世界时间数字推进（时间/轮次/前情/倒计时）= 本阶段**（按行动耗时粗推进·不需精确到分钟；其余阶段只读/感知·不重复推进）。

## 职责（顺序执行）

1. **场景事实落盘**：场景时间线 APPEND（本轮事件·yaml 列表元素：轮次/时间/事件）/ 出场角色摘要 KEY（**集合索引**——角色位置权威在 CHAR_state·从④结果派生）/ 道具·物理锚点·线索变化（叙事中移动/发现）。
2. **焦外记录（pending_actions·场景级·缺文件按模板建·templates/pending_actions.yaml）**：③调度单.焦外（含循环预设）+ ④焦外角色状态 → 筛相关（冲突对抗方/时间线节点临近/揭示候选/用户关注）→ 记 `活跃中.{PA-ID}`（角色/时段/行动/当前状态/预计影响/揭示场景·标可揭示）；揭示（焦外→焦内）→ 移 `已完成`·记揭示场景。
3. **世界事实落盘**：world_state 时间.具体时间（旧值+本轮已耗时间窗口·只增不减·跨天先切场景）/ 轮次（单调递增）/ 时间.前情描述（≤100字）/ 外部倒计时走表（本轮有确立/走表/到期时必写·**越过周期到期点→执行 loop_machinery §4 联动表·全员·非活跃焦外不豁免·对接 audit ④b/reset-cycle**）/ 全局标记写删 / 时间线压缩（场景 COMPLETE 时：scene_state.场景时间线 提炼为 world_state.时间线.{旧场景ID}·≤3 转折点·每条≤120字）。
4. **重置联动补写**（reset-cycle 调用后）：world_state 侧补写＋保留候选确认（脚本已做机械部分）。
5. **场景切换机械执行**（③导演 transition 决策 → 落地）：冻结旧场景（终态入 scene_state+时间线压缩）→ INDEX 旧场景 COMPLETED → init_scene 建新场景（同物理地点必用 `--from` 继承锚点/道具）→ world_state.焦点场景 更新（唯一权威源）→ 连续性核查（服装/道具/伤口）→ world_map 登记。细则见 scene_management.md §场景切换流程。
6. **轮完整性收尾检查**：`worldctl.py <世界> round-check`——direction/世界三件套/场景时间线/区域一致性（POV 位置节点 vs 焦点场景区域节点·空间已变未切场景即 FAIL）/引用对账逐项核对；FAIL=本阶段修复或上报。
7. **场记三问收尾自查**（每轮·写后）：①痕迹完整——场景时间线/道具线索→scene_state · 焦外→pending_actions · 伏笔→foreshadow（触发即登记·缺文件按模板建·规则 references/foreshadow.md）· 知情差异→knowledge_index（触发即收录·references/knowledge_index.md）；②落点=焦点场景目录；③连续性=时间/轮次/存档一致。validate 通过 ≠ 自查通过。

## 写入

**写语义三分**：🔁覆盖=当前快照（###KEY:·写前 read 旧值全量重写）｜➕追加=历史累积（###APPEND:·记忆锚点/信念演化/连续行动轨迹/场景时间线/伏笔等）｜🪟窗口=脚本自动裁剪（超窗口自动删最旧·LLM 零操作）。**字段写语义以 keys.md 对应节为权威·批次细则见 write_protocol.md——本节只列动作与触发。**

```
###STAGE: 场记
###META: 落点 焦点✓/时间✓/轮次✓/时间线✓ 轮完整✓
###FILE: scene_state
###APPEND: 场景时间线
- 轮次: 4
  时间: 09:30-09:40
  事件: T 藏钥匙·挡抽屉
###KEY: 出场角色摘要
T（柜台后·盘点）·访客（门口·试探）
###FILE: world_state
###KEY: 时间.具体时间
第1日 09:40
###KEY: 轮次
4
###KEY: 时间.前情描述
T 藏起备用钥匙·访客试探继续
```

## 写入纪律（不变量）

- **唯一通道=worldctl 脚本子命令**（write-raw --batch 等）；中文一律 stdin；非幂等（APPEND 重复执行会重复追加·同一批次只执行一次·验证用 read/validate/--dry-run·禁重放 write）。
- **场景目录先于写入**（硬性）：scene_state 写入前该场景目录必须存在（初始=启动序列入场物化·切换=init_scene），缺失即硬拦。
- 破坏性操作（###DELETE:/load/reset）执行前向用户确认（references/disclosures.md）。
- validate 输出必须看完整问题清单（过滤 `VALIDATE|ERROR|ERR|FAIL` 全类）。

## 闸门

闸门随落盘逐段自动执行（硬性：###STAGE 匹配＋世界三件套＋场景时间线＋落点＋Single Writer·不合格=本段整体拦截不落盘）；单段复检=`gate keeper --check`。标准模式人工审计（K1-K5 清单）见 references/gates.md。
