# TennisVideoHelper

使用声音瞬态和近端球员动作共同识别网球连续对打区间，并通过 NVIDIA NVENC 自动切分长回合视频。

程序面向固定或云台侧后方机位：近端球员在画面中较大，远端对手可能不在画面中。音频负责发现击球候选，姿态和运动分析负责验证近端动作，时间序列负责推断回合是否持续。

## 安全原则

- 源视频始终只读。
- 程序不会删除、移动或覆盖源视频。
- 每次运行使用新的输出目录，避免静默覆盖之前的精选结果。
- 只有通过 ffprobe 和头尾解码检查的片段才标记为验证成功。

## 环境要求

- Windows 10 或更新版本
- Python 3.12，由 `uv` 自动管理
- NVIDIA GeForce RTX 4060 Laptop GPU，8 GB 显存
- 支持 CUDA 12.8 的 NVIDIA 驱动
- 已加入 `PATH` 的 FFmpeg 和 ffprobe
- FFmpeg 必须包含 `hevc_nvenc`

检查本机编码器：

```powershell
ffmpeg -hide_banner -encoders | Select-String "hevc_nvenc"
```

## 安装

所有项目依赖统一使用 `uv add` 添加，并通过锁文件同步。不要使用 pip 修改项目环境。

```powershell
uv sync --extra dev
```

首次同步需要下载 CUDA 版 PyTorch，文件较大。如果网络读取容易超时，可以只为当前 PowerShell 会话提高 uv 超时：

```powershell
$env:UV_HTTP_TIMEOUT = "900"
uv sync --extra dev
```

验证 CUDA：

```powershell
uv run python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

预期显示 `True` 和 `NVIDIA GeForce RTX 4060 Laptop GPU`。

## 使用方法

分析单个视频：

```powershell
uv run tennis-video-helper analyze ".\网球\VID_20260425_213428.mp4" --output ".\精选输出"
```

批量分析整个文件夹：

```powershell
uv run tennis-video-helper analyze ".\网球" --output ".\精选输出"
```

首次校准时只分析每个视频的前 5 分钟：

```powershell
uv run tennis-video-helper analyze ".\网球" --output ".\精选输出" --limit-duration 300
```

## 可调参数

参数集中在 [`src/tennis_video_helper/config.py`](src/tennis_video_helper/config.py)。每个参数后面都有中文注释，说明参数用途，以及调大或调小后的实际效果和误检风险。

主要默认值：

```python
min_rally_duration: float = 10.0  # 最短有效对打时长，调大后只保留更长回合，调小后会输出更多短回合
pre_roll: float = 2.0  # 回合开始前保留秒数，调大后准备动作更完整，调小后片段更紧凑
post_roll: float = 3.0  # 回合结束后保留秒数，调大后收拍和反应更完整，调小后结束更紧凑
end_silence: float = 3.0  # 多久没有可信击球后结束回合，调大后不易误断，调小后切分更敏感
analysis_fps: int = 12  # 每秒分析帧数，调大后动作定位更细但更慢，调小后更快但可能漏掉快速挥拍
fusion_threshold: float = 0.6  # 确认回合所需的强事件阈值，调大后更保守，调小后更容易把噪声当作击球
rally_support_threshold: float = 0.4  # 强事件确认后维持回合的支撑阈值，调大后容易断开，调小后更容易粘连
```

修改参数后不需要重新锁定依赖，直接重新运行分析命令即可。

## 输出结构

```text
精选输出/
└── VID_20260425_213428/
    ├── clips/
    │   ├── rally_001_00-02-14_12.6s.mp4
    │   └── rally_002_00-05-47_18.3s.mp4
    ├── segments.csv
    ├── analysis.json
    └── processing.log
```

- `clips/`：通过 NVENC 编码的独立长回合片段。
- `segments.csv`：方便人工查看的时间、时长、音频/视觉候选数量和置信度摘要。
- `analysis.json`：保存源媒体信息、片段结果，以及全部音频、视觉和融合事件的时间戳、分数与判定理由，便于后续调参。
- `processing.log`：各阶段事件数量和验证统计。

## 输入视频策略

- 4K 30 FPS 输入保持 4K 30 FPS。
- 1080P 60 FPS 输入保持 1080P 60 FPS。
- 1080P 30 FPS 输入保持 1080P 30 FPS。
- 30/60 FPS 混合的可变帧率输入使用每帧真实时间戳分析，导出时不强制改成固定帧率；报告中的 `fps` 是整段视频平均值，局部片段可能显示为 30 或 60 FPS。
- SDR 使用 HEVC 8-bit NVENC。
- HDR10 使用 HEVC Main10 NVENC，并保留 PQ 传递函数标记。
- 第一版检测到 Dolby Vision 会停止处理该视频，避免动态元数据丢失造成偏色。
- 没有音轨的视频会停止处理，因为第一版要求音画融合。

## 校准

人工标记格式和调参步骤见 [`calibration/README.md`](calibration/README.md)。建议先标记 5 至 10 分钟素材，优先保证长回合召回率，再逐步降低背景球场声音导致的误检。

## 测试

```powershell
uv run pytest -q
```

## 设计与实施计划

- [完整设计](docs/superpowers/specs/2026-07-24-tennis-rally-video-selector-design.md)
- [实施计划](docs/superpowers/plans/2026-07-24-tennis-rally-video-selector-implementation.md)
