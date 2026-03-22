# 录屏视频敏感信息自动脱敏工具

一键定义需要脱敏的文字（身份证号、手机号、姓名等），通过本地 OCR + ffmpeg 自动检测并模糊处理视频中的敏感信息。全程本地运行，数据不上传。

## User Review Required

> [!IMPORTANT]
> **依赖安装**：需要新增几个 Python 包（`opencv-python`, `pytesseract`）和 Tesseract 中文语言包（`chi_sim`）。这些都通过 `brew` 和 `pip` 安装到本地虚拟环境，不会影响全局环境。

> [!IMPORTANT]
> **设计选择 — 智能采样 vs 逐帧 OCR**：录屏视频中文字通常是静止的（同一页面停留数秒）。工具默认每秒采样 2 帧进行 OCR，如果相邻帧检测结果一致则跳过，大幅提升速度。用户可在配置中调整采样率。

> [!IMPORTANT]
> **模糊方式**：默认使用高斯模糊（`boxblur`），也支持马赛克（`pixelize`）和纯色覆盖三种模式。用户可在配置文件中切换。

## Proposed Changes

### Python 项目骨架

#### [NEW] [requirements.txt](file:///Users/shisaq/Coding/video-censor/requirements.txt)
定义依赖：`opencv-python`, `pytesseract`, `pyyaml`

#### [NEW] [censor_config.yaml](file:///Users/shisaq/Coding/video-censor/censor_config.yaml)
用户配置文件，定义需要脱敏的信息：

```yaml
# 正则匹配模式（自动检测）
patterns:
  - name: 手机号
    regex: "1[3-9]\\d{9}"
  - name: 身份证号
    regex: "\\d{17}[\\dXx]"
  - name: 邮箱
    regex: "[\\w.+-]+@[\\w-]+\\.[\\w.]+"

# 精确关键词匹配（直接指定要打码的文字）
keywords:
  - "张三"
  - "李四"
  - "某某公司"

# 处理参数
settings:
  sample_fps: 2          # 每秒采样帧数，越高越精确但越慢
  blur_mode: gaussian     # gaussian | pixelate | solid_color
  blur_strength: 30       # 模糊强度
  blur_padding: 10        # 模糊区域在文字边界外扩展的像素数
  ocr_lang: chi_sim+eng   # Tesseract 语言（中文简体 + 英文）
  confidence_threshold: 40 # OCR 置信度阈值（0-100）
```

---

### 核心脚本

#### [NEW] [video_censor.py](file:///Users/shisaq/Coding/video-censor/video_censor.py)
主脚本，约 300 行 Python 代码，核心流程：

1. **帧采样**：用 OpenCV 按 `sample_fps` 抽取关键帧
2. **OCR 文字检测**：用 pytesseract 的 `image_to_data()` 获取每个文字的坐标和内容
3. **敏感信息匹配**：对 OCR 结果用正则和关键词匹配，筛出需要脱敏的文字区域
4. **时间轴追踪**：将检测到的区域按时间段合并（相邻帧中同一位置的文字合并为一个时间段）
5. **ffmpeg 滤镜生成**：根据检测结果生成 ffmpeg `drawbox` / `boxblur` 滤镜链
6. **输出视频**：调用 ffmpeg 一次性处理整个视频，输出脱敏后的文件

CLI 用法：
```bash
python video_censor.py input.mp4                          # 使用默认配置
python video_censor.py input.mp4 -c my_config.yaml        # 指定配置文件
python video_censor.py input.mp4 -o output.mp4            # 指定输出文件
python video_censor.py input.mp4 --preview                # 预览模式（标注但不模糊）
python video_censor.py input.mp4 --dry-run                # 仅输出检测到的敏感信息，不处理
```

关键技术点：
- 使用 `pytesseract.image_to_data(output_type=Output.DICT)` 获取文字坐标
- 关键词匹配时将相邻 OCR word 拼接后一起搜索，处理 Tesseract 把中文拆分成多个 word 的情况
- 区域追踪使用 IoU（Intersection over Union）判断相邻帧中是否为同一文字区域
- ffmpeg 滤镜使用 `enable='between(t,start,end)'` 控制时间段

---

### 便捷脚本 & 文档

#### [NEW] [run.sh](file:///Users/shisaq/Coding/video-censor/run.sh)
一键脚本：自动检查和安装依赖 → 激活虚拟环境 → 运行 `video_censor.py`

#### [NEW] [README.md](file:///Users/shisaq/Coding/video-censor/README.md)
使用说明文档，包含：安装方式、配置说明、用法示例、常见问题

## Verification Plan

### 自动化测试
由于这是全新项目、且核心流程依赖实际视频和 OCR 结果，适合功能测试而非单元测试：

1. **用 ffmpeg 生成一段包含敏感文字的测试视频**：
   ```bash
   ffmpeg -f lavfi -i color=c=white:s=1280x720:d=5 \
     -vf "drawtext=text='手机号 13812345678':fontsize=36:fontcolor=black:x=100:y=100, \
          drawtext=text='张三':fontsize=36:fontcolor=black:x=100:y=200" \
     -c:v libx264 -t 5 test_input.mp4
   ```
2. **运行工具处理该测试视频**：
   ```bash
   python video_censor.py test_input.mp4 --dry-run
   ```
3. **验证 `--dry-run` 输出**确实检测到了手机号和姓名「张三」

### 手动验证
1. 用户提供一段真实录屏视频，运行 `python video_censor.py your_video.mp4 --preview` 查看检测到的文字区域是否正确
2. 确认后运行 `python video_censor.py your_video.mp4` 生成脱敏视频，检查模糊效果
