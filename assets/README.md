# 资源目录

- `icons/`：Windows 可执行文件、安装程序和运行时窗口使用的像素风图标。
- `models/`：程序离线运行所需的姿态与球拍检测模型。

源码和打包程序统一通过 `tennis_video_helper.resources.asset_path` 查找资源。可使用 `TVH_ICON_DIR` 或 `TVH_MODEL_DIR` 覆盖默认目录，方便在其他项目中复用算法而不复制整个仓库。
