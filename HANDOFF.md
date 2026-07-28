# AMT Studio 项目交接

最后更新：2026-07-27

## 一句话状态

Task 009B3D 已修复最新空缺重算被误报失败的真实原因：Job `37811672` 和
`37811709` 都已在 A100 节点正常完成 MuScriptor 解码，但目标片段没有产生候选，
旧包装器把合法的空 JSONL 当成模型崩溃。现在只有定向补漏允许零候选并生成
“原轨不变”的成功版本；整曲识别仍不会接受空输出。任务状态会记录新增数量，
失败时会尽量取回并显示真实原因。日文路径的 NFC/NFD 等价形式也改用文件系统
身份验证，不再阻断状态读取。

同一任务还把“连续音碎片”做成所有音高类产品轨的通用、逐轨操作：每条音轨都可
重新扫描整首、看到“碎片数 → 连续音数”的预览，确认后一次性保存并重新打开校验，
仍可撤销且不改变原始识别版本。打击乐不合成长音，继续使用独立的重复短击规则。
完整 `make check` 通过 291 个 Python 和 49 个 Swift 测试（3 个私有实时测试按
预期跳过）。一次限定范围的复核发现并修复了 `requests` 目录符号链接可逃逸项目
边界的 P1；Unicode 兼容保留。修正版 Hyak 重试应从该任务最终提交同步后执行，
旧失败记录保留。

Task 001–008 和既有项目编辑器已经完成。产品路线现已按所有者的实际试听结果
收敛到 Task 002 MuScriptor 整曲多轨：保留模型输出的全部乐器轨，并在存在时
默认打开 `voice` 作为主唱候选，而不是把它冒充成完整主旋律。此前的 fusion、
额外数据集和 Gate 4 研究路线不再
位于“今天做出可用软件”的关键路径；它们仍保留为研究记录，但不会继续消耗开发
时间。Task 009B2B 私有 Beta 已实现 Mac 导入/轮询/编辑/导出和 Hyak L40 Slurm
推理链路；Task 009B2C 又补齐了 Hyak 登录过期恢复、活动任务重启恢复和真正的
多轨合奏控制。Task 009B2D 已把重型加载/MIDI 预览移出界面主线程，增加历史歌曲、
更稳定的权限入口、双音量控制和 `voice` 长空缺定位。新歌 Job `37735878`
已完成并取回。Task 009B2E 又在不引入 GAME 或分离模型的前提下完成一次同
MuScriptor 定向补漏；184 个候选已经作为独立轨取回，等待所有者与原始
`voice_raw` 对照试听。所有者现已试听通过，认为补漏主观上补回 95% 以上缺失
音符，仍有少数漏音；Task 009B2F 已据此生成非破坏性的增强主唱轨。Task
009B2G 又把这条路线接进新歌的一次上传流程：整曲识别后自动规划疑似长缺口，
在同一个 Slurm 作业中定向补跑并一次取回，不再要求新人重新上传或理解实验步骤。
Task 009B2H 修复了日文项目名在 macOS 的 NFC/NFD 等价形式被误判为身份不匹配的
问题，并把当前识别版本的完整多轨 MIDI 导出改成界面主操作。新歌 Job
`37743206` 现已以 `0:0` 成功完成，整曲多轨、自动补漏和最终包均已取回。
Task 009B2I 随后完成正式产品界面收尾：默认使用克制清楚的“精密模式”，设置中
可切换蓝紫“炫酷模式”；两者只改变视觉，不重载项目、不提交任务也不改变 MIDI。
Task 009B2J 又把原来的单轨卷帘改为“全部音轨/当前音轨”双层工作流：默认把
每条产品音轨作为一行纵向排列，整首时间分布可以同时比较；点选一行后再进入
保留拖动和改长度能力的单轨精细编辑。Task 009B2K 在不改变默认行为的前提下
增加三个计算选项：默认 `Hyak GPU`、本机 `Apple GPU (Metal/MPS)` 和本机
`CPU`。本机模式使用独立低优先级后台进程，沿用整曲多轨、自动补漏和打包
流程；可以检查本机环境并安全停止。按所有者要求，本次只完成代码、状态机、
单元测试和应用打包，没有真的在 Mac 上加载模型或处理歌曲。新歌 Job
`37746586` 已在 Hyak L40 以 `0:0` 完成，用时 `00:21:19`，最终包已取回且
队列为空。Task 009B2L 又补齐了新增音符、整曲验收导航和节拍化
编辑：当前轨可在播放头新增一个可撤销音符，同时显示秒、BPM、拍号、小节和拍；
未来新上传歌曲会在同一 Hyak 作业里顺序运行已固定的 Beat This，再进行补漏和
打包。`37746586` 使用提交时的旧代码，没有被中断或追改，所以其
节拍仍明确标为 120 BPM / 4/4 MIDI 默认值。Task 009B2M 随后把“只能查看
空缺”补成完整闭环：用户可逐段勾选、全选或清除，把多段作为一个 Hyak／本机
任务定向重算；结果成为新版本，源版本不覆盖，主旋律与伴奏轨都可使用。
Task 009B2N 修复了该入口首次实际点击时暴露的 Python `workers` 搜索路径问题；
失败发生在 Slurm 提交前，没有产生新任务。同时新增了保守的结尾延音碎片检测：
只在当前轨结尾提示，用户确认后把连续同音片段作为一次可撤销编辑合并。
Task 009B2O 又修复了第五段被误判越界：真实音频只有 `271.805147` 秒，伴奏模型
却输出到了 `274.96` 秒；产品现在统一以真实音频为时间线，不再让越界 MIDI
把歌曲虚增到 `4:34`。
Task 009B2P 继续补齐了实际产物边界：超出真实音频的预测不会再进入卷帘、试听
或 MIDI 导出；每条音轨还会独立显示结尾清理提示。旋律乐器合并延音碎片，鼓轨
则折叠重复短击，不能错误地把鼓合成长音。Task 009B2Q 随后根据所有者对实际
音频的复听修正了补漏路径：漏掉的清晰主旋律并未出现在任何伴奏轨，不能跨轨
拼接；此前代码只是全乐器重算后过滤 `voice`，现在会在 MuScriptor 解码阶段
直接约束目标乐器。Task 009B2R 又清理了右侧检查器：普通编辑只保留实际会用到
的音符参数，空的置信度复核不再出现，来源和整曲诊断仍可按需展开。

Task 009B2S 进一步把这三个真实使用问题闭环：补漏候选不再直接混入主旋律，
而是先与已识别伴奏做同音同时间软过滤；定向识别后仍为空的三秒以上片段会在
同一次任务中最多自动兜底一遍，不要求用户第三次手动提交。生成结果时，每条
伴奏会按乐器类型独立做保守尾部整理，原始事件另存且不覆盖。人工编辑现在会在
底层音轨兼容时跟随新识别版本，界面也有明确的保存按钮和保存时间。

Task 009B2T 整理了左侧音乐库：项目按运行中、已完成和未完成/失败分组，可搜索，
每行可打开、在 Finder 显示或经确认移到 macOS 废纸篓。删除前会重新读取任务状态，
运行中项目、越界路径、符号链接和身份不匹配目录一律拒绝。尾部修复入口也改为
选择音轨后始终显示：有候选时保留原按钮，无候选时明确说明已自动/人工处理或
本次检查没有命中，不再让用户误以为功能被删。当前 targeted-gap Job `37754413`
已成功完成并取回；默认 voice 没有尾部候选，但 clean electric guitar 仍命中
5 组、51 个碎片。

Task 009B2U 根据所有者对该结果的实际复听纠正了自动补漏策略：Job `37754413`
虽然确实在模型生成阶段约束为 `voice`，但仍把大量伴奏误判进主旋律，从 338 个
音符膨胀到 1,179 个。新版取消产品路径里的 unrestricted 兜底，并加入保守数量
准入；超限候选仍保留为诊断证据，但不会自动合入或成为默认版本。当前项目已恢复
默认打开此前试听较好的 338 音符版本。

Task 009B2V 又缩短并开放了 Hyak 任务时限：新整曲和空缺重算默认 1 小时，
设置中可持久调整为 1–24 小时。当前 L40 Job `37804031` 因组 GPU 配额没有预计
开始时间，已在未运行时替换为 checkpoint A100 Job `37805247`；后者几秒内在
80 GB A100 上启动，应用继续用新 Job ID 轮询。

Task 009B2W 把这次人工比较队列的过程收进了软件。以后整曲识别和空缺重算在
真正提交前都会自动试排已验证的 L40、L40S、A40、A100，选择预计最快的方案，
并把 GPU、队列、等待估计、选择原因和 checkpoint 抢占风险显示出来。用户不再
需要为了每首歌另外打开 Codex 规划 GPU；探测失败时仍会安全回退稳定 L40。

Task 009B2X 没有继续猜测过滤阈值，也没有重新运行模型，而是把已完成
`gap-recovery-20260728T000154Z-244743c9` 的三个真实处理阶段做成同一个
诊断对比版本：原始生成 864 个音符、仅去除 630 个伴奏重合后 234 个音符、再经
单旋律约束去除 73 个后 161 个音符。三轨可逐条独奏，合奏模式不会叠加三种
候选；原主旋律和源版本均未覆盖。下一步只需要所有者试听三轨并反馈哪一层最接近
目标，不能把一次主观比较直接写成准确率或自动放宽产品准入。

所有者完成试听后明确选择 864 音符的原始生成为三者中最好。Task 009B2Y 据此
把自动补漏和手选空缺重算的产品候选切换到原始生成，并完整删除了
`max(32, source / 10)` 这一与空段长度无关的数量门。伴奏过滤和单旋律约束仍会
生成可追溯诊断文件，但不再决定产品轨。边界没有放开到整首任意生成：仍然只处理
检测或手选的空段、在解码时约束 `voice`、裁剪到真实音频时间线并保留不可变源
版本。现成任务已无模型重跑地生成 1,186 音符的新产品版本，等待所有者最终试听。

