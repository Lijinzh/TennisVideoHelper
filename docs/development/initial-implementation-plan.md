# Tennis Rally Video Selector Implementation Plan

> 历史说明：本文记录项目最初实现时的目录和测试步骤，其中路径保持当时状态。当前可维护架构请以 [`../architecture.md`](../architecture.md) 为准。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个由 `uv` 管理、使用音画融合检测长回合并通过 RTX 4060 NVENC 输出独立视频片段的 Python 命令行工具。

**Architecture:** 管线先用 ffprobe 扫描媒体，再分别生成音频瞬态事件和近端球员视觉动作事件；融合模块将两类事件转换为连续回合区间，最后由 FFmpeg/NVENC 精确切片并生成报告。音频、视觉、融合、导出模块使用带时间戳的数据结构隔离，便于独立测试和替换。

**Tech Stack:** Python 3.12、uv、NumPy、SciPy、librosa、OpenCV、Ultralytics YOLO Pose、PyTorch CUDA、Typer、FFmpeg/ffprobe、pytest。

---

## 文件结构

```text
pyproject.toml
.gitignore
README.md
src/tennis_video_helper/
├── __init__.py
├── config.py
├── models.py
├── media.py
├── audio.py
├── vision.py
├── fusion.py
├── exporter.py
├── report.py
├── pipeline.py
└── cli.py
tests/
├── test_config.py
├── test_media.py
├── test_audio.py
├── test_vision.py
├── test_fusion.py
├── test_exporter.py
└── test_pipeline.py
```

每个阶段最多集中处理五个非生成文件；`uv.lock`、模型权重和测试输出属于生成内容。

### Task 1: 初始化 Git、uv 包结构与配置对象

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/tennis_video_helper/__init__.py`
- Create: `src/tennis_video_helper/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 初始化 Git 主分支**

Run: `git init -b main`

Expected: 输出 `Initialized empty Git repository`，当前分支为 `main`。

- [ ] **Step 2: 写入配置验证的失败测试**

```python
import pytest

from tennis_video_helper.config import AnalysisConfig


def test_default_config_matches_approved_design() -> None:
    config = AnalysisConfig()
    assert config.min_rally_duration == 10.0
    assert config.pre_roll == 2.0
    assert config.post_roll == 3.0
    assert config.analysis_fps == 12


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="min_rally_duration"):
        AnalysisConfig(min_rally_duration=0)
```

- [ ] **Step 3: 运行测试确认模块尚不存在**

Run: `uv run pytest tests/test_config.py -q`

Expected: FAIL，提示无法导入 `tennis_video_helper.config`。

- [ ] **Step 4: 实现不可变配置对象和参数中文行内注释**

实现 `AnalysisConfig`，包含设计文档中的 11 个公开参数；在 `__post_init__` 中验证持续时间、采样率、分析帧率、灵敏度、融合阈值和编码质量范围。

- [ ] **Step 5: 安装依赖并验证测试通过**

Run: `uv sync --extra dev && uv run pytest tests/test_config.py -q`

Expected: `2 passed`。

- [ ] **Step 6: 提交项目基础**

```powershell
git add pyproject.toml .gitignore README.md src/tennis_video_helper/__init__.py src/tennis_video_helper/config.py tests/test_config.py docs
git commit -m "chore: initialize tennis video helper"
```

### Task 2: 实现媒体扫描与 ffprobe 元数据读取

**Files:**
- Create: `src/tennis_video_helper/models.py`
- Create: `src/tennis_video_helper/media.py`
- Create: `tests/test_media.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 写入媒体解析和扩展名过滤的失败测试**

测试 `parse_probe_payload()` 能读取时长、分辨率、帧率、音轨、旋转和 HDR/Dolby Vision 标记；测试 `scan_videos()` 只返回支持的视频扩展名并保持稳定排序。

- [ ] **Step 2: 运行媒体测试确认失败**

Run: `uv run pytest tests/test_media.py -q`

Expected: FAIL，提示媒体函数尚不存在。

- [ ] **Step 3: 实现媒体模型和扫描器**

定义 `MediaInfo`、`AudioEvent`、`VisualEvent`、`FusedEvent` 和 `RallySegment` 数据类。`probe_media()` 使用参数数组调用 `ffprobe`，不拼接 shell 字符串；`scan_videos()` 支持文件和目录输入。

- [ ] **Step 4: 运行媒体测试**

Run: `uv run pytest tests/test_media.py -q`

Expected: 所有媒体测试通过。

- [ ] **Step 5: 提交媒体基础**

```powershell
git add src/tennis_video_helper/models.py src/tennis_video_helper/media.py tests/test_media.py pyproject.toml
git commit -m "feat: add media scanning and probing"
```

### Task 3: 实现音频提取与瞬态事件检测

**Files:**
- Create: `src/tennis_video_helper/audio.py`
- Create: `tests/test_audio.py`
- Modify: `src/tennis_video_helper/models.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 写入合成击球脉冲测试**

