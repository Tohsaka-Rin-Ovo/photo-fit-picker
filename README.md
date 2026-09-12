# 拾影 Photo Fit Picker

一个本地运行的 Windows / macOS 照片初筛工具。它会读取照片的拍摄时间和视觉特征，把连拍、同机位的近似照片整理成组，再由用户逐组确认保留项。

## 下载

前往 [GitHub Releases](https://github.com/Tohsaka-Rin-Ovo/photo-fit-picker/releases) 下载：

- Windows：`PhotoFitPicker-Windows-x64-Setup.exe`
- macOS：`PhotoFitPicker-macOS.dmg`

安装包暂未配置商业代码签名，Windows SmartScreen 或 macOS Gatekeeper 可能提示未知开发者。`SHA256SUMS.txt` 可用于核对下载文件是否完整。

## 当前功能

- 拖入或选择整个照片文件夹，递归扫描常规图片、HEIC 和主流相机 RAW。
- 根据 EXIF 时间、感知哈希和色彩分布对近似照片分组。
- 以清晰度和曝光为依据标出每组推荐照片，但不会自动移动。
- 支持单张保留/排除、本组全部保留/排除、仅保留推荐照片。
- 点击缩略图可打开大图，并在组内前后翻看和继续标记。
- 每张照片可独立勾选，选择状态可跨照片组保留。
- 底部批量栏支持将所选照片标为保留/排除、移动到指定文件夹或移到系统回收站。
- `Ctrl+A` / `Command+A` 选择当前照片组，`Esc` 清空所有选择。
- 将确认保留的原文件移动到自定义文件夹；遇到同名文件自动改名，不覆盖。
- 保存移动历史，并支持撤销最近一次批量移动。
- “排除”只记录审核状态，不删除文件；程序不会自动删除任何照片。
- 用户可逐张选择“移到回收站”，每次必须经过确认弹窗，并由系统回收站保留恢复能力。
- 所有分析在电脑本地完成，不上传照片。

## 图片格式

常规格式包括 JPG、JPEG、PNG、WebP、BMP、TIFF、HEIC 和 HEIF。

RAW 通过 LibRaw/rawpy 读取，目前纳入扫描的格式包括 Canon CR2/CR3/CRW、Nikon NEF/NRW、Sony ARW/SR2/SRF、Fujifilm RAF、Adobe DNG、Panasonic RW2/RWL、Olympus ORF/ORI、Pentax PEF/PTX、Samsung SRW、Sigma X3F，以及 3FR、DCR、ERF、FFF、GPR、IIQ、KDC、MEF、MOS、MRW、R3D 等格式。

程序优先使用 RAW 内嵌预览图进行快速分析；没有预览图时才进行半尺寸显影。移动、撤销和回收站操作针对完整 RAW 原文件，不会把预览图写回原文件。新相机或厂商特殊 RAW 变体能否读取取决于安装包所带的 LibRaw 版本。

## 运行源码

需要 Python 3.9 或更高版本。

```bash
python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
python -m pip install -e .
python -m photo_fit_picker.main
```

## 使用流程

1. 选择或拖入照片文件夹。
2. 先使用默认的 84% 相似度和 90 秒时间范围，点击“开始分析”。
3. 在左侧逐组查看照片；“推荐”表示组内清晰度和曝光综合得分最高。
4. 标记需要保留的照片，设置“已筛选”文件夹，然后点击“移动已保留照片”。
5. 如需恢复，点击顶部的返回箭头撤销最近一次移动。

点击照片上的回收站图标会出现确认弹窗。只有用户明确确认后，该张照片才会进入系统废纸篓/回收站；程序不提供永久删除或自动删除功能。

批量移到回收站同样必须经过确认弹窗。批量移动只处理明确勾选的照片，不会顺带移动其他已保留或已排除的照片。

相似度越高，分组越严格；误把不同画面放在一起时调高，连拍没有聚到一起时调低。移动前请保留独立备份，尤其是在第一次处理重要照片时。

## 打包

macOS：

```bash
chmod +x scripts/build-macos.sh
./scripts/build-macos.sh
```

Windows：双击 `scripts\build-windows.bat`，或在命令提示符中运行它。

GitHub Actions 配置位于 `.github/workflows/build.yml`。手动运行工作流会生成临时构建产物；推送 `v*` 标签会自动创建 GitHub Release，上传 Windows 安装程序、macOS DMG 和 SHA-256 校验文件。PyInstaller 必须在目标操作系统上构建，因此不能只在 Mac 上直接生成可靠的 Windows 程序。

## 第一版算法边界

当前算法适合连拍、同机位轻微变化、人物表情不同等近似画面。它不做人物身份识别，也不会理解“这张构图更有故事感”。后续可增加人脸闭眼检测、重复截图检测、CLIP 语义聚类，以及 RAW+JPEG/XMP 配对管理。