Task 009B2Z 把版本和音轨管理补成了普通用户可用的非破坏性流程。旧实验中间版本
继续留在项目里作证据，但普通版本列表不再显示“诊断版本”。用户可以从另一个
产品版本复制一条音轨到当前版本，合并当前版本的多条音轨并指定合并后的乐器，
或从新副本删除某条音轨；所有操作都生成新的 `custom-*` 版本，源识别结果不会
覆盖。删除单个音符已经移动到精细编辑工具栏并与新增音符并列。每条音轨的齿轮
菜单还会显示该轨自己的延音碎片候选，可经确认一键修复、保存和撤销；鼓轨仍按
重复短击处理，不会被错误合成长音。

Task 009B3C 修复了活动 GAME 作业被旧识别结果遮住的问题。提交后或重开运行中
项目会自动进入六阶段进度页；用户可以返回旧结果试听，再从顶部回到任务进度，
不会停止或重复提交作业。远端阶段判断也改为显示当前正在运行的分离、GAME、
节拍或打包步骤，而不是慢一阶段的已完成产物。

Task 009B3B 将可选 GAME 产品入口升级为独立锁定的官方 large 权重，同时修复了
“列表显示碎片但菜单说不可修复”的 SwiftUI 旧状态问题。Task 009B3A 把此前已经
验证过但只用于研究对比的 GAME 路线接成了可选产品入口。
默认仍是 MuScriptor 完整多轨；用户主动选择 GAME 时，Hyak 会在同一个 Slurm
作业里依次运行 BS-Roformer 人声分离和隔离的 GAME 环境，最终生成一条 `voice`
单轨。已有项目也可新增一个 GAME 版本，再用现有跨版本复制功能组合到多轨版本；
系统不会自动融合、替换或同时播放两条主唱候选。公开仓库不包含权重或个人 Hyak
身份。当前只完成代码与契约验证，没有替用户提交真实模型任务。

## Task 009B3C GAME 任务进度交接

- 有未结束任务时，中央区域优先显示任务进度；即使项目已经有可编辑旧结果，也
  不会再被旧钢琴卷帘遮住。
- GAME 进度固定为：`提交任务 → 等待 GPU → 分离人声 → GAME 识别 →
  节拍分析 → 打包取回`。状态来自 Slurm 和远端实际产物，不是估算百分比。
- `查看已有结果` 只切换页面，不会取消 Hyak 作业；顶部 `任务进度` 可随时返回。
- 后台每 20 秒轮询只更新状态，不会再把正在试听旧结果的用户强制弹回进度页。
  定向片段重算使用自己的四阶段文案；即使打开另一首歌，进度页标题仍绑定真实
  活动作业。
- 恢复运行中项目、切换旧结果/进度和后端阶段推进都有针对性回归；完整
  `make check` 通过。本轮没有提交、取消或替换任何模型作业。

## Task 009B3B GAME large 与整轨碎片修复交接

- `workers/game/pins.json` 继续固定历史 medium 实验；
  `workers/game/pins-large.json` 单独固定产品用 large。large 是官方 PyTorch
  发布中容量最大的版本，不代表已经在用户歌曲上证明更准。
- 产品提交只接受唯一的 large provenance，并搜索真实部署目录
  `amt-studio/models`。medium 不再被产品路径静默接受。
- 每条音轨齿轮菜单始终有重新扫描入口。非鼓音轨使用已有的全曲同音连续碎片
  分析，不局限结尾；鼓的重复短击不能当作延长音，仍使用单独的保守尾部规则。
- 修复仍生成持久化、可撤销的编辑，不改变原始模型版本。Hyak setup Job
  `37810626` 已在 A40 计算节点完成 large 安装、CUDA/导入与逐文件哈希校验；
  本地后端能唯一发现 large provenance 和分离模型。该作业不包含歌曲推理。

## Task 009B3A GAME 主唱旋律单轨交接

- 设置和顶部工具栏提供两个下一曲模式：
  - `完整多轨（MuScriptor）` 是默认值，继续输出当前完整多轨和自动 voice 补漏；
  - `主唱旋律单轨（GAME）` 只输出人声主唱旋律，不把它描述成器乐主旋律模型。
- GAME 选择会自动切回 `Hyak GPU`，本机 MPS/CPU 不可误跑。产品脚本
  `slurm/43_private_beta_game_vocal.slurm` 拒绝登录节点，按顺序运行
  `vocal_quality_a`、GAME seed 3407、可选 Beat This 和单轨打包。
- 后端从用户自己的 Hyak 私有持久目录发现经过 hash 约束的
  `GAME-1.0-medium` provenance 和 BS-Roformer checkpoint；无法唯一定位时会
  明确失败，不会下载、猜路径或回退到整曲混音直接跑 GAME。
- `用 GAME 新建主唱旋律单轨` 可对已打开项目创建一个新的不可覆盖版本。完成后
  默认打开 GAME 的 `voice`，原多轨版本不变；若要组合，使用现成的“从其他版本
  复制音轨”，而不是自动融合两种模型。
- GAME 没有逐音符 confidence/velocity，产品保持为空。官方权重许可
  `CC-BY-NC-SA-4.0`，因此功能和源码可公开，但权重不得随应用或仓库分发，当前
  仍是私人非商业研究路径。
- GAME 会在远端操作前拒绝覆盖未结束任务，并只选择不可抢占 GPU；当前串行分离
  与识别链不冒充可从 checkpoint 自动恢复。
- `make check` 通过 278 个 Python 和 44 个 Swift 测试，三项私有环境测试按设计
  跳过；Slurm shell syntax、Python compile 和 `git diff --check` 通过。没有
  提交 Hyak 或本机推理任务；下一步仅是所有者主动发起一首真实歌曲并试听比较。

## Task 009B2Z 跨版本音轨管理与逐轨碎片修复交接

- 左侧普通“识别版本”只列产品可用版本。旧拒绝包和三阶段对比包没有删除，仍可
  从底层 JSONL 和 manifest 追溯，但不再要求普通用户理解或操作。
- 点击 `管理版本与音轨`：
  - `从其他版本复制音轨` 会保留来源版本，并把选中轨及其已保存编辑复制进一个
    新自定义版本；
  - `合并当前版本的音轨` 至少选择两轨，并从参与轨中指定合并后的乐器。合并为
    音符并集，不擅自删除时间重叠的音符；
  - `删除当前版本中的音轨` 只从新副本删除，且至少保留一条可见产品音轨。
- 每个音轨的 `音轨设置` 提供编辑、智能修复和版本/音轨管理。旋律乐器会在全轨
  范围检测连续同音、短片段占多数且跨度至少两秒的疑似延音碎片；鼓轨继续只处理
  保守的尾部密集重复短击。修复前会确认，结果自动保存且可撤销。
- `新增音符` 与 `删除音符` 现在并排位于“当前音轨”的精细编辑工具栏；右侧检查器
  不再单独占一块显示删除按钮。
- 跨版本写入使用临时目录、哈希 manifest 和完成后重新加载验证。合并后的轨道和
  每个音符都统一使用用户选定的乐器，所有新音符仍保留来源 bundle、来源轨和
  source event ID。用户在写入期间切换项目时，旧操作不会把界面抢回旧项目。
- `make check` 通过 282 个 Python 和 44 个 Swift 测试，三项私有环境测试按设计
  跳过。真实日文项目通过生产加载器和应用模型打开/完整 MIDI 导出，签名应用已
  重建并打开。没有提交 Hyak 或本机模型任务。
- 单次 `/review` 调用因开始越界检查暂停的 Task 007D 而被及时终止；在终止前
  暴露的两个本轮 P1（切换项目竞态、合并音符乐器标签不一致）均已修复并加入
  回归测试。没有继续扩大审查。

## Task 009B2Y 原始候选产品化与取消数量上限交接

- 产品候选固定为 `raw_generated`：自动整曲补漏与手选多段重算都将原始的
  voice-constrained 候选合入 `voice_auto_enhanced`。
- 不再计算或执行固定新增音符上限；100 秒以上空段不会因为超过 32 个音符而整批
  被拒绝。准入证据记录
  `accepted_owner_selected_raw_generation` 和 `count_limit_applied=false`。
- soft mask 过滤结果现在另存为 `*.filtered.jsonl`，单旋律结果也继续保留用于
  诊断和以后对比；两者不会替代所有者已选择的产品候选。
- 历史上明确标记 `rejected_excessive_voice_growth` 的旧包仍保持诊断身份，
  避免改代码后悄悄重写历史判断；新生成的无上限包才可成为默认版本。
- 当前私有产品版本：
  `gap-recovery-20260728T000154Z-244743c9-raw-product`。其中
  `voice_auto_enhanced` 为 1,186 个音符，即原 322 加原始候选 864；所有伴奏轨
  保持不变，源包未覆盖。
- 该包通过生产加载器和完整 MIDI 验证。`make check` 通过 282 个 Python 和
  39 个 Swift 测试（三项预期环境跳过）；签名应用已重建并打开，没有提交 Hyak
  或本机模型任务。

## Task 009B2X 三阶段补漏对比交接

- 实际私有对比版本：
  `gap-recovery-20260728T000154Z-244743c9-stage-comparison`。
- 三条轨固定为 `gap_raw_candidate`（864）、
  `gap_accompaniment_filtered`（234）和
  `gap_monophonic_candidate`（161）；每条轨另有一个同名 `.mid`。
- 中间 234 不是重新计算或人工估计，而是使用已保存报告里的 630 个
  `shadowed_event_ids` 从 864 中确定性排除；最终 161 直接读取原任务保存的
  `target_gap_candidates.jsonl`。
- 对比版本被明确标为 diagnostic-only 和未通过默认主旋律准入；它不会在启动时
  取代安全产品版本。用户可在左侧“识别版本”手动打开它，再使用“当前音轨”或 S
  独奏依次试听。
- 生成入口为
  `uv run python -m scripts.build_gap_stage_comparison --project <PROJECT> --run-id <RUN> --output-bundle <BUNDLE>`。
  它只接受成功、哈希匹配且带完整 soft-mask 证据的 voice 补漏任务。
- 已通过真实项目显式加载、事件 ID 唯一性、三阶段计数、独立 MIDI 和互斥试听
  回归；没有提交 Hyak / 本地推理。

## Task 009B2W Hyak 自动选卡交接

- 计划器只读取当前 Slurm association，并用 `sbatch --test-only` 比较资源；
  试排不分配节点，也不会产生排队 Job。