构造包含 1.0、2.0、3.0 秒短促高频脉冲及低幅背景噪声的 NumPy 音频，断言检测结果靠近三个已知时间点，并验证相隔过近的峰值会去重。

- [ ] **Step 2: 运行音频测试确认失败**

Run: `uv run pytest tests/test_audio.py -q`

Expected: FAIL，提示 `detect_audio_events` 尚不存在。

- [ ] **Step 3: 实现音频分析**

`extract_audio()` 使用 FFmpeg 输出临时单声道 WAV；`detect_audio_events()` 使用 Log-Mel 频谱、`librosa.onset.onset_strength`、动态分位数阈值和峰值间隔生成 `AudioEvent`。

- [ ] **Step 4: 运行音频测试**

Run: `uv run pytest tests/test_audio.py -q`

Expected: 合成瞬态测试全部通过。

- [ ] **Step 5: 提交音频模块**

```powershell
git add src/tennis_video_helper/audio.py src/tennis_video_helper/models.py tests/test_audio.py pyproject.toml
git commit -m "feat: detect tennis audio transients"
```

### Task 4: 实现近端球员姿态与动作分析

**Files:**
- Create: `src/tennis_video_helper/vision.py`
- Create: `tests/test_vision.py`
- Modify: `src/tennis_video_helper/models.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 写入主球员选择和姿态运动分数测试**

使用伪造的人体框和关键点，断言面积更大且轨迹连续的近端球员被选择；断言腕、肘相对躯干快速移动时动作分数增加，而全体关键点共同平移时分数保持较低。

- [ ] **Step 2: 运行视觉测试确认失败**

Run: `uv run pytest tests/test_vision.py -q`

Expected: FAIL，提示视觉辅助函数尚不存在。

- [ ] **Step 3: 实现视觉分析器**

使用 `yolo11n-pose.pt` 和 CUDA 推理；按 `analysis_fps` 采样并缩放分析帧。通过最大人物框、上一帧中心距离和关键点可见度选择主球员。动作分数使用相对躯干归一化的腕肘位移，并用背景稀疏光流估计全局运动。

- [ ] **Step 4: 运行视觉单元测试和 CUDA 冒烟测试**

Run: `uv run pytest tests/test_vision.py -q`

Run: `uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"`

Expected: 测试通过，并输出 `True` 与 RTX 4060 Laptop GPU。

- [ ] **Step 5: 提交视觉模块**

```powershell
git add src/tennis_video_helper/vision.py src/tennis_video_helper/models.py tests/test_vision.py pyproject.toml
git commit -m "feat: analyze foreground player motion"
```

### Task 5: 实现音画融合与回合状态机

**Files:**
- Create: `src/tennis_video_helper/fusion.py`
- Create: `tests/test_fusion.py`
- Modify: `src/tennis_video_helper/models.py`
- Modify: `src/tennis_video_helper/config.py`

- [ ] **Step 1: 写入融合和切分失败测试**

覆盖以下行为：音画时间接近时得到高分；合理间隔的音频独立事件可表示远端击球；背景孤立声音低于阈值；持续 12 秒的事件序列被保留；持续 8 秒的序列被过滤；缓冲限制在视频范围内。

- [ ] **Step 2: 运行融合测试确认失败**

Run: `uv run pytest tests/test_fusion.py -q`

Expected: FAIL，提示融合函数尚不存在。

- [ ] **Step 3: 实现融合和状态机**

实现 `fuse_events()`、`build_rally_segments()` 和 `merge_segments()`。保留事件来源、音频分数、视觉分数、融合分数和判定理由。

- [ ] **Step 4: 运行融合测试**

Run: `uv run pytest tests/test_fusion.py -q`

Expected: 所有融合边界测试通过。

- [ ] **Step 5: 提交融合模块**

```powershell
git add src/tennis_video_helper/fusion.py src/tennis_video_helper/models.py src/tennis_video_helper/config.py tests/test_fusion.py
git commit -m "feat: fuse events into rally segments"
```

### Task 6: 实现 NVENC 导出和报告

**Files:**
- Create: `src/tennis_video_helper/exporter.py`
- Create: `src/tennis_video_helper/report.py`
- Create: `tests/test_exporter.py`
- Modify: `src/tennis_video_helper/models.py`

- [ ] **Step 1: 写入 FFmpeg 参数和报告序列化失败测试**

断言 SDR 使用 `hevc_nvenc`，10-bit HDR 使用 `p010le` 和 Main10，Dolby Vision 会被拒绝；断言导出参数不包含缩放或强制帧率；断言 CSV/JSON 包含片段起止时间和置信度。

- [ ] **Step 2: 运行导出测试确认失败**

Run: `uv run pytest tests/test_exporter.py -q`

Expected: FAIL，提示导出函数尚不存在。

- [ ] **Step 3: 实现导出、验证和报告**

