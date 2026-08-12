# TennisVideoHelper Codex 项目指南

本文件适用于仓库根目录及全部子目录。它规定 Codex 和其他自动化代理在本项目中的工作边界、验证要求、发布流程与长期规划。若子目录以后出现更具体的 `AGENTS.md`，则以更深层文件为准。

## 1. 项目目标

TennisVideoHelper 是一个面向 Windows 的网球视频精选工具。它通过音频瞬态、人体姿态、挥拍动作与球拍证据发现候选回合，让用户在桌面软件中逐段复核并导出结果。

项目同时维护四个需要一致演进的交付面：

1. Python 音画分析管线与 CLI；
2. PySide6 桌面软件；
3. Windows 安装包与 GitHub Release；
4. `docs/` 下的 GitHub Pages 官网。

任何工作都应优先保证：不破坏源视频、不误删用户结果、识别质量可验证、安装包可复现、软件与官网版本一致。

## 2. 开始工作前

每次任务开始先执行以下检查：

```powershell
git status --short --branch
git log -5 --oneline
```

- 阅读与任务直接相关的现有文档，不要绕过已经确定的架构和安全约束。
- 先确认未提交修改的归属。默认把它们视为用户工作，禁止覆盖、回滚或顺手提交。
- 修改识别或性能路径前，确认测试素材、GPU、FFmpeg、驱动、运行环境和软件进程与目标机器一致。
- 修改发布信息前，重新查询 GitHub Release 和公开下载资源；不要把旧记录当作当前状态。
- 使用 Windows PowerShell 命令，路径含空格或中文时使用 `-LiteralPath` 或正确引号。

## 3. 权威信息与目录职责

| 路径 | 职责 |
| --- | --- |
| `src/tennis_video_helper/core/` | 稳定配置与领域模型，不依赖 UI 或重型推理库 |
| `src/tennis_video_helper/media/` | 媒体探测、解码、导出、运行时与安全发布 |
| `src/tennis_video_helper/detection/` | 音频、视觉、球拍和融合算法 |
| `src/tennis_video_helper/review/` | 人工复核状态与报告 |
| `src/tennis_video_helper/app/` | 管线编排、CLI、硬件优化和更新器 |
| `src/tennis_video_helper/ui/` | PySide6 桌面界面，不在此重复实现识别算法 |
| `assets/` | 安装版必须携带的图标、模型和球场背景 |
| `packaging/` | PyInstaller 与 Inno Setup 配置 |
| `scripts/` | 构建、截图和资源生成脚本 |
| `docs/` | GitHub Pages 官网、架构、设计和 Release 说明 |
| `tests/` | 与源码分层对应的自动化测试 |

详细依赖方向见 `docs/architecture.md`。保持以下边界：

- `core` 不导入 OpenCV、PyTorch 或 PySide6。
- `media` 不负责判断击球。
- `detection` 不创建 UI，也不直接发布用户输出目录。
- `app` 负责编排并通过可替换服务连接各层。
- `ui` 调用应用层和复核层接口，不复制管线逻辑。

版本号的程序权威来源是：

- `pyproject.toml` 的 `project.version`；
- `src/tennis_video_helper/__init__.py` 的 `__version__`。

发布时所有其他版本展示都必须与二者一致。

## 4. 开发环境与常用命令

项目固定使用 Python 3.12 和仓库本地 `uv` 环境。不要用全局 `pip` 修改依赖。

```powershell
uv sync --extra dev
uv run pytest -q
uv run tennis-video-helper --help
uv run tennis-video-helper-gui
```

需要验证完整 NVIDIA 路径时才安装 GPU 扩展：

```powershell
uv sync --extra dev --extra gpu-max
```

依赖变更必须同时更新并提交 `pyproject.toml` 与 `uv.lock`。

## 5. 变更与测试矩阵

先运行最小相关测试，再运行完整测试。不能只凭软件能启动或某个样片成功就宣布完成。