- 只允许项目已验证且显存足够的 L40、L40S、A40、A100。预计开跑时间优先；
  与最早方案相差不超过五分钟时，固定按
  `A100 > L40S > L40 > A40` 择优。
- 试排参数与随后真实 `sbatch` 的 account、partition、QOS、GPU 和时限完全
  相同，避免“测的是一套、提交的是另一套”。Slurm 把 test-only 预计时间写到
  stderr，后端已显式合并读取并有回归测试。
- A100/A40 来自 checkpoint 路线时会标橙色抢占风险。所有探测失败不会阻断
  上传，而是按现有稳定 L40 Slurm 脚本继续提交。
- 本地状态只保存非秘密调度元数据；计划器没有新增个人 Hyak 用户名、host login、
  私有路径、密码或 Duo 信息，候选账号来自实时 Slurm association。实际
  host/root 仍只来自 ignored 的本机配置。
- 2026-07-27 16:54 PDT 的只读实测比较了四个兼容计划并选出预计 1 秒内可开的
  A100。队列中没有新增测试任务；既有 Job `37805247` 保持运行且未被修改。
- `make check` 通过 281 个 Python 和 38 个 Swift 测试（三项预期环境跳过）；
  strict Swift formatting、签名应用构建、plist/signature 和 diff 检查通过。

## Task 009B2V Hyak 排队与运行时限交接

- `sbatch --test-only` 的当时快照：普通 L40 预计
  `2026-07-28T06:22:38 PDT`，L40S 预计 `2026-07-27T20:19:38 PDT`，checkpoint
  A40/A100 均可立即开始；这些只是当时的调度估计，会随队列变化。
- 原 Job `37804031` 从未运行，已取消。新 Job `37805247` 只请求一张 A100，
  时限 `01:00:00`，当前由 app 状态文件正常跟踪，不应再次提交同一首歌。
- 软件仍把标准 L40 作为可复现默认 GPU 路线；本次只为当前堵塞任务人工选择
  checkpoint A100。checkpoint 可被抢占，若出现 `PREEMPTED` 应按失败状态处理。
- `设置` 中的时限只影响之后提交的 Hyak 整曲/空缺重算；本机 GPU/CPU 与正在
  运行的 Slurm Job 不会被修改。默认 1 小时，可选 1–24 小时。
- `make check` 通过 277 个 Python 和 38 个 Swift 测试（三项预期环境跳过）。

## Task 009B2U 主旋律补漏安全准入交接

- 根因不是前端没有切到新版本，也不是忘记传 `--instruments voice`。真实请求和
  子任务都使用了 voice allowlist；问题是 MuScriptor 在长窗口内仍会把明显伴奏
  预测成 voice，所以“标签是 voice”不能等同于“确实是主唱”。
- 前一个所有者试听较好的版本由 322 个原始音符增加到 338 个；最新差版本又增加
  841 个，达到 1,179 个。这个数量差异是产品安全门的证据，不是准确率。
- 自动和手选主旋律补漏现在都只保留定向 `voice` 路线，不再运行 unrestricted
  residual fallback。候选仍会保存并经过伴奏 soft mask，但只有新增数不超过
  `max(32, 原轨音符数 / 10)` 才能自动进入产品轨。
- 超限不等于删除：run 内原始/过滤候选和旧 1,179 音符 bundle 都保持不变，可手动
  打开诊断；应用只是不再默认选择它。未来被拒绝的任务会生成安全派生版本，主旋律
  保持源版本不变，超限候选会作为不参与合奏的诊断轨显示。用户之后手动选择的其他
  合格历史版本也会在重启后保留。
- 当前应用工作区默认恢复为
  `gap-recovery-20260727T035419Z-c5001346-multitrack` 的
  `voice_auto_enhanced`，共 338 个音符；坏版本在版本列表中以橙色诊断标签显示。
- 伴奏轨的手选空缺重算和逐轨尾部碎片清理不受这一主旋律准入影响。本次没有提交
  新 Hyak 或本机推理任务。
- `make check` 通过 276 个 Python 和 38 个 Swift 测试（三项预期环境跳过）；
  真实项目测试同时确认 338 音符安全版本和吉他 5 组／51 碎片诊断。

## Task 009B2T 音乐库与尾部修复交接

- 删除是“移到废纸篓”，不是永久清空；整个项目目录内的原曲、结果和人工修改会
  一起移动，用户可以从 macOS 废纸篓恢复。
- 扫描到的旧状态不能单独授权删除：执行前会重新验证项目必须是私有项目根目录
  的直接子目录、不是符号链接、manifest 身份一致，而且最新 Slurm 状态必须明确
  为终态；状态文件损坏、缺字段或未知/暂停/重排等非终态均按仍在运行处理。
- 如果删除的是当前打开项目，播放器、预览、选择状态和最近项目记录会一起清空；
  删除其他项目不会关闭当前工作区。若另一个项目仍有活动任务，其轮询和取回状态
  会保留，不会被当前项目的删除操作误停。
- 已有旧结果但最新一次重算失败的项目仍归入“未完成或失败”，不会因历史结果而
  错排到“最近完成”。
- 尾部修复并未丢失。旧界面只在检测到候选时渲染整个面板；当前默认 voice 无
  候选，所以它消失。现在面板常驻，切到 clean electric guitar 会重新出现
  `合并为延长音`，真实项目验证为 5 组 / 51 个碎片。
- 单次定向 `/review` 找到的两个 P1 删除状态问题和一个失败任务分组问题均已修复；
  没有继续扩大审查范围。

## Task 009B2S 保存、补漏与产物后处理交接

- 不能把“主旋律减去伴奏”实现为直接音频或 MIDI 相减：真实旋律可能与伴奏同音，
  两次识别也不是样本对齐信号。实现采用同音同时间的 accompaniment soft mask，
  原始 directed/fallback 候选都保留，最终轨只使用过滤后的单声部路径。
- 定向 `voice` 识别后，每个仍空三秒以上的已选目标最多生成一个带上下文的
  unrestricted MuScriptor 子任务。它会保留原预测乐器、排除鼓点、再经过同一
  soft mask；不会再次递归补漏。
- 当前 841 个旧候选只读验证后留下 160 个，606 个被判断为伴奏影子，75 个因
  同时复音竞争被移出首选路径；仍空的区间包括 `0:00–0:15`。这些数字只是旧
  结果上的算法诊断，不是准确率，旧 bundle 没有被改写。
- 新生成 bundle 会自动逐轨整理尾部：吉他／钢琴／贝斯等合成延音，鼓轨只折叠
  为一个短击。发生改变时，清理前事件写入 `raw_tracks/`，详细记录写入
  `reports/trailing_sustain_cleanup.json`。当前曲子只读命中吉他 51、贝斯 10、
  鼓 14 个碎片/击打。
- 旧编辑并非消失：它们原来按 bundle 存储。新版保存 selected-track SHA，并在
  相同底层音轨进入新 bundle 时迁移；旧格式则必须有 before-state 且完整重放
  成功。真实最新 bundle 已验证能找回之前的 clean-guitar 修改。
- `保存修改`（`Command-S`）和侧栏保存时间现在可见。新增/拖动/缩放/删除、
  undo/redo 和自动清理仍会即时原子保存；显式按钮用于给用户确认感。
- `make check` 通过 274 个 Python 和 37 个 Swift 测试（三项预期环境跳过）。
  本次没有提交 Hyak 或本机模型任务。

## Task 009B2R 右侧检查器交接

- `待复核 0/0` 对当前 MuScriptor 轨没有作用，因为 338 个音符都没有模型置信
  度；新版在整条轨均无置信度时自动隐藏该面板，有真实置信度的模型轨仍保留。
- 音高、起点、终点、长度和删除音符保持直接可见。模型、Run 和置信度来源放入
  默认折叠的 `来源信息`，需要排查时仍可展开。
- 原来常驻的 `整曲验收 1663 项` 改成底部一行 `高级诊断`，默认折叠；结尾延音
  或鼓点清理只有当前轨真的检出候选时才会直接出现。
- 新签名 App 已在真实项目上目视确认。重启界面没有取消所有者刚提交的补漏作业，
  它仍为 `RUNNING`。
- 完整 `make check` 通过 267 个 Python 和 36 个 Swift 测试（三项预期环境
  跳过）；严格 Swift 格式检查与 `git diff --check` 通过。

## Task 009B2Q 主旋律定向解码交接

- Job `37751981` 的旧路线确实运行成功，新版从 322 增至 338 音符，但五段只
  补回 16 个：`2:09.571–2:10.271` 两个、`3:29.261–3:35.261` 十四个，其余
  三段为零。因此不是前端没切版本，也不是结果包漏拷贝。
- 所有者复听确认：缺失的明显主旋律既不在主旋律轨，也不在任何伴奏轨；伴奏
  本身识别正确。后续禁止把吉他、钢琴或其它伴奏事件冒充主旋律候选。
- 根因是原补漏子任务没有使用 MuScriptor 已支持的 `--instruments`，只是生成
  全部乐器后再保留目标标签。现在自动补漏固定传入 `voice`，手选补漏传入当前
  轨的 canonical instrument，从模型生成阶段开始约束目标。
- 旧 bundle、338 音符版本和原始 JSONL 均保持不变。要判断修复后的真实召回，
  需要用户重新选择确认存在旋律的空段再运行一次；本次没有自动提交新作业。
- 聚焦测试 15/15 通过；完整 `make check` 通过 267 个 Python 和 36 个 Swift
  测试（三项预期环境跳过）。

## Task 009B2P 逐轨结尾清理交接

- 只要是应用正常导入的新歌曲，manifest 都有 canonical 音频时长。当前轨、
  全部轨卷帘、复核列表、MIDI 试听和单轨／完整多轨导出都会自动删除起点已越过
  音频终点的产品音符，并把跨越终点的音符截到终点；原始模型 JSONL 不改。
- 混音器和全部音轨卷帘的每一行都会独立分析并显示橙色提示。点击该轨后，右侧
  `整曲验收` 才显示属于这条轨的清理按钮。
- 钢琴、吉他、贝斯等有音高轨仍采用 `合并为延长音`；鼓轨采用
  `折叠重复打击`，每个被检测的鼓音只保留第一个短击，绝不会生成没有意义的
  长鼓音。两种操作都是一次可撤销编辑。
