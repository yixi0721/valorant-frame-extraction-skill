# valorant-frame-extraction-skill

无畏契约击杀抽帧 Codex Skill。导入自己的第一视角录像后，自动识别本人击杀，压缩击杀附近的连续射击画面，并导出 MP4。

抽帧会删去可压缩的一段画面，保留开枪起始和击杀反馈附近的动作。识别与导出均在本地完成，无需在线 API 或桌面 GUI。

## 适用录像

使用 **16:9、完整标准 HUD、自己的第一视角录像**。当前识别器依赖右上角击杀记录和弹药显示；观战、裁切 HUD、超宽屏或遮挡这些区域的录像需要额外适配。

- 自动识别本人的击杀，生成时间点、缩略图和可编辑的抽帧方案。
- 支持自然、利落两种模式，以及逐次撤销、启用和按帧调整。
- 默认导出原分辨率的 H.264 / AAC MP4，也可生成最高 720p 的预览。
- 视频与第一条音轨同步裁剪，原始录像保持不变。

## 在 Codex 中使用

将下面的请求交给 Codex：

```text
请用 $skill-installer 安装 https://github.com/yixi0721/valorant-frame-extraction-skill
仓库根目录中的 skill，名称为 valorant-frame-extraction-skill。
```

安装后在下一轮对话中调用，例如：

```text
$valorant-frame-extraction-skill
处理 E:\Videos\match.mp4。这是自己的第一视角录像，保留完整 HUD。
使用自然模式，导出到 E:\Videos\match-output。
```

Agent 的处理流程与结果核对要求见 [SKILL.md](SKILL.md)。

## 直接运行命令行

需要 Python 3.12+、FFmpeg 和 ffprobe。FFmpeg / ffprobe 应在 PATH 中，FFmpeg 需包含 libx264 编码器；NumPy 与 OpenCV 使用仓库中的依赖版本。

以下为 Windows PowerShell 示例。虚拟环境和录像放在个人视频工作区，skill 代码单独存放：

```powershell
git clone https://github.com/yixi0721/valorant-frame-extraction-skill.git
$skillDir = (Resolve-Path '.\valorant-frame-extraction-skill').Path
$workspace = Join-Path $env:USERPROFILE 'Videos\valorant'

python -m venv (Join-Path $workspace '.venv-chouzhen')
$pythonExe = Join-Path $workspace '.venv-chouzhen\Scripts\python.exe'
$cli = Join-Path $skillDir 'scripts\chouzhen.py'
& $pythonExe -m pip install -r (Join-Path $skillDir 'scripts\requirements.txt')
& $pythonExe $cli check
```

检查返回 `ready: true` 后，将录像放到工作区并命名为 `input.mp4`，执行：

```powershell
& $pythonExe $cli run (Join-Path $workspace 'input.mp4') --preset natural
```

默认在录像旁的 `chouzhen-output/` 下新建带时间戳的任务目录，包含 `result.mp4`、`analysis.json`、击杀缩略图和 FFmpeg 日志。命令返回的 JSON 中提供实际路径。

| 模式 | 参数 | 每次击杀最多压缩 |
| --- | --- | --- |
| 自然（默认） | `--preset natural` | 0.25 秒 |
| 利落 | `--preset snappy` | 0.60 秒 |

实际删帧受可剪区间限制。短连射或没有可靠射击起点的击杀会保留原动作，因此识别到的击杀数可能大于实际抽帧数。

## 调整结果

只生成分析方案时，将 `run` 改为 `analyze`；生成预览时，在 `run` 后加 `--preview`。指定输出目录可使用 `--output-dir`，该目录必须是新目录或空目录。

已有方案可直接修改和重新导出，无需再次识别。沿用上面的 PowerShell 变量，把 `$analysis` 换成本次生成的方案路径：

```powershell
$analysis = 'E:\Videos\match-output\analysis.json'
$edited = Join-Path (Split-Path $analysis) 'undo-2.json'
$output = Join-Path (Split-Path $analysis) 'undo-2.mp4'

& $pythonExe $cli edit $analysis --disable 2 --output $edited
& $pythonExe $cli render $edited --output $output
```

`2` 是方案中的击杀 ID。导出文件已存在时默认报错；有意替换时使用 `--overwrite`。更多帧数调整、字段与返回值说明见[运行与调整](references/workflow.md)。

## 结果核对与开发

通过缩略图和对应的源视频片段核对识别结果。击杀时间表示 HUD 记录出现的时间，匹配分数也不能作为识别准确率。

混在第一条音轨中的语音会随视频一起裁剪。当前功能围绕击杀附近的连射压缩，不包含人声分离、自动切刀、BGM 卡点或瞄准轨迹重构。

- [引擎与验证](references/engine.md)：模块职责、测试命令、已验证样片与适配范围。
- [CLI 入口](scripts/chouzhen.py)：`check`、`run`、`analyze`、`edit`、`render`。
- [测试目录](scripts/tests)：检测、剪辑方案、导出与命令行行为。
