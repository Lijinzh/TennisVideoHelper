# 真实视频校准

自动筛选的第一目标是不要漏掉真实长回合。建议先选取 5 至 10 分钟有代表性的素材，人工记录每个真实长回合的开始和结束时间，再与程序输出比较。

## 标记格式

在 `sample-labels.csv` 中填写：

- `source`：源视频文件名。
- `start_seconds`：有效对打开始秒数。
- `end_seconds`：有效对打结束秒数。
- `notes`：背景声音、下网、出界、遮挡等备注。

示例：

```csv
source,start_seconds,end_seconds,notes
VID_example.mp4,35.2,48.7,正常长回合
VID_example.mp4,92.1,103.0,远端击球声较弱
```

## 调参顺序

1. 先检查漏检：调高 `audio_sensitivity` 或 `visual_sensitivity`，或者调低 `fusion_threshold`。
2. 再检查回合被切碎：调大 `end_silence` 或 `merge_gap`。
3. 再检查背景球场误检：调低 `audio_sensitivity` 或调高 `fusion_threshold`。
4. 最后调整保留范围：修改 `min_rally_duration`、`pre_roll` 和 `post_roll`。

每个参数的调大、调小效果已经紧跟写在 `src/tennis_video_helper/config.py` 的参数定义后面。