- 清理不会静默执行，因为真实轮指、重复弹奏、鼓点或滚奏也可能长得相似，仍需
  所有者试听后确认。
- 当前歌曲鼓轨在真实时间线内检出 2 组、14 个重复短击；另有 28 个鼓音起点在
  `271.805147` 秒之后，已自动排除。贝斯轨检出 1 组、10 个延音碎片。
- `make check` 通过 265 个 Python 和 36 个 Swift 测试（三项预期环境跳过）；
  真实项目加载和鼓轨导出通过。本次代码实现没有提交任务；所有者在 20:54
  实际重试的五段请求已通过修正后的边界，Job `37751981` 现为 `RUNNING`，
  本次收尾没有取消、重提或更改它。

## Task 009B2O 真实音频时间线交接

- 截图里的 `selected gap 5 is outside the song timeline` 不是用户选错。
  App 用最晚 MIDI 音符 `274.96` 秒生成了第五段，而后端依照 canonical 音频
  `271.805147` 秒正确拒绝了它；该次仍停在本地规划，没有提交 Hyak。
- 时间轴、节拍位置、空缺列表和结尾延音检测现在共用 canonical 音频时长。
  当前五段精确修正为 `0–60.51`、`81.75–120.09`、`123.34–130.72`、
  `209.26–215.73`、`254.04–271.805147`；只读真实规划全部通过。
- 后端边界没有放宽：恰好结束于音频终点允许，真正越界仍拒绝。
- 所有者已经在旧版点击过结尾合并，因此现有 app correction 中有五个长音结束
  于 `274.96`。新版选择 `clean_electric_guitar` 时会把这些仅由本 App
  生成的旧版长音截到 `271.805147`，另存为一次可撤销更新；原始模型 JSONL
  不变。
- `make check` 通过 265 个 Python 和 33 个 Swift 测试（三项预期环境跳过）；
  没有生成 request、提交 Slurm 或运行本机模型。

## Task 009B2N 提交修复与结尾延音交接

- 截图中的 `ModuleNotFoundError: No module named 'workers'` 来自已安装 console
  script 的 `sys.path`，不是 Hyak、Duo 或模型错误。后端现会先加入已经验证过的
  仓库根目录再加载 worker；导入失败也只返回简短 JSON 错误，不再弹整段 traceback。
- 这次失败没有提交 Slurm。项目任务文件仍是已完成的 `37746586`，没有新的
  Job ID，也没有残留 `requests/*.json`。
- `clean_electric_guitar` 的真实 JSONL 证明确有模型碎片：结尾五个固定音高被
  切成 121 段；从 `270.12` 秒开始，同一和弦每 `0.23` 秒重复一组。这不是
  卷帘绘制造成的视觉假象；但后续 B2O 已确认 `271.805147` 秒之后的部分越过
  真实音频终点，本身也是模型 spill。
- 选择该轨后，“整曲验收”会显示 `结尾疑似延音碎片`。点击 `合并为延长音`
  并确认，会把五组分别合并为五个长音，作为一个 `.merge` 编辑写入，因此一次
  撤销即可还原；原始 bundle、模型 JSONL 和其他音轨均不修改。
- 检测门槛限制在曲尾、同音、首尾间隙不超过 30 ms、至少四段、总长至少两秒且
  过半为短片段。它不会在全曲自动吞掉正常轮指；界面也明确要求先试听确认。
- `make check` 通过 264 个 Python 和 31 个 Swift 测试（三项预期环境跳过）；
  真实项目只读验证准确检出 5 组、121 段。没有启动 Hyak 或本机模型。

## Task 009B2M 可选空缺重算交接

- “当前音轨空缺”位于左侧栏。列表不再只显示前四项；每段有复选框，并提供
  `全选`、`清除`、`重新分析所选 N 段`。
- 点击提交后会再次确认计算位置。所选多段进入同一个作业，每段携带四秒上下文；
  超长段才会在同一作业内切片，不会为每段分别排队，也不会重跑整首。
- 目标乐器来自当前轨的 MuScriptor instrument，因此
  `voice_auto_enhanced`、吉他、贝斯等都可定向重算。空白不等于一定漏识别，
  新音符仍是待试听候选。
- 新任务先验证源 bundle、音频身份、目标区间确实为空且不重叠。完成后保留
  全部旧轨，只有目标轨在新 bundle 中加入候选；旧 bundle 和旧任务状态历史
  均保留。
- 当前 `ピカソ-ビギン-ザ-ナイト` 的 `voice_auto_enhanced` 实际有五段长空缺；
  前两段约为 `0:00–1:00.51` 和 `1:21.75–2:00.09`。用户可以只勾这两段，
  也可以全选五段后提交。系统没有代替用户提交真实计算任务。
- 完整 `make check` 通过 263 个 Python 与 29 个 Swift 测试（三项预期的
  环境门控跳过）；真实项目加载和五段请求计划也已只读验证。
- 本 Task 仅启动了一次定向 `/review`；网络中断后八分钟以上没有返回任何结果，
  因而停止该空转进程且没有重跑。随后只做了 P0/P1、敏感信息和路径边界的人工
  定向检查，没有发现阻塞项。

## Task 009B2L 节拍与验收交接

- `新增音符` 位于当前音轨工具栏，快捷键是 `Command-Shift-N`。它在播放头
  创建一拍长的音符并立即选中；拖动、左右边缘改长度、删除、撤销和重做沿用
  同一非破坏性编辑历史，原始模型 JSONL 不会改写。
- 当前音轨顶部同时显示时间与 `第 N 小节 · 第 N 拍`，卷帘里保留每五秒标签，
  并增加逐拍竖线和每小节起点。BPM 使用 tempo map 的中位数作为稳定摘要，
  MIDI 导出仍保留完整 tempo/meter map。
- 新 Hyak 单曲流程为 MuScriptor 整曲多轨 → Beat This 节拍/下拍 →
  MuScriptor 定向补漏 → 打包/取回；仍然只有一个 Slurm Job，模型只在计算
  节点顺序运行。若 Beat This 单独失败，整曲多轨仍会用明确标注的默认 MIDI
  网格继续交付，不会因为附加节拍分析丢掉有效识别结果。
- 旧项目若没有 Beat This 来源，会显示“未分析；当前为 MIDI 默认网格”，
  不能把 120 BPM / 4/4 当成识别结果。Beat This 当前能估算每小节拍数，但
  normalizer 固定四分音符分母，因此 6/8 等复合拍号尚不能宣称可靠区分。
- “整曲验收”跨正常产品音轨提示低置信度与异常短音，并可逐项跳转；这些只是
  定位线索，不会自动删音，也不等于正式准确率或确定错误。
- 已构建并签名的新应用在
  `apps/AMTStudioMac/dist/AMT Studio.app`。Job `37746586` 完成并取回后，
  旧应用已安全退出，新签名版本已经重新打开。
- 完整 `make check` 通过 259 个 Python 与 29 个 Swift 测试（三项预期的
  环境门控跳过）；唯一一次聚焦 `/review` 未发现剩余 P0/P1 阻塞。

## 当前产品主旋律

在软件中打开 `1-07-still-love-her-失われた風景`，选择结果
`task009b2f-owner-approved-enhanced`。其中三个版本始终保留：

- `voice raw（原始，不修改）`：原始 254 音符主唱候选；
- `voice gap candidate（仅补漏候选）`：本次 184 音符定向补漏结果。
- `增强主唱（原始 + 已审核补漏）`：438 音符的当前推荐产品轨。

软件默认选择增强主唱。三种主唱版本在合奏中互斥：切换到原始版或仅补漏版时，
不会同时播放增强版造成重复发声。所有增强音符均保留来源，原始 JSONL 与补漏
JSONL 都未覆盖。所有者的“95% 以上”是单曲主观补漏估计，不是正式准确率。

以后新上传歌曲使用 `voice_auto_enhanced` 作为 Beta 默认主旋律。它与上述经过
所有者试听的 `voice_enhanced` 不同：自动版只说明系统完成了同模型缺口补跑，
不表示候选经过人工确认。普通界面默认隐藏 `voice_raw` 和
`voice_gap_candidate`，但项目包继续保留；标准完整多轨和合奏最多播放其中一个
主旋律版本。自动补漏失败时，整曲原始多轨仍会作为有效结果交付。

Hyak Job `37740313` 的四个子推理均成功；父作业在推理完成后因旧节拍 map 缺少
新版 MIDI 来源字段而以 `1:0` 结束。兼容修复在 Mac 上复用现有候选生成了双轨
试听包，真实项目 Swift 加载测试通过，没有重复运行模型。原始 `voice_raw`
SHA-256 仍为
`25725cff2b738bee8d66514dc5fbde51e04cf1a6b5e74c490e52025de4b4d48c`。
该试听现已通过，当前无需启动 BS-Roformer、GAME、训练、融合或自动模型晋级；
下一步只处理实际软件问题。

## 项目目标与硬边界

- 产品目标：把完整歌曲转换为可编辑的主旋律及多轨 MIDI/MusicXML。
- JSONL canonical events 是事实来源；MIDI 和 MusicXML 是导出物。
- performance timing 与 score timing 必须分开，量化结果不能覆盖原始时值。
- Mac 负责前端、编排、轻量验证、统计和试听渲染。
- Hyak Slurm compute node 仍是模型推理的默认和已验证路线。本机 MuScriptor
  MPS/CPU 是用户主动选择的可选路线；其代码与状态机已验证，但尚未做真实歌曲
  的端到端运行、速度或质量验证。
- `klone-login` 只用于登录、传输、查看状态和提交作业，禁止在登录节点跑模型。
- 每个第三方模型必须使用独立的 `workers/<name>/` 环境。
- 原始音频、stem、模型权重、私有转录、凭据和授权记录不得提交到 Git。

## 仓库位置

