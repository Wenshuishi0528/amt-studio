# Known Issues and Current Product Reality / 已知问题与当前产品实际状态

## English

### What this project is

AMT Studio converts a song into structured note events and MIDI tracks using
pretrained automatic music transcription models. During the current research
phase, large model inference runs on the University of Washington Hyak cluster.
The Mac application is intended to handle import, job progress, playback,
editing, project persistence, and export.

The repository is not yet a finished one-click consumer application. The
existing macOS editor can open and edit previously generated canonical
projects, but the complete `import song -> run model -> retrieve result -> open
project` flow is still unfinished.

### Task 002 multi-track result

MuScriptor's Task 002 full-song result is the most important current
multi-track baseline. It produced separate tracks labeled as acoustic piano,
electric guitar, electric bass, voice, drums, electric piano, flutes, acoustic
guitar, and other instruments.

The project owner's latest listening observation is:

- the main vocal melody is generally recognized in one `voice` track rather
  than being scattered across multiple MIDI tracks;
- the main melody and many overall notes are subjectively useful;
- some sparse accompaniment events are genuine musical embellishments;
- some accompaniment events appear to be instrument misclassification or
  hallucinated notes;
- some accompaniment notes may be missing or assigned to the wrong track;
- the displayed bass `+12` octave treatment is acceptable and is not currently
  considered a defect.

These are subjective listening observations from private material. They are
not a measured accuracy percentage and must not be presented as a formal
benchmark result.

### Why manual correction does not immediately improve the model

Editing a wrong note currently changes the corrected MIDI for that project. It
does **not** automatically update MuScriptor or make the next song more
accurate.

Manual corrections can become useful training data, but future output changes
only after an explicit learning step such as:

- fine-tuning a model;
- training a smaller correction, reranking, or instrument-reclassification
  model;
- implementing and validating a deterministic post-processing rule.

A small number of corrections from one song can easily overfit that song.
Corrections should therefore be stored with provenance and used for training
only after a sufficiently varied corpus and a separate blind test set exist.

### Current model and product limitations

- Multi-track instrument identity is not fully reliable.
- Correct notes may appear under the wrong instrument label.
- Weak accompaniment notes may be omitted.
- Spurious or hallucinated accompaniment notes may be emitted.
- A visually sparse track is not automatically an error; the original
  arrangement may contain only a brief instrumental embellishment.
- Source separation can introduce leakage, echo, or missing content.
- Vocal fusion experiments did not reliably beat the strongest GAME baseline
  on sealed blind evidence.
- A direct full-mix instrumental-melody probe was rejected because of pervasive
  accompaniment output and high voicing false alarm.
- The application does not yet provide a finished automatic Hyak-backed import
  workflow for ordinary users.
- The final Mac product must eventually run without requiring a live Hyak
  account, but that local model packaging work is not complete.

### Current recommended direction

The near-term product should prioritize a usable end-to-end workflow around the
existing MuScriptor full-song baseline:

1. import a song;
2. run the pinned model reproducibly;
3. preserve every raw multi-track result;
4. use the `voice` track as the initial main-melody track when appropriate;
5. let the user audition, relabel, correct, and export tracks;
6. save corrections without silently changing the original model output.

New datasets, fusion experiments, and model training should not delay this
basic product workflow. A learned correction model can be added later when
enough diverse, opt-in corrections exist.

### Privacy, data, and licensing

The public repository intentionally excludes private audio, datasets, model
weights, credentials, cluster logs, and private generated transcriptions.
Third-party models and datasets retain their own license restrictions. No
open-source license has been selected for the project owner's original code;
the public source is currently all rights reserved.

---

## 中文

### 这个项目是什么

AMT Studio 使用已经训练好的自动音乐识别模型，把歌曲转换为结构化音符和多轨
MIDI。当前研究阶段的大模型推理运行在华盛顿大学 Hyak 集群上；Mac 软件计划负责
歌曲导入、任务进度、试听、修改、项目保存和导出。

本仓库目前还不是普通用户可以一键使用的完整软件。现有 macOS 编辑器可以打开、
试听、修改、重新打开和导出已经生成的 canonical 项目，但是完整的
“导入歌曲 → 运行模型 → 取回结果 → 自动打开项目”流程还没有彻底完成。

### Task 002 多轨结果

MuScriptor 的 Task 002 整曲结果是目前最重要的多轨基础。它输出了标记为原声钢琴、
电吉他、电贝司、人声、鼓、电钢琴、长笛、原声吉他以及其他乐器的独立轨道。

项目所有者重新试听后的最新判断是：

- 人声主旋律通常集中在一条 `voice` 轨道里，并没有明显分散到多个 MIDI 轨道；
- 主旋律和整体大量音符在主观试听上已经具有较高可用性；
- 部分稀疏的伴奏音符确实是原曲中的短暂乐器点缀；
- 部分伴奏音符可能属于乐器误分类或模型幻觉；
- 某些伴奏音符可能漏识别，或者被分配到了错误轨道；
- 贝司显示的 `+12` 八度处理可以接受，目前不认为是缺陷。

以上内容来自对私有测试歌曲的主观试听，不是经过定义和测量的准确率，不能作为
正式 benchmark 结果宣传。

### 为什么人工修改不会立刻让模型变准

现在修改一个错误音符，只会改变当前项目的修正版 MIDI，**不会**自动更新
MuScriptor，也不会让下一首歌曲自动识别得更准确。

人工修正可以成为未来的训练数据，但只有明确执行以下学习步骤，后续输出才会改变：

- 微调模型；
- 训练较小的纠错、重排序或乐器重新分类模型；
- 编写并验证确定性的后处理规则。

只用一首歌的少量修正训练，很容易只记住这一首歌。因此，修正记录应当保留完整
来源；只有积累足够多样的数据并保留独立盲测集后，才适合用于训练。

### 当前模型和产品的已知限制

- 多轨乐器身份并不完全可靠。
- 音符本身可能正确，但被放进错误的乐器轨道。
- 较弱的伴奏音符可能漏识别。
- 模型可能生成原曲中不存在的伴奏音符。
- 轨道看起来稀疏不一定代表错误，原曲可能本来只有短暂的乐器点缀。
- 音源分离可能产生伴奏泄露、回音或内容损失。
- 已完成的主唱融合实验没有在封存盲测中稳定超过最强 GAME 基线。
- 直接从完整混音提取器乐主旋律的实验，因为伴奏输出过多和较高的发声误报而被拒绝。
- 软件还没有完成面向普通用户的 Hyak 自动导入和后台推理流程。
- 最终 Mac 产品不应依赖实时 Hyak 账号，但本地模型打包工作尚未完成。

### 当前推荐方向

近期应该围绕现有 MuScriptor 整曲基线，优先完成真正可用的端到端流程：

1. 导入歌曲；
2. 可复现地运行已固定版本的模型；
3. 完整保留所有原始多轨结果；
4. 在合适时把 `voice` 轨作为初始主旋律轨；
5. 允许用户试听、重新标记、修改和导出轨道；
6. 保存人工修正，但绝不偷偷覆盖模型原始输出。

新的数据集、融合实验和模型训练不应继续推迟这个基础产品流程。等积累足够多样、
明确授权的修正数据后，再考虑训练纠错模型。

### 隐私、数据与许可证

公开仓库明确排除私有音频、数据集、模型权重、账号凭据、集群日志和私有转录结果。
第三方模型和数据集继续受各自许可证约束。项目所有者的原创代码尚未选择开源许可证；
当前公开源码仍为保留所有权利。
