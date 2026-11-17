# 运行与调整

## 运行环境

脚本只依赖 Python 3.12+、NumPy、OpenCV 和 FFmpeg / ffprobe。无需 PySide6、在线 API 或固定显卡。以下示例使用 PowerShell，替换为实际路径：

```powershell
$skillDir = '本 SKILL.md 所在目录'
$workspace = '用户工作区路径'
python -m venv (Join-Path $workspace '.venv-chouzhen')
$pythonExe = Join-Path $workspace '.venv-chouzhen\Scripts\python.exe'
& $pythonExe -m pip install -r (Join-Path $skillDir 'scripts\requirements.txt')
& $pythonExe (Join-Path $skillDir 'scripts\chouzhen.py') check
```

已有合适环境时直接使用，不重复创建。虚拟环境和视频产物放在用户工作区；skill 文件夹可整体移动，不需要改代码。`requirements.txt` 记录已验证的依赖版本。检查脚本不会自行安装、下载或修改系统配置。

## 只分析或生成预览

```text
python "SKILL_DIR/scripts/chouzhen.py" analyze "VIDEO_PATH" --output-dir "NEW_OUTPUT_DIR"
python "SKILL_DIR/scripts/chouzhen.py" render "OUTPUT_DIR/analysis.json" --output "OUTPUT_DIR/preview.mp4" --preview
```

`run` 等于分析后导出；默认导出原分辨率 H.264 / AAC MP4。`--preview` 限制最高 720p。输出是恒定帧率，沿用探测得到的名义帧率；处理可变帧率输入时，删帧边界仍按实际源帧 PTS 计算。

新分析要求空目录，避免把旧素材的方案和新素材的缩略图混在一起。渲染失败后保留的分析文件可直接用于重新导出。

## 修改方案

撤销第 2 次击杀的抽帧，另存方案：

```text
python "SKILL_DIR/scripts/chouzhen.py" edit "OUTPUT_DIR/analysis.json" --disable 2 --output "OUTPUT_DIR/undo-2.json"
python "SKILL_DIR/scripts/chouzhen.py" render "OUTPUT_DIR/undo-2.json" --output "OUTPUT_DIR/undo-2.mp4"
```

将第 2 次击杀改为删去 8 帧，并重新启用：

```text
python "SKILL_DIR/scripts/chouzhen.py" edit "OUTPUT_DIR/analysis.json" --enable 2 --frames 2=8 --output "OUTPUT_DIR/tuned.json"
```

改用利落模式：

```text
python "SKILL_DIR/scripts/chouzhen.py" edit "OUTPUT_DIR/analysis.json" --preset snappy --output "OUTPUT_DIR/snappy.json"
python "SKILL_DIR/scripts/chouzhen.py" render "OUTPUT_DIR/snappy.json" --output "OUTPUT_DIR/snappy.mp4"
```

- `natural` 每次最多压缩 0.25 秒；`snappy` 每次最多压缩 0.60 秒，都不能超出已识别的可剪区间。
- `--disable` / `--enable` 可跟多个 ID；`--frames ID=N` 可重复传入。ID 来自本次方案，不是视频帧号。
- 同时指定时，先应用预设，再应用启停和帧数设置。调整帧数不会自动启用已禁用的击杀。
- `edit` 默认另存为 `analysis.edited.json`；`edit` 和 `render` 均在目标已存在时报错。只有需要替换该文件时才加 `--overwrite`。
- 原始录像始终不能作为导出目标。缺少源视频或源文件大小、修改时间发生变化时，需要找到原文件或重新分析，不绕过源文件校验。

## 数据含义

完整方案由脚本生成，直接修改前只需理解这些字段：

| 字段 | 含义 |
| --- | --- |
| `media.path` | 本次源录像绝对路径 |
| `kills[].id` | 本次分析中的击杀 ID |
| `time` | 该击杀记录在 HUD 中出现的时间，单位秒 |
| `burst_start` | 推测的连续射击起点；无可靠结果时为 null |
| `safe_start` / `safe_end` | 当前算法允许剪接的区间；null 表示保留原动作 |
| `cut_points` | 可选择的源帧时间戳，用于精确按帧调整 |
| `cut_start` / `cut_end` | 当前删去的半开区间 `[start, end)`，单位秒 |
| `enabled` | 是否应用这次删帧，不影响其他击杀 |
| `thumbnail` | 本地缩略图路径 |

优先使用 `edit`，让程序检查 ID、帧数和边界。`render` 不重新识别，也不会把编辑过的参数写回原方案。

stdout 是最终结果 JSON，stderr 是进度 JSON 或运行时错误。`check` 缺环境返回 2，处理错误返回 1，取消返回 130；帮助和命令行参数格式错误使用普通 argparse 输出。导出结果包含 `source_duration_seconds`、`output_duration_seconds`、`removed_seconds`，可核对时长变化；首次适配新素材时再按实际需要查看剪接附近画面及音轨。
