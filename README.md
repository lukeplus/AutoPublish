# AutoPublish

AutoPublish 是一个命令行工具，用于把本地视频发布到内容平台。当前版本支持 B 站、抖音和 YouTube：B 站走接口上传，抖音走创作者中心浏览器自动化，YouTube 走官方 Data API。

## 快速开始

### 1. 安装

```bash
pip install .
python -m playwright install chromium
autopublish --help
```

开发调试时可以改用 `pip install -e .`。如果本机已安装 Chrome，抖音默认会优先使用 Chrome；没有 Chrome 时会回退到 Playwright Chromium。

需要生成本地安装包时：

```bash
python -m pip install build
python -m build
```

### 2. 准备配置

```bash
cp config.example.yaml autopublish.yaml
```

`autopublish.yaml` 用于配置凭证目录、B 站默认主区、上传线路、抖音浏览器参数、YouTube OAuth client 等。

### 3. 登录并检查凭证

```bash
autopublish login bilibili
autopublish check bilibili
```

```bash
autopublish login douyin
autopublish check douyin
```

```bash
autopublish login youtube
autopublish check youtube
```

多账号使用 `--account` 区分：

```bash
autopublish login douyin --account work
autopublish check douyin --account work
```

### 4. 上传视频

B 站：

```bash
autopublish upload bilibili ./video.mp4 \
  --title "我的视频" \
  --desc "视频简介" \
  --tags "标签1,标签2" \
  --human-type2 1010
```

抖音：

```bash
autopublish upload douyin ./video.mp4 \
  --title "我的视频" \
  --desc "视频简介" \
  --tags "标签1,标签2"
```

YouTube：

```bash
autopublish upload youtube ./video.mp4 \
  --title "我的视频" \
  --desc "视频简介" \
  --tags "标签1,标签2" \
  --cover ./thumbnail.jpg \
  --privacy-status public
```

定时发布：

```bash
autopublish upload douyin ./video.mp4 \
  --title "定时发布视频" \
  --scheduled-time 1700000000
```

### 5. 批量上传

```bash
cp tasks.example.yaml tasks.yaml
autopublish batch ./tasks.yaml
```

## 常用命令

| 命令 | 用途 |
|------|------|
| `autopublish login bilibili` | 登录 B 站 |
| `autopublish login douyin` | 登录抖音 |
| `autopublish login youtube` | 登录 YouTube |
| `autopublish check douyin` | 检查抖音凭证是否有效 |
| `autopublish upload bilibili ./video.mp4 --title "标题"` | 上传到 B 站 |
| `autopublish upload douyin ./video.mp4 --title "标题"` | 上传到抖音 |
| `autopublish upload youtube ./video.mp4 --title "标题"` | 上传到 YouTube |
| `autopublish batch ./tasks.yaml` | 按 YAML 任务文件批量上传 |
| `autopublish categories` | 查看可用 B 站主区 |

当前内置 B 站主区：

| human_type2 | 名称 |
|-------------|------|
| `1010` | 知识区 |
| `1026` | 健康 |

## 文件说明

| 文件 | 用途 |
|------|------|
| `config.example.yaml` | 配置模板 |
| `tasks.example.yaml` | 批量任务模板 |
| `docs/usage.md` | 完整使用手册 |
| `autopublish.yaml` | 本地配置文件，已被 `.gitignore` 忽略 |
| `tasks.yaml` | 本地批量任务文件，已被 `.gitignore` 忽略 |
| `pyproject.toml` | pip 构建和安装配置 |
| `MANIFEST.in` | 源码包文件清单 |

## 项目结构

```text
src/autopublish/cli.py                 # 命令入口、配置读取、任务编排
src/autopublish/platforms/bilibili.py  # B 站登录、上传、合集、主区逻辑
src/autopublish/platforms/douyin.py    # 抖音登录、检查、上传、定时发布逻辑
src/autopublish/platforms/youtube.py   # YouTube OAuth、上传、定时发布、封面逻辑
```

完整参数、配置字段、批量任务格式和排错说明见 [docs/usage.md](docs/usage.md)。
