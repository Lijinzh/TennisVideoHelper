"""集中管理用户可调的分析参数。"""

from dataclasses import dataclass, field
from typing import Callable


AccelerationCallback = Callable[[dict[str, object]], None]


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    """网球回合分析配置。"""

    min_rally_duration: float = 10.0  # 最短有效对打时长，调大后只保留更长回合但可能漏掉精彩短回合，调小后输出更多但短回合也会增多
    min_confirmed_hits: int = 3  # 每段至少包含多少次“强挥拍 + 同步击球声”；3 次本方击球通常对应至少 5 拍往返，可明显过滤走路、捡球和持拍摆臂
    pre_roll: float = 2.0  # 回合开始前保留秒数，调大后准备动作更完整但片段更长，调小后更紧凑但可能切掉引拍前内容
    post_roll: float = 3.0  # 回合结束后保留秒数，调大后能保留收拍和反应但片段更长，调小后更紧凑但可能结束过急
    end_silence: float = 3.5  # 无可信击球后等待多久判定回合结束，调大后不易误断慢速回球但可能把间歇并入回合，调小后切分更敏感但容易把长回合拆开
    merge_gap: float = 1.5  # 两个候选区间间隔小于该值时自动合并，调大后更容易合并误断片段但也可能粘连两个独立回合，调小后区分更严格但漏检时容易碎片化
    analysis_fps: int = 12  # 每秒分析的画面帧数，调大后动作定位更细但推理更慢且显存占用增加，调小后速度更快但可能漏掉快速挥拍
    audio_sample_rate: int = 22_050  # 音频分析采样率，调大后保留更多高频细节但计算量增加，调小后分析更快但可能削弱击球瞬态特征
    audio_sensitivity: float = 1.0  # 声音候选灵敏度，调大后能检出更弱击球但背景球场误检会增加，调小后误检减少但可能漏掉远端或较轻的击球声
    visual_sensitivity: float = 1.0  # 骨架挥拍灵敏度；正手看主手轨迹，双反综合双腕同向运动和肩部转体，调大后轻微挥拍更易检出但空挥风险增加
    player_handedness: str = "right"  # 持拍手：right 接受右手单手和双手挥拍，left 接受左手单手和双手挥拍，auto 不限制
    aligned_audio_reliability: float = 0.9  # 音画时间对齐时声音证据的可靠度；未经骨架确认的声音不会独立启动或延长回合
    aligned_visual_reliability: float = 0.85  # 音画时间对齐时挥拍证据的可靠度，调大后动作对回合延续贡献更大但空挥风险增加，调小后更依赖击球声音
    fusion_threshold: float = 0.6  # 音画融合后判定可信事件的最低分数，调大后结果更保守但可能漏检，调小后召回率提高但背景噪声误检会增加
    rally_support_threshold: float = 0.38  # 已有强事件确认回合后，允许维持连续性的最低分数；为容纳不同 GPU 解码后端约 0.02 的置信度波动而保留小幅余量
    encode_cq: int = 21  # NVENC 恒定质量参数，数值调小后画质更高且文件更大，数值调大后文件更小但压缩痕迹更明显
    inference_backend: str = "auto"  # 姿态推理后端，正式版优先使用轻量 ONNX GPU 运行时；开发环境仍可选择 PyTorch 或 TensorRT
    inference_precision: str = "fp16"  # 推理精度，fp16 是默认高速高精度模式，int8 速度更高但必须经过真实素材校准，fp32 最稳妥但更慢
    inference_batch_size: int = 16  # 单次提交给 GPU 的分析帧数量，调大后通常能提高吞吐但增加显存占用，调小后显存更稳但 GPU 利用率降低
    require_gpu: bool = False  # 是否禁止 CPU 回退，开启后缺少 CUDA 会直接停止，关闭后会明确提示并使用 CPU 完成任务
    require_racket_confirmation: bool = True  # 骨架挥拍必须由移动手附近的网球拍检测确认；只对候选帧运行，避免把讲话手势当成回合
    gpu_available: bool | None = None  # 运行时探测结果；None 表示由调用方保持原有 GPU 导出行为，CLI 会写入实际探测结果
    export_original_quality: bool = False  # 默认把超过 1080p 的视频缩小到 1080p 并保持原始帧率；开启后保留源分辨率
    overwrite_existing_output: bool = False  # 成功完成后是否替换同名视频的旧结果；GUI 和 CLI 默认开启，失败或停止时保留旧结果
    acceleration_callback: AccelerationCallback | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        positive_fields = (
            "min_rally_duration",
            "min_confirmed_hits",
            "end_silence",
            "analysis_fps",
            "audio_sample_rate",
            "audio_sensitivity",
            "visual_sensitivity",
            "rally_support_threshold",
            "inference_batch_size",
        )
        non_negative_fields = ("pre_roll", "post_roll", "merge_gap")

        for field_name in positive_fields:
            if getattr(self, field_name) <= 0:
                raise ValueError(f"{field_name} 必须大于 0")

        for field_name in non_negative_fields:
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} 不能小于 0")

        if not 0 < self.fusion_threshold <= 1:
            raise ValueError("fusion_threshold 必须在 (0, 1] 范围内")

        for field_name in (
            "aligned_audio_reliability",
            "aligned_visual_reliability",
        ):
            if not 0 < getattr(self, field_name) <= 1:
                raise ValueError(f"{field_name} 必须在 (0, 1] 范围内")

        if self.rally_support_threshold > self.fusion_threshold:
            raise ValueError("rally_support_threshold 不能大于 fusion_threshold")

        if not 0 <= self.encode_cq <= 51:
            raise ValueError("encode_cq 必须在 [0, 51] 范围内")

        if self.inference_backend not in {"auto", "onnx", "torch", "tensorrt"}:
            raise ValueError("inference_backend 必须是 auto、onnx、torch 或 tensorrt")

        if self.inference_precision not in {"fp16", "int8", "fp32"}:
            raise ValueError("inference_precision 必须是 fp16、int8 或 fp32")

        if self.player_handedness not in {"right", "left", "auto"}:
            raise ValueError("player_handedness 必须是 right、left 或 auto")
