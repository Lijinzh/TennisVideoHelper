# TennisVideoHelper

使用声音瞬态和近端球员动作共同识别网球连续对打区间，并通过 NVIDIA NVENC 自动切分长回合视频。

程序面向固定或云台侧后方机位：近端球员在画面中较大，远端对手可能不在画面中。音频负责发现击球候选，姿态和运动分析负责验证近端动作，时间序列负责推断回合是否持续。

## 击球与回合判定标准

当前实现不是“听到球声就保留”，而是按以下顺序确认：

1. 声音瞬态只负责召回可能的击球时刻；没有骨架动作支持的声音始终低于回合支撑阈值，不能独立开始或延长回合。
2. YOLO Pose 选择画面中的近端主要球员，并在相对躯干坐标中分析动作，不把相机平移或整个人跑动直接当成挥拍；轻量 YOLO Object 只在骨架候选帧上确认移动手附近确实存在网球拍。
3. 在约 0.07–0.45 秒窗口内检查手腕和肘部相对肩膀的移动、手臂伸展及横向/纵向扫动；手臂运动必须明显强于腿部跑动。
4. 肩膀必须明显位于髋部上方，躯干不能接近水平或因前屈而明显缩短。低头弯腰捡球会因站立姿态不足被过滤；正常准备姿势和屈膝仍允许通过。
5. 不硬编码“右手正手、左手反手”。系统按当次动作判断左手单手、右手单手或双手挥拍，因此兼容左手球员、双反和单手切削。
6. 同一次挥拍在 0.75 秒内只保留最高分帧。人体框高度超过画面 55% 时视为球员已走到镜头前或身体严重裁切，立即切断动作轨迹，避免走近镜头、捡球或离场动作粘连回合。
7. 回合起止只由“骨架动作 + 移动手附近检测到网球拍”的挥拍锚点决定；一个回合至少要有两次手腕相对肩膀移动达到 `0.85 个躯干长度` 的强挥拍，并且回合内至少一次球拍挥拍要与置信度不低于 `0.10` 的声音对齐。普通讲话手势即使幅度较大，只要移动手附近没有球拍，就不能凑成回合。
8. 对手击球声只能在两个视觉锚点之间桥接，不能把边界向前或向后拖长。

## 安全原则

- 源视频始终只读。
- 程序不会删除、移动或覆盖源视频。
- 命令行默认使用新的编号目录；界面默认启用“覆盖同名旧结果”，但只在新结果完整生成并验证成功后替换，任务失败或被停止时保留旧结果。
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
- 可选择成功后覆盖同名视频的旧结果；关闭后继续生成 `_2`、`_3` 等历史版本目录。
- 默认把超过 1080p 的素材通过 NVDEC、CUDA 缩放和 NVENC 导出为最高 1080p，同时保留原始帧率和可变帧率时间关系；勾选“以原画质导出”后才保留 4K 等源分辨率。
- 在顶部工作区以竖屏友好的窄幅预览显示当前视频、文件名和批次序号；输入输出与任务控制同屏排列。
- 显示真实处理阶段、完成百分比、已用时间和预计剩余时间，而不是模拟进度。
- 在开始按钮下方显示实际加速状态：明确标出 GPU 已启用、部分启用或已回退 CPU，并列出 TensorRT/PyTorch CUDA、NVDEC/OpenCV 与 NVENC/libx265 的真实后端。
- 调整最短回合、前后保留、结束静默、画面分析率、声音灵敏度和动作灵敏度。
- 使用加大的数值调节按钮，并将参数说明与输入框分开布局，避免文字互相遮挡。
- 仅分析视频开头的指定分钟数，便于快速试跑和调参。
- 点击“检测并优化”，用所选真实视频自动测试 TensorRT/PyTorch 和多个批量；最快且事件结果一致的配置会保存到 `%LOCALAPPDATA%\TennisVideoHelper\optimization-profile.json`，以后自动套用。
- 后台调用现有分析管线，界面保持响应，并可手动停止任务。

不要按显存大小猜批量：不同驱动、GPU 和视频格式的瓶颈不同，应以“检测并优化”的热态实测结果为准。当前 RTX 3070 对 60 秒真实 HLG/HEVC 素材选择 TensorRT FP16、批量 8、Threaded NVDEC，视觉分析约为 36.3 倍实时。

### 命令行

在命令行执行同一套自动优化：

