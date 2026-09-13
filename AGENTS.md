# AGENTS.md

拾影 Photo Fit Picker — 本地优先的 PySide6 桌面应用（Windows/macOS），扫描照片文件夹，按 EXIF 时间、感知哈希和色彩分布分组近似照片，由用户逐组审核保留/排除。Python 3.9+，src-layout 包 `photo_fit_picker`。README 和代码注释以中文为主，回复与文档请保持中文。

## 常用命令

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"   # 安装依赖 + dev（pytest, pyinstaller）

python -m pytest                    # 全部测试（pyproject 已配 pythonpath=src, testpaths=tests）
python -m pytest tests/test_fileops.py::TestClassName::test_name   # 单个测试
python -m photo_fit_picker.main     # 运行应用
```

打包：macOS 用 `scripts/build-macos.sh`（产出 `dist/release/PhotoFitPicker-macOS.dmg`）；Windows 用 `scripts/build-windows.bat`。CI 在 `.github/workflows/build.yml`；PyInstaller 必须在目标 OS 上构建。提交信息使用 conventional commits（`feat:`/`fix:`/`docs:`/`release:` 等）。

## 架构

`src/photo_fit_picker/` 单包，模块边界：

- `main.py` — 入口（`main()`）。
- `models.py` — dataclass 领域对象（`PhotoRecord`, `AnalysisOptions`, `ReviewStatus` 等）。被所有其他模块依赖，自身不依赖 UI/IO。
- `analysis.py` — 扫描、EXIF/rawpy 读取、感知哈希、分组；定义 `SUPPORTED_EXTENSIONS`。纯逻辑，不做文件移动。
- `worker.py` — `AnalysisWorker(QObject)`，把 analysis 包装成 Qt Signal/Slot，支持取消。UI 不直接长跑分析。
- `fileops.py` — 所有文件移动/回收站/撤销历史（`.photo-fit-picker-history.json`）；RAW+同名 JPEG+XMP sidecar 作为关联资产（`LINKED_EXTENSIONS`）整体移动，批次事务失败回滚。
- `organizer.py` — 按日期/GPS 生成整理建议（`OrganizationPlan`），仅预览，不写盘。
- `session.py` — 审核进度持久化到系统应用数据目录（不写入照片文件夹），用文件指纹避免恢复到已替换照片。
- `ui.py` — 全部 PySide6 界面（约 4000 行，是最大的模块）。UI 逻辑不要下沉到其他模块。

测试在 `tests/`（organizer/session/fileops/analysis，纯 pytest，不需要 Qt/显示环境）。

## 硬性安全边界（改动文件操作相关代码前必读）

- 程序**绝不自动删除照片**；移到回收站必须每次经用户确认弹窗，且只走系统回收站，不提供永久删除。
- 任何文件移动必须：先展示方案 → 用户确认 → 记录为可撤销操作（历史文件），失败自动回滚。
- 扫描忽略符号链接；目标与照片当前文件夹相同时必须拦截移动。
- 分析全部本地完成，不上传照片、不联网。
- 所有 UI 文案为中文，跨平台快捷键用 Ctrl/Command 分支。

敏感改动前先读 `README.md` 的功能与安全说明、`ROADMAP.md`（照片安全规则适用于所有阶段）和 `.github/workflows/build.yml`（发布流程）。

## 已知注意点

- 代码需兼容 Python 3.9（`from __future__ import annotations` 已在各模块使用；避免 3.10+ 语法如 match、`X | Y` 运行时类型注解）。
- RAW 读取优先用内嵌预览图，无预览才半尺寸显影；不要把预览图写回原文件。
- UI 中"排除"只记录状态不删文件；"整理"在最终确认前不创建目录。