| 变更范围 | 最小测试 |
| --- | --- |
| `detection/audio.py` | `uv run pytest tests/detection/test_audio.py -q` |
| `detection/fusion.py` | `uv run pytest tests/detection/test_fusion.py -q` |
| `detection/vision/` | `uv run pytest tests/detection/vision -q` |
| `media/` | `uv run pytest tests/media -q` |
| `app/pipeline.py` | `uv run pytest tests/app/test_pipeline.py -q` |
| 更新器 | `uv run pytest tests/app/test_updater.py tests/ui/test_update_schedule.py -q` |
| 桌面 UI | `uv run pytest tests/ui -q`，并实际启动界面检查 |
| 球场背景 | `uv run pytest tests/ui/test_court_backgrounds.py tests/test_website.py -q` |
| 官网 | `uv run pytest tests/test_website.py tests/test_github_star.py -q`，并做桌面与手机渲染检查 |
| 打包配置 | 运行相关构建脚本并检查产物内容 |
| 版本发布 | 完整测试、安装、公开 Release 与官网验证 |

提交前基线：

```powershell
uv run pytest -q
git diff --check
```

## 6. 识别算法规则

- 声音只用于缩小视觉搜索范围，不能单独确认击球或回合。
- 真实击球应有时间对齐的声音、挥拍骨架动作和足够的球拍证据。
- 走路持拍、低头捡球、讲话手势、普通摆臂和邻场声音不能单独形成回合。
- 优先保护真实长回合召回率，再降低误检；不得用显著漏检换取漂亮的候选数量。
- 修改采样、批次或缓冲逻辑时，保持全局采样时钟和跨批次球拍证据连续性。
- 参数继续集中在 `core/config.py`，新增参数要有中文注释，说明调大和调小的效果及风险。

识别改动必须记录：

- 素材时长、分辨率、帧率、机位和主要场景；
- 修改前后确认击球数、候选回合数、误检和漏检；
- 运行耗时与硬件/后端；
- 是否覆盖至少一个真实长视频，而不只是合成单元测试。

私人训练视频、截图和日志不得提交到仓库。

## 7. 输出与数据安全

- 源视频始终只读。
- 新结果先写入暂存目录，完成媒体校验和报告生成后再发布。
- 覆盖同名结果时，只替换该输入视频对应的目标目录，不清理整个输出根目录。
- 删除或替换前解析并核对绝对路径，禁止对仓库根目录、用户目录或未确认变量执行递归删除。
- 保留用户设置、外部输出目录和无关文件。
- FFmpeg/NVENC 成功退出不等于产物有效；仍需探测时长、流信息和可读性。

## 8. 桌面 UI 与主题

- 保持 UI、CLI 与管线共享同一配置和业务实现。
- 耗时分析不得阻塞主线程；进度、取消和错误状态必须可见。
- 主题选择使用持久化设置，关闭重开后应恢复。
- 球场背景需保持文字、视频预览和参数卡片可读，新增背景时同时更新资源清单和测试。
- UI 改动至少检查一个常规桌面窗口和一个较小窗口，关注裁切、重叠、滚动和对比度。
- 对话框、更新检查和安装流程要在已安装版本中实际验证，不只运行源码版。

## 9. 官网规则

`docs/` 是直接发布的静态站点。网站修改后必须同时验证源码测试与公开页面。

- 下载按钮使用精确版本资源：`releases/download/<tag>/<asset>`。
- 不使用无法证明存在的 `latest/download` 安装包链接。
- 版本、文件名、大小、SHA-256、Release 页面和发布日期必须与公开资产一致。
- 网站不能保存 GitHub Token，也不能从静态前端直接携带密钥创建 Issue。
- UI 改动检查桌面端与约 `390x844` 手机端。
- 验证页面标题、主要内容、下载交互、控制台错误和关键截图。
- 部署后使用带查询参数的 URL 做缓存穿透检查，例如 `?release=<version>-<timestamp>`。

## 10. Windows 打包

普通用户默认交付 Light 安装版：

```powershell
.\scripts\build_light_installer.ps1 `
    -FfmpegDirectory "C:\path\to\ffmpeg\bin"
```

Full/Compact 便携版按需构建：

```powershell
.\scripts\build_portable.ps1 -Edition Compact `
    -FfmpegDirectory "C:\path\to\ffmpeg\bin"
```

打包完成后检查：

- 主程序可以启动；
- `_internal/runtime/ffmpeg.exe` 与 `ffprobe.exe` 存在；
- 两个 ONNX 模型存在并可加载；
- `assets/backgrounds/` 的预期背景数量和文件名完整；
- 安装包文件名包含精确版本；
- 静默安装/升级退出码为 0；
- 已安装软件显示的版本与安装包一致；
- 覆盖升级不会留下旧 `_internal` 文件，也不会删除用户数据。

