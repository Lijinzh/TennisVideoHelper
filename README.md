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

基础安装使用 PyTorch CUDA，并在 TensorRT 或 NVDEC 不可用时保持可运行。RTX 20/30/40/50 系列建议安装最高性能可选组件：

```powershell
uv sync --extra dev --extra gpu-max
```

`gpu-max` 会安装 NVIDIA PyNvVideoCodec、TensorRT、ONNX 和 ModelOpt，首次下载约 2 GB。首次使用 `auto`/`tensorrt` 后端时会构建本机专用 FP16 引擎并缓存到 `~/.cache/tennis-video-helper/engines`，通常需要数分钟；以后直接复用缓存。

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

### 可视化界面

启动磨砂黑桌面界面：

```powershell
uv run tennis-video-helper-gui
```

界面支持：

- 选择单个视频或整个视频文件夹。
- 选择精选片段输出目录，并在完成后直接打开。
- 在顶部工作区显示当前处理视频的预览图、文件名和批次序号。
- 显示真实处理阶段、完成百分比、已用时间和预计剩余时间，而不是模拟进度。
- 调整最短回合、前后保留、结束静默、画面分析率、声音灵敏度和动作灵敏度。
- 使用加大的数值调节按钮，并将参数说明与输入框分开布局，避免文字互相遮挡。
- 仅分析视频开头的指定分钟数，便于快速试跑和调参。
- 后台调用现有分析管线，界面保持响应，并可手动停止任务。

RTX 4060 Laptop GPU 只有 8 GB 显存，画面分析率建议先保持在 8–12 FPS；继续调高会增加动作采样密度，但处理速度和显存占用也会明显上升。

### 命令行

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

最高性能模式（默认就是这些参数）：

```powershell
uv run tennis-video-helper analyze ".\网球" --output ".\精选输出" --backend auto --precision fp16 --batch-size 16
```

- `auto`：优先 TensorRT，引擎构建/加载失败时回退批量 PyTorch CUDA。
- `torch`：强制使用批量 PyTorch CUDA，适合排查 TensorRT 差异。
- `tensorrt`：强制使用 TensorRT；依赖或引擎构建失败会明确停止。
- `--require-gpu`：没有 CUDA/NVENC 时停止；默认 `--allow-cpu` 会明确警告并回退 CPU 推理和 `libx265` 导出。
- INT8 当前故意不自动启用：必须先用真实网球素材校准并验证长回合召回率，避免为了速度引入漏检。

程序会优先使用 NVDEC 在 GPU 上顺序解码、旋转、缩放和抽样；复杂可变帧率视频会用 PTS 校准保持时间线。若 PyNvVideoCodec、驱动或视频格式不兼容，会自动回退 OpenCV 跳帧解码。

本机 RTX 4060 Laptop GPU 实测（仅视觉分析，同一模型与阈值）：

| 样本 | 原始实现 | 优化后 TensorRT + NVDEC | 加速 |
|---|---:|---:|---:|
| 1080p，前 60 秒 | 63.48 秒 | 3.02 秒 | 21.0× |
| 4K，前 15 秒 | 36.62 秒 | 2.92 秒 | 12.5× |

以上为已缓存 TensorRT FP16 引擎后的热启动结果；首次运行还会包含一次性的引擎构建时间。与优化后的批量 PyTorch/OpenCV 路径相比，同两段素材仍分别达到 8.48× 和 9.11× 加速。回合边界验证误差分别为 0.060 秒和 0.183 秒，均低于 ±0.5 秒目标。

AMD XDNA NPU 目前未默认启用：本机驱动低于当前 Ryzen AI 运行时要求，且尚未证明能让端到端流程再提升至少 5%。GPU 路径已覆盖解码、预处理和姿态推理；NPU 只会在后续有可重复净收益时作为独立可选插件加入。

## 可调参数

参数集中在 [`src/tennis_video_helper/config.py`](src/tennis_video_helper/config.py)。每个参数后面都有中文注释，说明参数用途，以及调大或调小后的实际效果和误检风险。

主要默认值：

```python
min_rally_duration: float = 10.0  # 最短有效对打时长，调大后只保留更长回合，调小后会输出更多短回合
pre_roll: float = 2.0  # 回合开始前保留秒数，调大后准备动作更完整，调小后片段更紧凑
post_roll: float = 3.0  # 回合结束后保留秒数，调大后收拍和反应更完整，调小后结束更紧凑
end_silence: float = 3.5  # 多久没有可信击球后结束回合，调大后不易误断慢速回球，调小后切分更敏感
analysis_fps: int = 12  # 每秒分析帧数，调大后动作定位更细但更慢，调小后更快但可能漏掉快速挥拍
aligned_audio_reliability: float = 0.9  # 音画对齐时声音证据可靠度，调大后更依赖声音，调小后更依赖动作
aligned_visual_reliability: float = 0.85  # 音画对齐时动作证据可靠度，调大后更依赖挥拍动作，调小后更依赖声音
fusion_threshold: float = 0.6  # 确认回合所需的强事件阈值，调大后更保守，调小后更容易把噪声当作击球
rally_support_threshold: float = 0.38  # 强事件确认后维持回合的支撑阈值，并容纳不同 GPU 解码后端的小幅置信度波动
inference_backend: str = "auto"  # 自动优先 TensorRT，失败时回退批量 PyTorch CUDA
inference_precision: str = "fp16"  # 默认 FP16；INT8 在完成真实素材校准前不会启用
inference_batch_size: int = 16  # RTX 4060 8 GB 的默认批量
require_gpu: bool = False  # False 时缺少显卡会明确警告并回退 CPU
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
- Dolby Vision Profile 8.4 可使用其 HLG 兼容基础层分析，并导出为 10-bit HLG Main10；NVENC 输出不再包含 Dolby Vision 动态元数据，但会保留 BT.2020、HLG 传递函数和色彩范围。
- 其他 Dolby Vision Profile 会停止处理，避免在没有兼容基础层时造成偏色。
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