使用参数数组执行 FFmpeg；编码完成后调用 ffprobe，并对片段头尾进行解码检查。报告采用临时文件写入后原子替换，避免中途中断留下伪成功报告。

- [ ] **Step 4: 运行导出测试并检查本机编码器**

Run: `uv run pytest tests/test_exporter.py -q`

Run: `ffmpeg -hide_banner -encoders | Select-String 'hevc_nvenc'`

Expected: 测试通过且本机列出 `hevc_nvenc`。

- [ ] **Step 5: 提交导出模块**

```powershell
git add src/tennis_video_helper/exporter.py src/tennis_video_helper/report.py src/tennis_video_helper/models.py tests/test_exporter.py
git commit -m "feat: export verified rally clips"
```

### Task 7: 实现管线和命令行入口

**Files:**
- Create: `src/tennis_video_helper/pipeline.py`
- Create: `src/tennis_video_helper/cli.py`
- Create: `tests/test_pipeline.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 写入管线编排失败测试**

通过依赖注入伪造扫描、音频、视觉和导出结果，断言单文件失败不会阻止后续文件，源文件路径不会作为写入目标，成功片段才进入报告。

- [ ] **Step 2: 运行管线测试确认失败**

Run: `uv run pytest tests/test_pipeline.py -q`

Expected: FAIL，提示管线尚不存在。

- [ ] **Step 3: 实现管线和 Typer CLI**

提供 `tennis-video-helper analyze INPUT --output OUTPUT`。启动时检查 FFmpeg、ffprobe、CUDA、模型权重和 NVENC；逐视频处理并显示当前阶段、耗时和输出数量。

- [ ] **Step 4: 运行全部测试和 CLI 帮助**

Run: `uv run pytest -q`

Run: `uv run tennis-video-helper --help`

Expected: 全部测试通过，帮助中显示 `analyze` 命令。

- [ ] **Step 5: 提交完整管线**

```powershell
git add src/tennis_video_helper/pipeline.py src/tennis_video_helper/cli.py tests/test_pipeline.py pyproject.toml
git commit -m "feat: add rally analysis cli"
```

### Task 8: 用当前样片执行校准与端到端验证

**Files:**
- Modify: `README.md`
- Create: `calibration/README.md`
- Create: `calibration/sample-labels.csv`

- [ ] **Step 1: 运行前 5 分钟分析校准**

Run: `uv run tennis-video-helper analyze .\网球\VID_20260425_213428.mp4 --output .\精选输出 --limit-duration 300`

Expected: 生成分析 JSON、CSV 和至少一份处理日志；如果没有达到 10 秒的候选回合，报告应明确记录零结果而不是报错。

- [ ] **Step 2: 检查 GPU 和输出媒体**

Run: `nvidia-smi`

Run: `ffprobe -v error -show_streams -show_format <生成片段>`

Expected: 视觉推理使用 RTX 4060，生成片段保留源分辨率、帧率策略并包含音频流。

- [ ] **Step 3: 记录校准方法和人工标签格式**

README 说明如何在 `sample-labels.csv` 中记录 `start_seconds,end_seconds,notes`，以及如何根据漏检和误检调整带中文注释的参数。

- [ ] **Step 4: 提交校准材料**

```powershell
git add README.md calibration
git commit -m "docs: add sample calibration workflow"
```

### Task 9: 最终验证并发布 GitHub 私有仓库

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新完整使用说明**

README 必须包含环境安装、CUDA/NVENC 检查、运行命令、输出结构、参数调整、HDR/Dolby Vision 限制和不删除源视频的安全说明。

- [ ] **Step 2: 执行最终验证**

Run: `uv sync --extra dev`

Run: `uv run pytest -q`

Run: `uv run tennis-video-helper --help`

Run: `git status --short --branch`

Expected: 依赖同步成功，测试零失败，CLI 可运行，只有预期文件变化。

- [ ] **Step 3: 提交最终文档**

```powershell
git add README.md uv.lock
git commit -m "docs: complete setup and usage guide"
```

- [ ] **Step 4: 检查 GitHub 登录和同名仓库**

Run: `gh auth status`

Run: `$githubOwner = gh api user --jq .login`

Run: `gh repo view "$githubOwner/TennisVideoHelper" --json name,visibility,url`

Expected: GitHub 已登录；若同名仓库不存在则继续创建，若存在则停止并报告冲突。

- [ ] **Step 5: 创建私有仓库并推送**

Run: `gh repo create TennisVideoHelper --private --source . --remote origin --push`

Expected: GitHub 创建私有仓库，`origin` 指向新仓库，`main` 已推送并跟踪 `origin/main`。

- [ ] **Step 6: 验证远端状态**

Run: `gh repo view --json nameWithOwner,visibility,url,defaultBranchRef`

Run: `git status --short --branch`

Expected: `visibility` 为 `PRIVATE`，默认分支为 `main`，本地工作树干净且与 `origin/main` 同步。