不要提交 `runtime/`、`build/`、`dist/`、本地虚拟环境或用户输出。

## 11. 版本与 Release 同步清单

发布新版本是一项完整工作，不是只修改源码或上传 EXE。至少同步检查：

1. `pyproject.toml`；
2. `src/tennis_video_helper/__init__.py`；
3. `packaging/TennisVideoHelper.iss` 的后备版本；
4. 依赖版本号的自动化测试；
5. `docs/tennis-video-helper.js` 中的版本、文件名、大小、SHA-256 和下载 URL；
6. `docs/index.html` 中所有可见版本、发布页、下载名、大小、SHA 和发布日期；
7. `docs/releases/v<version>.md`；
8. Windows 安装包；
9. GitHub Release 标题、标签、说明和资产；
10. 公开 GitHub Pages 页面。

Release 完成标准：

- 完整测试通过；
- 安装包在干净或现有安装上验证成功；
- 本地与 GitHub Release 资产的字节数和 SHA-256 一致；
- Release 不是草稿或预发布，并正确标记为 Latest；
- 公开下载可访问；
- 官网显示相同版本并指向精确资产；
- Git 远端提交、Release 标签目标和本地预期提交一致。

Release 说明至少包含主要变化、安装/升级方式、支持系统、SmartScreen/签名状态、文件大小、SHA-256 和验证结果。

## 12. Git 工作规范

- 默认从最新 `main` 创建 `codex/<topic>` 分支；用户明确要求直接提交到 `main` 时再遵循其要求。
- 不使用 force push，不执行 `git reset --hard`，不回滚用户未提交修改。
- 一个提交处理一个清晰主题，提交信息使用简洁的 Conventional Commit 风格。
- 只暂存当前任务文件；提交前再次运行 `git diff --cached --name-status`。
- 推送后用 `git ls-remote` 或 GitHub API 验证远端提交，不以本地 push 输出作为唯一证据。
- 网络连接失败时可以在确认本机代理可用后重试 `127.0.0.1:7890`，但不得打印或写入凭据。

## 13. 机密与隐私

- 禁止提交 API 密钥、Token、Cookie、个人路径、私人媒体、账号信息或包含隐私的日志。
- 官网只能调用无需密钥的公开 API。
- 准备公开仓库或 Release 前，检查当前文件及 Git 历史是否存在凭据泄漏。
- 不要在测试输出或最终说明中打印环境变量和认证信息。

## 14. 项目路线图

以下是规划优先级，不代表普通任务可以自动扩大到全部范围：

### P0：可靠性与可复现发布

- 增加 GitHub Actions：Python 3.12 单元测试、网站测试、版本一致性检查。
- 建立单一发布元数据来源，减少 HTML、JavaScript、Inno Setup 和测试中的手工重复。
- 增加安装包资产清单与 SHA-256 自动生成/校验。
- 为覆盖安装、更新器重定向和用户数据保留增加自动化回归。

### P1：识别质量基线

- 建立匿名或可公开的固定校准数据集与指标报告。
- 固化长回合召回率、误检率和端到端耗时基线。
- 为不同机位、单双打、30/60 FPS、1080p/4K 建立回归矩阵。
- 把算法参数变化与真实样片结果绑定，避免只优化单个视频。

### P2：性能与安装体验

- 继续缩小 Light 安装包并记录各组件体积。
- 验证 DirectML、CUDA、TensorRT 和 CPU 回退的真实端到端收益。
- 优化首次启动、硬件检测、错误说明和更新下载体验。
- 在条件具备时加入代码签名；在此之前持续明确 SmartScreen 风险和哈希校验。

### P3：产品与平台扩展

- 改善复核时间线、批量选择和异常片段解释。
- 在不破坏 Windows 主路径的前提下评估 Linux/macOS 媒体后端。
- 只有在端到端净收益可重复达到门槛时才引入 NPU 插件。
- 继续扩充球场主题，但所有概念创作与真实场馆必须清晰标注。

## 15. 任务完成报告

最终回复应先说明用户可见结果，再给出验证证据，并明确剩余风险。至少包括：

- 修改了什么；
- 运行了哪些测试及结果；
- 是否验证真实 GUI、安装包、公开 Release 或官网；
- 是否保留了无关工作区修改；
- 仍未验证的机器、素材、浏览器或发布环节。

不要把“代码已修改”“构建成功”或“命令退出 0”单独当作最终完成证据。
