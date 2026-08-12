# 为 Tennis Video Helper 贡献代码

感谢你愿意帮助这个项目。建议先创建或认领一个 GitHub Issue，写清楚现象、输入视频特征、预期结果和当前结果，再开始修改代码。

GitHub Pages 架构图中的“阅读贡献指南”会通过 `docs/contributing.html` 跳转到本文件，避免网站发布与提交顺序导致链接暂时失效。

## 本地开发环境

项目使用 Python 3.12 和仓库本地的 uv 环境：

```powershell
uv sync --extra dev
uv run tennis-video-helper-gui
```

需要验证完整 NVIDIA GPU 路径时，再安装 GPU 扩展依赖：

```powershell
uv sync --extra dev --extra gpu-max
```

不要用全局 `pip` 修改项目依赖。依赖发生变化时，应同时提交 `pyproject.toml` 与 `uv.lock`。

## 从哪里开始修改

| 方向 | 主要代码 | 重点测试 |
| --- | --- | --- |
| 击球声音候选 | `src/tennis_video_helper/detection/audio.py` | `tests/detection/test_audio.py` |
| 骨架、挥拍和球拍确认 | `src/tennis_video_helper/detection/vision/` | `tests/detection/vision/` |
| 音画融合与回合边界 | `src/tennis_video_helper/detection/fusion.py` | `tests/detection/test_fusion.py` |
| 批处理与候选生成 | `src/tennis_video_helper/app/pipeline.py` | `tests/app/test_pipeline.py` |
| 人工复核会话 | `src/tennis_video_helper/review/` | `tests/review/` |
| 视频读取、导出与安全覆盖 | `src/tennis_video_helper/media/` | `tests/media/` |
| Windows GUI | `src/tennis_video_helper/ui/` | `tests/ui/` |
| GitHub Pages 官网 | `docs/` | `tests/test_website.py` |

## 提交前检查

至少运行与你修改内容直接相关的测试，然后运行完整测试：

```powershell
uv run pytest -q
git diff --check
```

如果修改识别算法，请在 Pull Request 中补充：

- 视频时长、分辨率、帧率、机位和球员惯用手；
- 修改前后的候选片段数量与确认击球点；
- 是否新增漏检、误检或明显性能退化；
- 用于锁定行为的最小自动化测试。

不要提交私人训练视频、API 密钥、访问令牌、个人路径或包含他人隐私的日志。

## Pull Request 建议

1. 从最新 `main` 创建独立分支。
2. 一个 Pull Request 只处理一个清晰问题。
3. 说明问题、方案、验证方法和剩余风险。
4. UI 改动附桌面与移动端截图；视频流程改动附媒体探测或解码验证结果。
5. 不要为了顺手整理而大范围重构无关模块。

对于击球判定，声音只能缩小视觉搜索范围。一个真实击球仍应具有对齐的声音、挥拍骨架动作和足够的球拍证据；孤立声音、走路持拍、低头捡球或普通摆臂不能单独形成回合。
