# AMT Studio 项目交接

最后更新：2026-07-25

## 一句话状态

Task 001–006 已完成。两套专业标注 blind benchmark 已在候选输出前冻结并完成
正式帧级/音符级评测；GAME 是当前四条固定路线中最强基线。Gate 2 仍未完全通过，
唯一缺口是一次真实、计时的人工修正会话，不能用自动 proxy 冒充。

Task 006 是当前最终任务提交（用 `git log -1 --oneline` 查看）。当前开发分支是
`main`。

## 项目目标与硬边界

- 产品目标：把完整歌曲转换为可编辑的主旋律及多轨 MIDI/MusicXML。
- JSONL canonical events 是事实来源；MIDI 和 MusicXML 是导出物。
- performance timing 与 score timing 必须分开，量化结果不能覆盖原始时值。
- Mac 负责前端、编排、轻量验证、统计和试听渲染。
- 当前阶段的模型推理、音源分离、批处理和训练全部通过 Hyak Slurm
  compute node 运行。
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
验证，位于同级 `blind-04-v2/`，但状态仍是 `awaiting_owner_review`，未签封。

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

## 当前限制

- 私有歌曲仍只有未签封的 provisional reference；上面的正式指标只适用于
  MedleyDB/Vocadito 固定 benchmark，不能外推成私有歌曲准确率。
- 尚未进行真实、计时的人工修正会话，因此 Gate 2 不宣称通过，Task 007 暂不授权。
- Amax 是逐曲选择较有利标注者的乐观汇总，A1/A2 结果必须同时保留。
- 当前候选没有可校准的逐音置信度，precision/coverage 曲线保持 unavailable。
- 没有人工 beat/downbeat 参考，因此当前 567/143 只是模型输出数量，不是
  节拍准确率。
- GAME 与 Basic Pitch 尚未单独测量独立运行重复性。
- Beat This 的 minimal post-processor 可产生不规则局部 beat/downbeat
  间隔；已保留原始 logits 和不确定性，尚未以参考标注评估。
- 尚未实现 candidate fusion、正式 score quantization/MusicXML、训练或
  SwiftUI 应用。
- Task004 的试听 MIDI 只是审听材料；Task005 的 `performance.mid` 是四条
  未排序候选轨，`score-grid-experiment.jsonl` 也不是正式乐谱。

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
