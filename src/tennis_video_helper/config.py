"""集中管理用户可调的分析参数。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    """网球回合分析配置。"""

    min_rally_duration: float = 10.0  # 最短有效对打时长，调大后只保留更长回合但可能漏掉精彩短回合，调小后输出更多但短回合也会增多
    pre_roll: float = 2.0  # 回合开始前保留秒数，调大后准备动作更完整但片段更长，调小后更紧凑但可能切掉引拍前内容
    post_roll: float = 3.0  # 回合结束后保留秒数，调大后能保留收拍和反应但片段更长，调小后更紧凑但可能结束过急
    end_silence: float = 3.0  # 无可信击球后等待多久判定回合结束，调大后不易误断长回合但可能把间歇并入回合，调小后切分更敏感但容易把长回合拆开
    merge_gap: float = 1.5  # 两个候选区间间隔小于该值时自动合并，调大后更容易合并误断片段但也可能粘连两个独立回合，调小后区分更严格但漏检时容易碎片化
    analysis_fps: int = 12  # 每秒分析的画面帧数，调大后动作定位更细但推理更慢且显存占用增加，调小后速度更快但可能漏掉快速挥拍
    audio_sample_rate: int = 22_050  # 音频分析采样率，调大后保留更多高频细节但计算量增加，调小后分析更快但可能削弱击球瞬态特征
    audio_sensitivity: float = 1.0  # 声音候选灵敏度，调大后能检出更弱击球但背景球场误检会增加，调小后误检减少但可能漏掉远端或较轻的击球声
    visual_sensitivity: float = 1.0  # 挥拍动作灵敏度，调大后更容易识别轻微动作但空挥误检会增加，调小后判断更严格但可能漏掉幅度较小的回球
    fusion_threshold: float = 0.6  # 音画融合后判定可信事件的最低分数，调大后结果更保守但可能漏检，调小后召回率提高但背景噪声误检会增加
    rally_support_threshold: float = 0.4  # 已有强事件确认回合后，允许维持连续性的最低分数，调大后误延续更少但长回合容易被打断，调小后更能连接漏检但可能把相邻活动粘连
    encode_cq: int = 21  # NVENC 恒定质量参数，数值调小后画质更高且文件更大，数值调大后文件更小但压缩痕迹更明显

    def __post_init__(self) -> None:
        positive_fields = (
            "min_rally_duration",
            "end_silence",
            "analysis_fps",
            "audio_sample_rate",
            "audio_sensitivity",
            "visual_sensitivity",
            "rally_support_threshold",
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

        if self.rally_support_threshold > self.fusion_threshold:
            raise ValueError("rally_support_threshold 不能大于 fusion_threshold")

        if not 0 <= self.encode_cq <= 51:
            raise ValueError("encode_cq 必须在 [0, 51] 范围内")
