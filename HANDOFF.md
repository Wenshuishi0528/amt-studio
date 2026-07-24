# AMT Studio 项目交接

最后更新：2026-07-24

## 一句话状态

Task 001–004 已完成，Gate 1 已通过；Task 005 现在可以开始。Gate 2
尚未通过，因为还没有人工参考音符和盲测旋律指标。

Task 004 的基线提交是 `b706d84`。当前开发分支是 `main`。

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
```

Task004 的公开证据在：

```text
tasks/004_VOCAL_MELODY_BASELINE.md
STATUS.md
configs/model_registry.yaml
docs/MODEL_EVALUATION_MATRIX.md
```

## 如何开始 Task 005

先阅读：

```text
AGENTS.md
00_START_HERE.md
docs/PROJECT_SPEC.md
docs/ARCHITECTURE.md
docs/DECISIONS.md
tasks/005_BEAT_AND_CANONICAL_EVENTS.md
```

Task 005 的边界：

- 把 Beat This 放在独立 worker 环境中；
- 用 Slurm compute job 运行节拍/下拍模型；
- 保存原始 beat/downbeat 时间戳和不确定性；
- 统一 worker request/result manifest；
- 实现 canonical note、tempo、meter、track 和 provenance 模型；
- performance MIDI 必须保持原时间线；
- score-grid 实验必须作为独立派生表示；
- 至少用一个独立 MIDI parser 做 round-trip 测试；
- 不改变 Task 002–004 的任何原始模型输出。

开始实现时把 `tasks/005_BEAT_AND_CANONICAL_EVENTS.md` 的状态改为
`in progress`。Task 完成前运行：

```bash
make check
git diff --check
git status --short
```

更新 `STATUS.md`、Task005 Evidence 和本 `CHANGELOG.md`，执行一次聚焦代码
审查，并为 Task005 创建一个独立 Git commit。

## 当前限制

- 没有人工参考音符，因此没有 note/melody precision、recall 或 F1。
- GAME 与 Basic Pitch 尚未单独测量独立运行重复性。
- Beat This 尚未在本项目验证。
- 尚未实现 candidate fusion、正式 score quantization、训练或 SwiftUI 应用。
- Task004 的试听 MIDI 只是审听材料，不是 Task005 的正式 score export。

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