本地根目录不要写死，使用：

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
```

Hyak 使用持久化 group storage：

```bash
export HYAK_AMT_ROOT="/mmfs1/gscratch/stf/$USER/amt-studio"
export HYAK_REPO="$HYAK_AMT_ROOT/repo"
export HYAK_PROJECT="$HYAK_AMT_ROOT/projects/private/glass-kiss"
```

登录命令：

```bash
ssh "$UW_NETID@klone.hyak.uw.edu"
```

Duo 必须由项目所有者在手机上确认。密码、token 和 Duo 信息不得写进仓库、
脚本、日志或本交接文件。SSH 会话会过期，因此“上次登录成功”不等于以后持续在线。
应用使用的 NetID/主机和持久化根目录保存在本地忽略文件
`configs/local_hyak.json`；仓库只提交不含个人信息的
`configs/hyak.example.json`。换账号时复制示例并修改本地文件即可。

## Task 009 Mac 编辑器

源码与启动方式：

```bash
make mac-app
open -n "apps/AMTStudioMac/dist/AMT Studio.app"
```

当前编辑器会：

- 默认把新歌曲提交到 Hyak，也可在顶部或侧栏明确切换为本机 Apple GPU 或
  本机 CPU；有活动任务时禁止换后端，避免同一首歌重复提交；
- 本机模式开始前可以检查 MuScriptor 环境、固定模型来源、ffmpeg 和 MPS
  可用性；任务在独立低优先级进程中运行，关闭窗口不会主动终止，也可以在
  任务页确认后停止；
- 默认使用石墨灰、青绿与少量荧光绿的“精密模式”，并可在右上角设置中切换
  午夜蓝、青色与紫色的“炫酷模式”；选择会本地保存，但不影响项目或模型；
- 在真实运行任务中用五个明确阶段显示上传/排队、整曲识别、检查缺口、自动
  补漏和打包结果，不显示无法证实的百分比或预计时间；
- 把顶部操作收敛为七个入口；`项目` 统一包含打开、Finder 显示和保存，
  `导出` 第一项明确是“整个识别版本（完整多轨 MIDI）”；
- 通过 LaunchServices 打开本地登录脚本来建立不保存密码的 Hyak SSH 控制连接，
  不再使用 AppleScript 控制 Terminal；
- 清楚显示 `未检查/检查中/已连接/需要重新登录`；登录过期时远端 Slurm
  作业继续运行，通过密码和 Duo 后应用自动恢复同一任务而不重复提交；
- 在应用重启后优先恢复仍在运行的私有 Beta 项目；完成项目不会阻塞下一次识别；
- 在首页和侧栏列出本机已有歌曲，外部项目用 security-scoped bookmark
  记住权限，不必每次重新选择文件夹；
- 选择 MP3/WAV/M4A/FLAC，在 Mac 做轻量 canonicalize/传输后提交 Hyak L40；
- 每 20 秒查询一次真实 Slurm 状态，并显示整曲识别、缺口规划、自动补漏和
  打包阶段；完成后自动取回并打开项目；
- 在同一个 Slurm 作业中先保留整曲原始多轨，再对至少八秒的 `voice` 疑似长
  缺口运行有界同模型补漏；失败时回退为原始多轨，不要求重新上传；
- 打开并校验已有 `manifest.json` 和 canonical bundle；
- 对多个 bundle 和候选轨要求明确选择，不使用隐式 `latest`；
- 对新 MuScriptor 多轨默认打开 `voice_auto_enhanced` Beta 主旋律，同时保留
  原始主唱、仅补漏候选和所有伴奏轨；
- 标出 `voice` 内至少三秒的长空缺并可一键跳转，同时列出该时间段其他预测轨
  的候选音符数量；不会未经确认把伴奏自动复制到主旋律；
- 默认同步播放原曲和全部预测 MIDI 轨，也可切为只听当前编辑音轨；
- 分别调整原曲音量和 MIDI 总音量，避免钢琴预览被原曲掩盖；
- 每条轨显示音符数，并提供 M 静音、S 独奏和 MIDI 音量；这些设置重启后保留；
- 用鼠标拖动音符、拖左右把手调整长度，并支持撤销/重做；
- 将选择写入 `app/workspace.json`，将非破坏性编辑历史写入
  `annotations/corrections/`，不覆盖原始 candidate JSONL；
- 顶部和侧栏都直接提供 `导出整版 MIDI`：它导出当前明确选择的识别版本，
  包含全部伴奏轨和一条当前推荐主旋律；`其他导出` 再提供当前编辑音轨和按
  M/S/音量生效的当前混音，诊断版本仍保留在项目 JSONL 中；
- 从已校验 canonical 音频异步生成真实波形，不再用音符密度冒充波形；
- 让真实波形和钢琴卷帘音符跟随当前主题色，而不是保留系统默认蓝色；
- 默认用纵向逐行总览同时显示全部产品音轨的真实音符分布、音符数和共享播放头；
  点选任意一行后可切到“当前音轨”继续使用原来的拖动、改长度和检查器编辑；
  原始/仅补漏诊断轨仍受现有高级开关控制，避免默认重复显示主旋律版本；
- 按当前候选轨提供的原始置信度筛选并逐个定位待复核音符；没有置信度的音符
  保持未知，不会误判为低置信度。

界面性能边界也已改变：完整项目、bundle/track 切换和 MIDI 预览在后台准备，
钢琴卷帘按十秒懒加载，播放游标只刷新需要动画的子视图；点选音轨不再重复解码
同一 FLAC，也不再把数千音符重复写回编辑历史。release 构建在本机存在开发者
证书时使用稳定的 Apple Development 签名，减少每次重建都被 macOS 当作新应用
重新询问权限的概率；系统首次文件访问或 Duo 仍必须由所有者批准。最终
`make check` 通过 257 项 Python 和 27 项 Swift 测试；新的九轨自动产品包也
通过真实项目加载与所选轨 MIDI 导出。聚焦 P0/P1 的代码检查修复了折叠诊断
版本后隐藏轨仍可能继续播放的问题，未发现剩余阻塞问题。最新版已用本机
Apple Development 身份签名、严格校验并打开真实新歌项目。

Task 002 的旧结果可无推理地拆为 9 条预测乐器轨并保留全部 7,667 个音符。
新的真实端到端 Job `37734361` 在 L40 compute node `g3098` 上用时 `00:17:28`，
完成 `0:0`，取回 13 条预测乐器轨和 6,881 个音符；默认 `voice` 有 469 个音符。
完整多轨 MIDI 为 14 个 track（含 conductor），有 12 个 General MIDI program
change，1,545 个鼓音全部位于 percussion channel。模型原始 JSONL 不会被修改；
人工调整只改变当前项目和重新导出的 MIDI，并不会自动训练或改变 MuScriptor。

同一 canonical 音频、模型权重、beam 4 和 prelude 配置在旧 A100 Task 002 与本次
L40 运行间产生了不同的事件数/标签数，因此不宣称跨硬件字节一致；私有 Beta
固定使用当前 L40 路线，不为这个差异重复跑模型。

所有者从应用上传的 `STILL LOVE HER` 真实 Job `37735878` 已在 L40 compute
node `g3096` 完成，耗时 `00:24:50`、退出码 `0:0`。生产状态接口已取回并校验
7 条预测乐器轨、10,989 个音符，其中默认 `voice` 为 254 个；完整便利 MIDI
含 conductor 共 8 轨、6 个 program change，并有 2,115 个 percussion
note-on。真实 Swift 项目加载及当前轨/完整多轨导出集成测试通过；当前 Hyak
队列为空，ControlMaster 仍在线。

所有者试听认为这首歌的伴奏总体不错，`voice` 中实际出现的旋律音高也大多正确，
但存在大段漏识别。对 canonical 事件的确定性检查证实：349.85 秒时间线上有
四个至少三秒的 `voice` 空缺，分别为 `0.00–33.35`、`63.55–90.69`、
`104.52–131.41` 和 `195.14–349.85`，合计 `242.09` 秒。这个结果说明当前
主要问题是主唱候选的时间覆盖/召回不足，而不是应把已检出的音符全部推翻。
其他轨道在这些时段有音符只能作为排查入口，其中既可能有真实主旋律，也可能是
伴奏、误分类或幻觉；因此本轮只暴露并定位空缺，不自动拼接或修改模型原始输出。

收尾时唯一一次 `/review` 没有 P0，报告 5 个 P1；现已全部修复：Xcode 工程纳入
Hyak 后台源码、任务状态拒绝路径逃逸/身份错配、16 条以上预测轨不会导致
canonical bundle 丢失、远端运行绑定实际同步的 Git commit、个人 Hyak 信息移出
提交内容。3 个 P2 按“只修 P0/P1”的边界保留，不继续扩大。最终 `make check`
通过当前工作树的 247 项 Python 和 18 项 Swift 测试（2 项需要私有环境变量而
预期跳过）；其中 7 项 Python 测试来自保留但暂停的 Task 007D 未提交文件，
不属于本次 Task 009 commit。

旧 `glass-kiss` 项目的三个 bundle、四条轨和 2,223 个音符均通过路径、大小和
SHA-256 校验。选择 GAME 后是 391 个音符、4:25 时间线；播放游标已实际推进。
导出的 391-note MIDI 已被 Mido 完整解析，并分别在 GarageBand 与 Logic Pro
中打开。普通 `swift test` 通过 16 项测试，其中私有集成测试按设计跳过；提供
明确私有项目/bundle/track 环境变量后该集成测试也通过。仓库级 `make check`
通过 216 项 Python 测试及整套 Swift 测试。

真实项目的四条 current canonical 轨均没有提供非空 confidence；因此 GAME
显示 `0 / 0` 并明确列出 391 个未知项，这是正确的缺失状态，不是“没有低置信度
错误”的质量结论。

`make mac-ui-test` 现在会用 Xcode 26.1.1 构建生产应用源码和正式 UI-test bundle。
测试在含中文和空格的临时路径生成三秒 WAV 与 canonical fixture，实际完成打开
项目、真实波形、播放推进、低置信度导航、音符编辑、撤销/重做以及退出重开后的
历史恢复；测试结束即删除 fixture，并通过 `--no-recent-project` 隔离用户的最近
项目偏好。私有 Beta 不采用被拒绝的 fusion，也不在 Mac 上运行 MuScriptor；
推理只允许由 `slurm/40_private_beta_muscriptor.slurm` 在 Hyak compute node
执行。今天不做 MusicXML、训练、新数据集或通用 model-pack 打包。

## 当前已验证结果

### Task 001：项目与音频入库

- 私有参考歌曲已成功入库。
- canonical mix 是确定性的 44.1 kHz stereo FLAC。
- 私有数据目录受 `.gitignore` 保护。

### Task 002：MuScriptor

- MuScriptor large 的完整歌曲基线已在 Hyak A100 上完成。
- 原生 JSONL、MIDI、规范化事件、命令、环境、模型哈希和输出哈希均保留。
- 固定片段的独立运行得到字节一致的原生 JSONL 和 MIDI。

### Task 003：音源分离

- 默认人声：`vocal_quality_a`，即 BS-Roformer。
- 多 stem 备用：`multistem_quality_a`，即 Demucs。
- 用户在三个片段中都选择 A；A 的人声更清楚，B 有明显伴奏泄露和回音。
- 该选择只是当前歌曲的听感选择，不是转录准确率证据。

### Task 004：主唱旋律候选

已保留四条同项目、同 canonical mix 谱系的候选：

1. GAME on selected vocal stem；
2. Basic Pitch on selected vocal stem；
3. MuScriptor voice on selected vocal stem；
4. MuScriptor voice directly on full mix。

结构统计和试听包没有进行融合、歌曲特调、质量排序或准确率宣称。

### Task 005：节拍图与 canonical events

- Beat This `1.1.0` 和官方 `final0` checkpoint 已固定版本与哈希。
- setup job `37621094` 与最终 baseline job `37621507` 都在 Hyak A40
  计算节点完成；Mac 没有运行模型。
- 最终 run 是
  `beat-this-task005-final0-d332b542-attempt-4`，包含 567 个 beat、
  143 个 downbeat 和 13,281 帧双通道原始 logits。
- `amt-worker-request/v1` / `amt-worker-result/v1` 已成为统一 worker
  合约；旧任务的不可变结果也通过同一读取接口。
- canonical bundle 保留四条独立候选轨，没有融合或排序。
- performance MIDI 保留原秒时间；score-grid JSONL 是单独的实验表示，
  不是正式乐谱。
- Mido `1.3.3` 已独立回读 2,223 个音符，最大 onset/offset 误差小于
  0.236 ms。
- Beat This 没有提供校准后的逐事件置信度，因此事件 confidence 保持
  `null`，tempo/meter 也明确标记为派生或推断结果。

## Task 004 试听包

试听目录：

```text
projects/private/glass-kiss/reviews/melody-task004-d332b542/passages/
```

每个 `passage-01/02/03` 中：

- `mix.wav`：原歌曲的 12 秒参照片段；
- `game-piano.wav`：GAME 候选转成的钢琴声；
- `basic_pitch-piano.wav`：Basic Pitch 候选转成的钢琴声；
- `muscriptor_stem-piano.wav`：MuScriptor 在选定人声 stem 上的结果；
- `muscriptor_direct-piano.wav`：MuScriptor 直接处理原混音的结果。

`candidates/*/piano-full.wav` 是整首钢琴预览，`candidate.mid` 是候选 MIDI。
`logs/` 和 `review_manifest.json` 是复现与完整性证据，不需要用户试听。

这次快速试听不是 Task 005 的阻塞条件。最终候选选择和准确率判断应等待 Task 006
的人工参考标注。

## 关键私有产物

以下路径全部位于 `projects/private/`，应继续保持 Git ignored：

```text
projects/private/glass-kiss/audio/canonical/mix.flac
projects/private/glass-kiss/runs/
projects/private/glass-kiss/reports/melody-task004-candidates-d332b542.json
projects/private/glass-kiss/reviews/melody-task004-d332b542/
projects/private/glass-kiss/runs/beat-this-task005-final0-d332b542-attempt-4/
projects/private/glass-kiss/exports/canonical-task005-d332b542/
projects/private/glass-kiss/logs/task005/
```

Task005 的公开证据在：

```text
tasks/005_BEAT_AND_CANONICAL_EVENTS.md
STATUS.md
CHANGELOG.md
configs/model_registry.yaml
docs/MODEL_EVALUATION_MATRIX.md
docs/adr/0004-versioned-worker-and-canonical-project-contract.md
```

## Task 006 当前状态

已实现：

```text
src/amt_core/benchmark.py
src/amt_core/evaluation.py
scripts/create_reference_pack.py
scripts/seal_reference_pack.py
scripts/evaluate_benchmark.py
scripts/freeze_evaluation_candidates.py
scripts/manage_seeded_reference.py
scripts/recover_muscriptor_normalization.py
scripts/create_annotation_topline.py
docs/EVALUATION.md
```

私有开发标注包：

```text
projects/private/<development-project>/annotations/reference-task006-development-v1/
```

它冻结了六个 12 秒 evaluation window，SHA-256 为
`ec7e6895b36686212da8cbec5e86bee9007f0d733f5b433cdfe56111a02f6838`。
每段两侧包含最多一秒上下文；所有者已确认六类覆盖基本正确，GAME 候选已作为
待确认种子写入，但不能在试听确认前声明为人工真值。

私有 blind 标注包：

```text
projects/private/<blind-project>/annotations/reference-task006-blind-v1/
```

它来自此前未参与开发的不同艺人歌曲，六个 12 秒窗口在任何该曲模型任务提交前
冻结，SHA-256 为
`e235a1faa04990bb53c3d976bfb6bb9241411beae4cc198328eaece747a8e5ee`。
Separator、Beat This、GAME、Basic Pitch、声部 MuScriptor 和整曲 MuScriptor
均在 Hyak 计算节点运行。整曲 MuScriptor 的 8,270 个原生音符中有一个精确
零时长事件，恢复流程保留并校验原始推理、将该事件写入拒收证据，并生成 8,269
个有效音符，未重新运行模型。

所有者已基本确认 blind 包六类覆盖，并给出逐段试听意见：`blind-01` 主观上约
90% 正确；`blind-02`、`blind-04`、`blind-06` 仍有漏音、错音、过短或黏连；
`blind-05` 仍较乱。这里的 90% 不是计算得到的准确率。下一步需要依据这些意见
修正音符，再由所有者确认；不能由模型把自己的候选输出直接声明为人工真值。

针对 `blind-05`，反馈后的标注辅助作业 `37627351` 已在 Hyak A40 节点完成。
它只转录 Demucs `other` 轨的失真电吉他候选，在模型输入前排除了鼓、贝斯和
人声。新提案有 59 个音符，结构上消除了旧提案中 8 次超过一个八度的突跳，
但所有者试听确认所用 SoundFont 不是可辨认的原声钢琴音色，并且无法听出原曲
调子。因此该路线已拒绝，不会只换音色后继续使用。该提案产生于 blind 反馈
之后，明确不计入 primary blind metrics。

试听导出器现会在渲染前读取 SoundFont 的 bank 0/program 0 名称，只有确认是
原声钢琴才继续；同时必须匹配已批准的 GeneralUser GS 文件 SHA-256。此前实际
为 `FM Bells 1` 的配置以及 `FM Piano`、`Rhodes Piano` 等名称会被直接拒绝。
该修复只保证评审音色可信，不会把错误的最高音提案包装成正确主旋律。

随后在 Hyak 运行的六轨吉他标注辅助实验也已拒绝：三种预先声明的 pYIN 设置都
得到 0 个可接受音符；MuScriptor 在 `blind-05` 的 77 个起音组中有 40 个是
多音组，最大同时 5 个音，证明该轨仍混有节奏和弦。没有生成新的试听包，也
没有降低阈值或再次套用“取最高音”。

评测器现在还要求：seed 必须来自 hash 验证过的 worker 输出，candidate-corrected
seal 必须不可变地绑定 seed 和 review 记录；blind metrics 必须先有
`candidate_set_seal.json`，且候选集合在查看输出质量前冻结。当前 blind 输出
已经看过，不能事后补一个 seal 再冒充正式 blind 结果。

Seed 的序列化哈希和音符语义指纹都会被排除。语义指纹只覆盖冻结评测窗口以及
实际计分的 onset、offset、pitch、instrument，因此改 run ID、量化字段、窗口外
音符或重新规范化都不能绕过自我评分排除。无置信度候选不会再产生误导的阈值
0 分；配对使用全局最小成本最大匹配；高一致性子集会遮蔽已匹配的歧义参考音符。
跨片段边界的长音只有在 offset 确实等于上下文边界时才能使用
`offset_censored`，只评 onset/pitch，不会因上下文裁剪被误判 offset。

已执行聚焦 `/review`；最后五项 P1/P2 完整性问题均已修复并增加回归测试。
最终 `make check` 通过 140 项测试；脚本/worker 编译、schema JSON、从仓库外
启动候选冻结 CLI 和 `git diff --check` 也通过。

人工签封和 baseline metrics 完成前不要创建 Task006 commit，也不要进入 Task007。

为替换已经失去正式 blind 资格的旧输出，新建了公开代号 `blind-song-c` 的私有
项目。六个原曲片段已在任何模型提交前冻结，benchmark SHA-256 是
`f4e1736c833eb0cc427f17d9bb0f99dae7d5211dfe737bd013f9aa78718539f0`。
Separator 路线与四个主旋律候选标签也已在看输出前写入私有 candidate plan。
先前的多作业链都在未启动时取消，模型和 run ID 未改变。当前唯一正式作业
`37637038` 使用一张 checkpoint A40，在同一个 allocation 内依次运行 separator、
Beat This、GAME、Basic Pitch、MuScriptor，最后自动执行
`scripts/freeze_evaluation_candidates.py`。pipeline 脚本和 candidate plan 均已
记录 SHA-256。在该作业和 `candidate_set_seal.json` 成功前没有查看候选音符、
统计质量或生成模型试听。

该等待现已结束：job `37637038` 在 checkpoint A40 上以 `0:0` 完成，总耗时
`00:25:07`。自动生成的 candidate-set SHA-256 是
`02f37949ffe92824cb6b793181f491562c3cd66622f7e2f9d7f727bd53763296`。
八个 worker run、comparison report、seal 和 Slurm 日志已同步回 Mac，所有
manifest 输出均重新计算大小与 SHA-256 并通过。

在查看质量前已固定 GAME 为唯一 candidate-corrected 标注 seed，并永久排除其
primary metrics。新的 `scripts/create_task006_seed_review.py` 只渲染原曲与这个
固定 seed，强制绑定 benchmark、seed policy、candidate seal、worker hashes 和
已批准的 `Grand Piano` SoundFont。六段试听包已经生成并验签：

```text
projects/private/<blind-song-c-project>/
  reviews/reference-task006-blind-v1-seed-v1/passages/
```

每个 `blind-01` 至 `blind-06` 文件夹只有 `mix.wav` 和 `seed-piano.wav`。所有者
反馈已经作为非专业、主观的 annotation guidance 私下保存；这些 provisional
notes 没有被冒充为人工真值，也没有生成私有歌曲的正式准确率。评测器支持并明确
记录“密封集合减去精确 hash 绑定 seed”，不会把 GAME 与自己的修正版参考做
自我评分；逐音修正版现在也可通过独立 corrected-reference 和 correction-session
验签后写入并签封。

第一轮所有者反馈把 `blind-02`、`blind-03`、`blind-04` 分别描述为主观约
95%、90%、80% 正确，但同时明确听到剩余错音、杂乱或漏音，因此这些百分比仅是
试听印象，不能当作实测准确率或 reference 签字。`blind-05` 与 `blind-06` 被
描述为伴奏/间奏而非单轨主旋律，其中 seed 音符可能是假阳性；由于所有者明确说明
自己不是专业标注者，该空 reference 解释仍需一次明确确认。原始中文反馈和保守的
错误分类已写入私有、Git 忽略的证据文件，provisional notes 没有被静默修改。

为辅助第 2–4 段的精确修正，Hyak checkpoint CPU job `37650151` 在已验 lineage
的人声 stem 上运行固定 pYIN 配置，以 `0:0` 完成，用时
`00:02:54`。同步回 Mac 后 12 个声明输出全部通过大小和 SHA-256 复核；第 2–4
段分别提出 22、22、17 个音符，并使用已批准的 `Grand Piano` 生成窄范围试听包：

```text
projects/private/<blind-song-c-project>/
  reviews/reference-task006-blind-v1-pyin-vocal-a-v1/passages/
```

该 pYIN 路线只用于 annotation aid，不能作为 blind candidate 评分；它没有读取
或暴露另外三条密封候选。所有者最终在第 2–4 段都保留 GAME seed，并明确认为
pYIN 断断续续、无法使用，因此该路线已经关闭，不再复听、调阈值或重跑。第 5/6
段的少量 pYIN 检出也不会推翻所有者的伴奏分类。

`blind-04` 另有一次私有乐谱引导修正。所有者明确了六页原谱中的第 3 页，也就是
三页合并 PDF 第 2 页左半边；目标是第 2 行整行接第 3 行开头。Codex 只转录右手
最上方旋律，用已有 Beat This 小节起点
`180.78 / 182.84 / 184.88 / 186.94 / 188.98 s` 对齐，并按原唱音区下移一个
八度。结果为 22 个音符，旧的 23-note GAME seed 保留不改，便于审计：

```text
projects/private/<blind-song-c-project>/
  annotations/reference-task006-blind-v1/score-guided/blind-04-v1/
```

目录中包含逐音 JSONL、逐小节转录、来源哈希、乐谱裁图、MIDI、纯钢琴、
原曲叠加钢琴和先原曲后钢琴试听。该 PDF/截图为用户私下提供，来源版权状态未
独立核实，因此不得提交或分发。此次是 Codex 代录，没有测量项目所有者的人工
修正用时，也没有签封为正式 reference；Gate 2 状态不变。所有者首次试听后把
该版主观估计为约 80% 正确，并指出仍有明显错音；该数值不是实测准确率，当前
22-note 版本已标记为 `needs_revision`，不能作为最终 reference。

随后复核确认根因是 V1 人工读谱位置错误，而不是 PDF 页码或乐谱来源错误：第 2
行后两个小节有 6 个音被看高了一个谱级。V2 不覆盖 V1，把错误的
`D-C-C-B♭ / E♭-C-E♭-D` 修为谱面的
`D-B♭-B♭-B♭ / D-B♭-D-C`。已有 Hyak 人声 pYIN 帧在八个对应区间的中位
MIDI 音高也独立支持 V2。V2 的 22 个音、MIDI 和三种试听均已通过结构与哈希
验证，位于同级 `blind-04-v2/`。所有者随后主观认为 V2 正确率在 95% 以上，并
接受其作为当前私有参考。该数值不是实测指标；V2 仍未正式签封，也没有人工计时
修正证据，因此 Gate 2 状态不变。

随后进行了计时审听。第一次因原曲掩蔽钢琴而明确作废；替代版本把钢琴置于压低
后的原曲前约 12 dB。所有者完整播放 1 遍并在 41 秒墙钟时间内回复“通过，1遍”。
从 V1 问题反馈到 V2 接受的助手辅助流程共 449 秒、修正 6 个音。这两个时间均有
哈希证据，但没有测量所有者直接逐音编辑时间，因此只能作为“助手修正 + 人工最终
审听”证据。按原 Gate 2 口径，当时仍未关闭；Task 007 的 ADR 0005 后来明确只
用该命名 workflow 授权融合研究，仍不宣称 direct-edit 效率。

## Task 006 正式评测

MedleyDB predominant-melody 帧级 benchmark：

- benchmark SHA-256：
  `854e3ac3cdf9a0a70867d9e51780e38635d50a07de8acf781a6132e546fb2a16`；
- candidate-set SHA-256：
  `f34359571dd3396197182c39f4c1c63dac6ae870ddbf49ec79bc6e384e4517c6`；
- A40 候选作业 `37690768` 与最终 CPU 评测作业 `37692231` 均为
  `COMPLETED 0:0`；
- 固定 50-cent tolerance 下，GAME 的 overall accuracy `0.7271`、raw pitch
  accuracy `0.6822`、voicing recall `0.9278`、voicing false alarm
  `0.2086`，四条路线中排名第一；
- 权威 `v3` report SHA-256：
  `e4407cce7728e0990d0b3070edb43464ba60228296fb80aeb210ef0bc287ea68`。

Vocadito 双标注者音符 benchmark：

- benchmark SHA-256：
  `1a50acb82e59c5a60a8904a86db1c0de3f84121aa871a6a4b5775ac1c246145c`；
- candidate-set SHA-256：
  `4de9e1495687a255bf3d8f5244cb31235b781db70d1fc852ffb297fa764a21e7`；
- A40 候选作业 `37691274` 与最终 CPU 评测作业 `37692232` 均为
  `COMPLETED 0:0`；
- GAME 的 macro per-track Amax onset+pitch F1 为 `0.7447`，
  onset+pitch+offset F1 为 `0.4758`；aggregate onset+pitch F1 对 A1/A2
  分别为 `0.5966`/`0.7379`，因此不能隐藏标注者差异；
- 权威 `v3` report SHA-256：
  `f38c2c0d31086418b40ef10e2a9c437c7c76d2771794176b5e9559e64e7a0d60`。

两个 report 都在发布前重验全部输入快照，并在 Mac 同步后按 run manifest 重新
验证所有输出大小与 SHA-256。自动 note-object discrepancy 只表示粗略负担，不是
最少编辑动作或人工用时。

## Task 007 deterministic fusion

- ADR 0005 把本次可审计工作流明确拆为 assisted correction `449 s`、owner final
  review `41 s`/一次完整播放、direct owner note edit
  `unavailable_not_measured`；它只授权研究，不证明编辑器效率。
- ADR 0006 固定 deterministic main-melody fusion、development-only
  calibration、完整候选/拒收 provenance，以及先生成 fusion evaluation seal、
  再加载 blind reference 的顺序。
- Task 007 Vocadito development/blind 各六位 singer，彼此以及 Task 006 六位
  blind singer 均不重叠。A40 候选作业 `37705578`、开发校准 `37705582`、融合
  封存 `37706932`、正式评测 `37706934` 均为 `COMPLETED 0:0`。
- candidate-set SHA-256：
  `e2584762d81911d8685b45aecbbdf4949d1f4d9c2824289d9a6d6312ca6bb403`；
  fusion evaluation-seal payload SHA-256：
  `50181e0c74a22396b9d1fe2770c0750351f890dc17a2c6039332794cfa12f520`。
- GAME blind macro Amax onset+pitch/onset+pitch+offset F1 是
  `0.7797`/`0.4316`；fusion 是 `0.7410`/`0.4332`。后者只增加 `0.0016`，
  前者下降 `0.0387`，因此 frozen primary-metric rule 失败。
- confidence threshold `0.75` 时保留 `41/293` 个窗口内音符，precision
  `0.8556`、recall `0.1225`。完整 curve、四个 worker ablation、八个 feature
  ablation 均已保存；beat phase 因没有 beat 输入而是显式 no-op。
- fusion 与 GAME 的自动 discrepancy 同为 `85.3723/min`；没有 matched human
  correction time，也没有 multi-track reference。结论是明确拒绝 v1 trade-off，
  保留 GAME 为默认基线，Gate 4 不通过。
- 权威 report SHA-256：
  `8d529a72cdd9119f7eabf97cf64b6c4010c96d668de8a592a2a0cd896d0c5f75`。
  本地 ignored private-project 目录已同步 calibration、fusion、两个 seal 和
  evaluation；所有 manifest 输出与 11 个 sealed scoring-source hash 已重验。
- `make check` 通过 186 项测试；Ruff、Slurm `bash -n`、Task 007 JSON、
  compile 和 `git diff --check` 均通过。

## Task 007B Gate 4 恢复实验

- 新 split 在推理前固定：development 为
  `12/S9, 20/S15, 23/S18, 29/S23, 33/S26`，blind 为
  `19/S14, 21/S16, 22/S17, 26/S21, 30/S24, 32/S25`。11 位 singer
  与 Task 006/007 v1 均不重叠。
- 正式成功作业为准备 `37720512`、A40 候选 `37720513`、开发校准
  `37720514`、attempt-2 seal `37722126`、评测与自动判定 `37722127`；
  均为 `COMPLETED 0:0`。候选作业实际运行于 A40 节点 `g3046`。
- 官方 track 30 A1 最后一个音符比 PCM 边界长 `2.77 ms`。原 CSV 未改，
  freeze 与 scoring 都固定采用最多 `5 ms` 的边界量化容差；超过 `5 ms`
  仍拒绝。第一次 seal 被旧三候选下限阻塞后，旧默认仍保留为三，
  Task 007B 必须显式指定两候选。所有失败/取消尝试都只属于基础设施证据，
  没有用于改阈值或 blind 调参。
- candidate-set seal SHA-256：
  `3022a656447cab707a643fd7dfe496cf27e1fcce2d8d2715eeb16c7d868e0ab1`；
  attempt-2 fusion evaluation seal SHA-256：
  `351a176eebe7a07df71075a8ed26ac22e454d662c8111905d534cf86051d0ffe`。
- GAME blind onset+pitch/onset+pitch+offset F1 为
  `0.7814082068/0.3676085616`；fusion 为
  `0.6923501742/0.3276084961`，分别下降
  `0.0890580326/0.0400000655`。两条 frozen automatic gate 都失败。
- 权威 report SHA-256：
  `ea66e1b20b3739478a56b89a0c5e104af55b959de15007de7f34dbded507a1f7`；
  gate decision SHA-256：
  `4338127e5009589e2f336086d62b78a9b99be8630580ed380b671f8b238fd732`。
  决定为 `reject_v2_without_blind_retuning`，`gate4_passed=false`。
- 因自动前置门槛失败，不再让 owner 做 matched correction，避免浪费人工。
  Task 007B blind 结果不得调参。Task 009B2B 与 Task 010 继续阻塞；下一步
  是产品/数据策略决定，而不是继续消耗同一 Vocadito blind 集。
- Mac ignored 证据已同步至
  `projects/private/vocadito-task007b-{development,blind}-v2/`、
  `projects/private/task007b-logs/` 与
  `projects/private/task007b-data-logs/`，关键哈希与 Hyak 一致。

## Task 007C 器乐 full-mix 开发探针

- Phoenix `ScotchMorris` 只能作为
  `development_instrumental_melody`。六个 20 秒窗口只按曲长固定为
  `0/30/60/90/120/150` 秒；候选在读 Melody 1 评分前签封，但这个附加签封
  不会把 development 变成 blind。
- 唯一候选是 Basic Pitch `0.4.0` 默认解码直接处理 exact canonical mix。
  adapter 现在只允许 canonical mix 通过明确的 `direct_canonical_mix`
  lineage；输出标为未知乐器 `other`，既不冒充 voice，也不改变既有 separator
  vocal-stem 合约。
- 准备 `37732190`、候选 `37732191`、评测 `37732192` 均在 Hyak compute
  node 上 `COMPLETED 0:0`。候选产生 1,701 个事件；20,676 帧上的 raw pitch
  accuracy 为 `0.6932`、overall accuracy 为 `0.3339`、voicing false alarm
  为 `0.9648`，三个冻结条件全部失败。85.33% 的评分帧有多音重叠，最多同时
  7 个事件，说明伴奏泄露而不是稳定的单线主旋律。
- 自动决定是 `reject_direct_mix_instrumental_route_for_v1`。不得在 Phoenix
  上救援式调参，也不为这条失败路线采集新器乐 blind set。v1 研究范围收窄为
  lead-vocal main melody；Gate 4 仍不通过，Task 009B2B 与 Task 010 继续阻塞。
- benchmark freeze SHA-256：
  `e64a30cd6acdfe8064bace7a2872fe36e22056e45939ff07722a39db4ceda5b8`；
  candidate-set payload SHA-256：
  `cc5b7df33ba9bdc36b020b2461a68b1cdb98827527ff8f855c1f0b880ee168a9`；
  report SHA-256：
  `fbe730efde84b8f1cb70c5a81844c1573eca9a8a51cee468d23603525b90a7df`；
  hardened v2 decision SHA-256：
  `5bb86efc3ee236013b71147d1b54ceea76c3a5e76bd6f1455014dca41805aa13`。
  v2 判定会在读取 metrics 前重验 benchmark/candidate seals、candidate
  events/run manifest、evaluation run manifest、reference hash、50-cent
  容差和固定投影。
- ignored 私有证据与 Slurm logs 已同步至
  `projects/private/medleydb-phoenix-scotch-morris/`。完整
  `make check` 通过 230 项 Python 与 17 项 Swift 测试（1 项预期 private
  integration skip）。
- 唯一一次 `/review` 报告 2 个 P1 与 2 个 P2。两个 P1 已修复并有针对性
  回归：development reference 不能进入 blind split，automatic assessment
  不能再信任未认证的 report 数字。按收尾边界，prepare-pack reuse 与通用
  direct-mix/project-manifest binding 两个 P2 只记录、不扩展；没有重跑模型、
  scoring 或 smoke。
- 下一步只应定义 lead-vocal-only research MVP，并明确真正新的 accompanied
  vocal artist-disjoint blind/reference/correction data 条件；不得把 Task
  006/007/007B 已评分的 blind 输出改作调参集。

## 当前限制

- 私有歌曲仍只有未签封的 provisional reference；上面的正式指标只适用于
  MedleyDB/Vocadito 固定 benchmark，不能外推成私有歌曲准确率。
- direct owner note-edit time 与 matched baseline/fusion correction time
  仍未测量；不能把 assisted correction 或自动 discrepancy 当作直接编辑效率。
- Amax 是逐曲选择较有利标注者的乐观汇总，A1/A2 结果必须同时保留。
- 只有未改动的 full fusion 有 development-calibrated confidence；单 worker
  与所有 ablation 不得复用这个 calibrator。
- 没有人工 beat/downbeat 参考，因此当前 567/143 只是模型输出数量，不是
  节拍准确率。
- GAME 与 Basic Pitch 尚未单独测量独立运行重复性。
- Beat This 的 minimal post-processor 可产生不规则局部 beat/downbeat
  间隔；已保留原始 logits 和不确定性，尚未以参考标注评估。
- deterministic fusion 已实现但被 blind 结果拒绝；尚未实现正式 score
  quantization/MusicXML、训练或 Task 009B 的导入/后台推理/model-pack 集成。
  Task 009A 的既有项目 SwiftUI 编辑器已经可用。
- Task004 的试听 MIDI 只是审听材料；Task005 的 `performance.mid` 是四条
  未排序候选轨，`score-grid-experiment.jsonl` 也不是正式乐谱。

## Task 008 Hyak 批处理

- ADR 0007 固定了 `amt-batch-spec/v1`、冻结 manifest、可跨 manifest 复用的
  按内容寻址阶段缓存、persistent 完整输出归档和 scrubbed retention。
- 每一行都绑定 input/config/model、相关源码、code revision、阶段命令及输出
  SHA-256；Python 还绑定未解引用的 virtualenv 入口、解析后的解释器以及
  installed-package fingerprint。所有 Python entry point 都必须是冻结源码；
  发生变化就不能误用旧缓存。
- 三种提交 profile 是 `priority-l40s`、`checkpoint-a40`、`cpu-smoke`。前两者
  已通过 Hyak `sbatch --test-only`，没有为 smoke 占用 GPU。
- 最终 smoke manifest 是 `task008-smoke-v7`，SHA-256：
  `44c265b6f402798d4ed277fb2e7f94524747a432f5fac97f87061dc6f42de18d`。
  `37712191` 在计算节点 `n3467` 冻结 manifest，login node 没有做 artifact
  hashing；GPU test-only probe 是 `37712211` 与 `37712212`。
- 首轮数组 `37712213` 按设计中断一行、完成一行；第二轮 `37712227` 对中断行
  复用 prepare 后只完成 infer，对已完成行直接整行 cache hit。finalizer
  `37712215` 和 `37712230` 都是 `COMPLETED 0:0`。
- 最终 index 为 2/2 行完成；execution failure rate 是 `1/3`，cache-hit rate
  是 `1/4`。这次失败是刻意注入的续跑测试，不是生产模型失败率。
- 四个尝试记录与十个 stdout/stderr log 均以 append-only 方式保存在
  persistent index；中断产生的 unpublished `tmp/` 已清空，只保留 checkpoint。
  每行的 prepare 与 infer 声明输出都已持久化，`selected_outputs` 只负责标记
  重要子集。
- repository executable 与 Python runtime 均冻结并纳入 cache key；非
  `srun` active step 不能执行 row。retention 由 global/cache lock 串行化，
  跳过 active cache；terminal incomplete cache 只有在 attempt JSON/log 已
  持久化后才能淘汰，超预算时不再接收新的 unique cache。当前 shared root
  是 14 个目录、`117,938` bytes。
- Mac 的 ignored 证据位于
  `hyak-results/{manifests,indexes,selected,logs}/`。完整 scrubbed cache 不会
  同步回来；完整声明输出先复制到 persistent storage 并重验后，retention
  才允许清理 completed cache，且预算无法安全满足时会在任何删除前失败。
  array job ID 会在提交 finalizer 之前先落盘。Mac 可用
  `verify_source=False` 离线读取同步回来的冻结 manifest。
- 当前 Hyak 队列已清空。Task 009A 与不含推理的 Task 009B1 波形/待复核界面
  已完成；Task 009B2 的导入、后台任务和模型集成仍因 Gate 4 与 stable
  backend gate 阻塞。
- 最终只运行了一次 `/review`：它报告两个 P1 和一个 P2。两个 P1 已通过
  `amt-batch-execution/v2` 修复：stage 只读取 cache 内不可变的
  input/config/model/code snapshot，不再继承任意 shell/Slurm 环境；显式
  stage environment 仍可使用且会进入 cache key。对应回归测试已加入。
- 按停止指令没有处理 P2 的 cache root 顶层散落普通文件计费边缘情况，也
  没有再跑 smoke。v7 仍是 scheduler/resume/cache/finalizer/retention 的
  权威 Hyak 证据，但早于最后的 v2 本地加固；最终 `make check` 通过 216
  项测试。不要把 v7 的源码 hash 误写成最终提交后的源码 hash。

## 快速健康检查

本地：

```bash
make check
git status --short
git log -1 --oneline
```

Hyak 登录后只做轻量检查：

```bash
hostname
test -d "$HYAK_REPO"
squeue -u "$USER"
```

模型工作必须通过 `sbatch slurm/<job>.slurm` 或 compute-node 交互分配运行。
