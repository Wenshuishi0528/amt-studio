# AMT Studio 项目交接

最后更新：2026-07-24

## 一句话状态

Task 001–005 已完成，Gate 1 已通过；Task 006 现在可以开始。Gate 2
尚未通过，因为还没有冻结的人工参考音符和盲测指标。

Task 005 是当前最终任务提交（用 `git log -1 --oneline` 查看）。当前开发分支是
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

## 如何开始 Task 006

先阅读：

```text
AGENTS.md
00_START_HERE.md
docs/PROJECT_SPEC.md
docs/ARCHITECTURE.md
docs/DECISIONS.md
tasks/005_BEAT_AND_CANONICAL_EVENTS.md
tasks/006_REFERENCE_ANNOTATION_AND_EVAL.md
```

Task 006 的边界：

- 先固定并哈希 benchmark 片段，再查看或调参；
- 优先标注人工确认的主旋律 note reference；
- 单独记录歧义、标注者置信度、octave error 和修正成本；
- 每个 metric 写清 onset/offset/pitch tolerance；
- blind-test 不能用于调参；
- beat/downbeat、四条旋律候选和 score-grid 都只能依据参考标注评估；
- Gate 2 通过前不能进入 Task 007 融合。

开始实现时把 `tasks/006_REFERENCE_ANNOTATION_AND_EVAL.md` 的状态改为
`in progress`。Task 完成前运行：

```bash
make check
git diff --check
git status --short
```

更新 `STATUS.md`、Task006 Evidence 和本 `CHANGELOG.md`，执行一次聚焦代码
审查，并为 Task006 创建一个独立 Git commit。

## 当前限制

- 没有人工参考音符，因此没有 note/melody precision、recall 或 F1。
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
