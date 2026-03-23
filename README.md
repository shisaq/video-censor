# 🔒 Video Censor — 录屏视频敏感信息自动脱敏

一键定义需要脱敏的文字（身份证号、手机号、姓名等），通过本地 OCR + ffmpeg 自动检测并模糊处理视频中的敏感信息。**全程本地运行，数据不上传**。

## 快速开始

```bash
# 1. 一键运行（自动安装依赖）
chmod +x run.sh
./run.sh your_video.mp4

# 2. 或手动运行
source .venv/bin/activate
python video_censor.py your_video.mp4
```

## 用法

```bash
# 使用默认配置
python video_censor.py input.mp4

# 指定配置文件
python video_censor.py input.mp4 -c my_config.yaml

# 指定输出文件
python video_censor.py input.mp4 -o output.mp4

# 预览模式（红框标注检测区域，不做模糊）
python video_censor.py input.mp4 --preview

# 仅检测输出敏感信息，不处理视频
python video_censor.py input.mp4 --dry-run
```

## 配置说明

编辑 `censor_config.yaml` 定义需要脱敏的信息：

```yaml
# 正则匹配模式（自动检测）
patterns:
  - name: 手机号
    regex: "1[3-9]\\d{9}"
  - name: 身份证号
    regex: "\\d{17}[\\dXx]"
  - name: 邮箱
    regex: "[\\w.+-]+@[\\w-]+\\.[\\w.]+"

# 精确关键词（姓名、公司名等）
keywords:
  - "张三"
  - "某某公司"

# 处理参数
settings:
  output_fps: 10          # 输出帧率，低于原始时先降帧再处理，大幅提速
  sample_fps: null        # null = 跟随 output_fps，每帧都分析（推荐）
  blur_mode: gaussian     # gaussian | pixelate | solid
  blur_strength: 30       # 模糊强度
  blur_padding: 10        # 模糊区域外扩像素
  ocr_lang: chi_sim+eng   # OCR 语言
  confidence_threshold: 40  # OCR 置信度阈值（0-100）
  iou_threshold: 0.5      # 相邻帧同一区域判定阈值
```

### 关键参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `output_fps` | `10` | 输出视频帧率。设为低于原始帧率的值可大幅提速（如 30fps→10fps，工作量减少 2/3）。设为 `null` 保持原始帧率 |
| `sample_fps` | `null` | OCR 采样帧率。`null` 表示跟随 `output_fps`，确保每帧都被分析，不遗漏敏感信息 |
| `blur_mode` | `gaussian` | `gaussian`（高斯模糊）、`pixelate`（像素化）、`solid`（纯色覆盖） |
| `confidence_threshold` | `40` | OCR 置信度阈值，低于此值的识别结果会被忽略，调高可减少误检 |
| `iou_threshold` | `0.5` | 相邻帧区域重叠度阈值，仅合并位置高度重合的连续帧，避免滚动时误合并 |

## 工作流程

1. **降帧预处理** — 若 `output_fps` 低于原始帧率，先用 ffmpeg 降帧，减少后续工作量
2. **逐帧 OCR** — 使用 Tesseract 识别每帧中的文字及位置
3. **敏感匹配** — 通过正则表达式和关键词过滤敏感信息
4. **区域合并** — 将连续帧中位置相同的区域合并（无时间缓冲，精确到帧）
5. **视频处理** — 调用 ffmpeg 对目标区域进行模糊处理

## 依赖

- Python 3.10+
- ffmpeg (`brew install ffmpeg`)
- Tesseract (`brew install tesseract tesseract-lang`)
- Python 包: opencv-python, pytesseract, pyyaml