```powershell
uv run tennis-video-helper optimize ".\网球\IMG_0566.MOV" --benchmark-seconds 60
```

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
- `--overwrite-existing`：新结果成功后替换同名旧结果；默认 `--keep-existing` 会继续创建编号目录。
- `--original-quality`：保留源分辨率；默认 `--1080p-output` 会把超过 1080p 的素材缩小到横屏 1920×1080 或竖屏 1080×1920，不放大低分辨率视频，并保持原始帧率。
- INT8 当前故意不自动启用：必须先用真实网球素材校准并验证长回合召回率，避免为了速度引入漏检。

程序会优先使用 NVDEC 在 GPU 上顺序解码、旋转、缩放和抽样；复杂可变帧率视频会用 PTS 校准保持时间线。若 PyNvVideoCodec、驱动或视频格式不兼容，会自动回退 OpenCV 跳帧解码。

Apple ProRes、Avid DNxHD/DNxHR 和 GoPro CineForm 不属于 NVIDIA NVDEC 支持的消费级硬件解码格式。遇到这些素材时，程序会直接使用 CPU/OpenCV 解码，同时继续使用 CUDA 姿态推理和 NVENC 导出；这属于正常的“部分 GPU 加速”，不是显卡或驱动故障。

本机 RTX 4060 Laptop GPU 实测（仅视觉分析，同一模型与阈值）：

| 样本 | 原始实现 | 优化后 TensorRT + NVDEC | 加速 |
|---|---:|---:|---:|
| 1080p，前 60 秒 | 63.48 秒 | 3.02 秒 | 21.0× |
| 4K，前 15 秒 | 36.62 秒 | 2.92 秒 | 12.5× |

以上为已缓存 TensorRT FP16 引擎后的热启动结果；首次运行还会包含一次性的引擎构建时间。与优化后的批量 PyTorch/OpenCV 路径相比，同两段素材仍分别达到 8.48× 和 9.11× 加速。回合边界验证误差分别为 0.060 秒和 0.183 秒，均低于 ±0.5 秒目标。

完整 1080p 前 5 分钟任务中，NVENC 使用 `p4` 高速预设后，7 个片段全部通过现有媒体验证，总耗时从 51.37 秒降至 38.54 秒，约减少 25%。测试中 4 路并行编码相比 2 路只提升约 1%，因此继续保留 2 路，避免无意义地增加显存、磁盘与温度压力。

AMD XDNA NPU 目前未默认启用：本机驱动低于当前 Ryzen AI 运行时要求，且尚未证明能让端到端流程再提升至少 5%。GPU 路径已覆盖解码、预处理和姿态推理；NPU 只会在后续有可重复净收益时作为独立可选插件加入。

## 打包发布

便携版构建会内置 `ffmpeg.exe`、`ffprobe.exe`、姿态模型和已生成的 TensorRT 引擎，用户不需要单独安装 FFmpeg 或 Python：

```powershell
.\scripts\build_portable.ps1 -FfmpegDirectory "C:\path\to\ffmpeg\bin"
```

输出位于 `dist\TennisVideoHelper`，包含无控制台 GUI 和负责输出进度的 `TennisVideoHelperWorker.exe`。当前“完整自动建引擎版”的实测目录约 9.2 GiB，其中主要是 PyTorch CUDA（约 4.1 GiB）、TensorRT 构建资源（约 3.2 GiB）和通用完整版 FFmpeg（约 462 MiB）。因此它是功能基线，不是最终小体积发行版；后续发布应把首次建引擎工具链拆成按 GPU 下载的可选加速包，并使用只含所需解码/编码器的 FFmpeg 构建。

不需要用户现场构建 TensorRT 引擎时，可以生成体积更小的 Compact 版；它保留 CUDA、Threaded NVDEC 和 NVENC，并由自动优化选择最快的 PyTorch 批量：

```powershell
.\scripts\build_portable.ps1 -Edition Compact -FfmpegDirectory "C:\path\to\ffmpeg\bin"
```

Compact 输出位于 `dist\TennisVideoHelper-Compact`。Full 和 Compact 可以同时保留，分别面向绝对性能和下载体积优先的用户。

用于过滤讲话手势的 `yolo11n.onnx` 球拍检测模型约 10.8 MiB，Full 与 Light/Compact 安装版都会直接内置，不需要用户联网下载，也不会显著改变安装包体积。

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
