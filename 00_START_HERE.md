# AMT Studio 从这里开始

这是一个面向“完整歌曲到可编辑多轨 MIDI”的长期研究与产品工程骨架。它把工作分成两个相互独立、但共享数据格式的部分。

1. `research/worker` 层负责模型推理、评测、融合和训练。它可以在 Mac M4 或 Hyak GPU 上运行。
2. `app` 层最终负责本地 macOS 软件、试听、钢琴卷帘、低置信度提示和人工修正。

第一条硬性原则是：**所有模型先输出统一的 JSONL 音符事件，MIDI 只是导出格式。** 这样可以保留置信度、来源、候选音符和连续音高等 MIDI 无法完整表达的信息。

第二条硬性原则是：**每个第三方模型使用独立 worker 环境。** 不把 MuScriptor、GAME、Basic Pitch、音源分离和节拍模型强行装进同一个 Python 环境。核心工程只通过命令行和 JSON 文件与它们通信。

第三条硬性原则是：**主旋律是独立的一级输出。** 即使多轨转录失败，系统仍应尽最大可能生成 `main_melody.mid`。有主唱时默认主唱旋律；无人声时由候选主奏声部选择器决定，并允许用户手动指定乐器。

## 现在只做的第一件事

把本仓库放到 Mac，例如：

```bash
mkdir -p ~/Developer
cd ~/Developer
# 将下载的 AMT-Studio-Starter 文件夹放在这里，并改名为 amt-studio
cd amt-studio
```

把你的歌曲放进私有目录，不要提交到 Git：

```bash
mkdir -p data/private/inbox
cp "/你的路径/姫乃樹リカ - 硝子のキッス.mp3" data/private/inbox/
```

在 Codex 中打开整个仓库，然后复制 `CODEX_BOOTSTRAP_PROMPT.txt` 的全文给 Codex。不要在第一条指令中要求它完成整个软件。

## 任务顺序

Codex 应按 `tasks/` 中的编号逐个完成。每项任务都含验收条件。上一项未通过时，不进入下一项。

- `001`：Mac 环境、核心 CLI、歌曲入库、可复现清单
- `002`：MuScriptor 整曲多轨基线
- `003`：音源分离基线与质量比较
- `004`：主唱旋律多模型基线
- `005`：节拍、统一音符事件和导出
- `006`：人工参考标注与真实评测
- `007`：融合与置信度系统 v1
- `008`：Hyak 批量实验
- `009`：macOS 原生应用外壳
- `010`：训练纠错/重排序模型

先阅读：

- `AGENTS.md`
- `HANDOFF.md`
- `CHANGELOG.md`
- `docs/PROJECT_SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/QUALITY_GATES.md`
- `tasks/001_BOOTSTRAP_AND_INGEST.md`
