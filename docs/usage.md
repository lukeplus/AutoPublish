# AutoPublish 使用手册

AutoPublish 当前支持 B 站和抖音。命令入口是 `autopublish`，平台名填写 `bilibili` 或 `douyin`。

## 安装

```bash
pip install .
python -m playwright install chromium
autopublish --help
```

开发调试时可以使用 editable 安装：

```bash
pip install -e .
```

生成本地 wheel 和源码包：

```bash
python -m pip install build
python -m build
```

环境要求：

- Python 3.10 或更高版本
- 能正常访问目标平台网络接口
- 抖音发布依赖浏览器自动化，需要本机 Chrome 或 Playwright Chromium

## 配置

复制模板：

```bash
cp config.example.yaml autopublish.yaml
```

默认会依次查找：

1. `autopublish.yaml`
2. `autopublish.yml`
3. `config.yaml`
4. `config.yml`

也可以显式指定：

```bash
autopublish -c ./autopublish.yaml check douyin
```

通用字段：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `credentials_dir` | 凭证保存目录 | `~/.autopublish/credentials` |

B 站字段：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `bilibili.human_type2` | 默认主区，`1010=知识区`，`1026=健康` | `1010` |
| `bilibili.tags` | 默认标签列表 | `[]` |
| `bilibili.copyright` | 默认版权类型，`1=自制`、`2=转载` | `1` |
| `bilibili.limit` | 上传分片并发数 | `3` |
| `bilibili.line` | 上传线路，可选 `bda2`、`qn`、`ws` | 自动 |

抖音字段：

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `douyin.tags` | 默认标签列表 | `[]` |
| `douyin.headless` | 是否使用无头浏览器 | `false` |
| `douyin.channel` | 优先使用的浏览器 channel，例如 `chrome` | `chrome` |
| `douyin.timeout` | 页面操作超时时间，单位秒 | `120` |

## 登录和凭证

B 站：

```bash
autopublish login bilibili
autopublish check bilibili
```

抖音：

```bash
autopublish login douyin
autopublish check douyin
```

多账号：

```bash
autopublish login douyin --account work
autopublish check douyin --account work
```

凭证会保存到 `credentials_dir`。默认账号文件名分别为 `bilibili_default.json`、`douyin_default.json`；指定账号会保存为 `<platform>_<account>.json`。

## 单个上传

B 站最小命令：

```bash
autopublish upload bilibili ./video.mp4 --title "标题"
```

抖音最小命令：

```bash
autopublish upload douyin ./video.mp4 --title "标题"
```

B 站完整示例：

```bash
autopublish upload bilibili ./video.mp4 \
  --title "AutoPublish 演示视频" \
  --desc "这是一个上传示例" \
  --tags "自动发布,演示,工具" \
  --human-type2 1010 \
  --cover ./cover.jpg \
  --cover43 ./cover43.jpg \
  --copyright 1 \
  --season-id 123456 \
  --account default
```

抖音完整示例：

```bash
autopublish upload douyin ./video.mp4 \
  --title "AutoPublish 演示视频" \
  --desc "这是一个上传示例" \
  --tags "自动发布,演示,工具" \
  --cover ./cover.jpg \
  --scheduled-time 1700000000 \
  --account default
```

参数说明：

| 参数 | 平台 | 必填 | 说明 |
|------|------|------|------|
| `platform` | 全部 | 是 | `bilibili` 或 `douyin` |
| `video` | 全部 | 是 | 视频文件路径 |
| `--title` | 全部 | 是 | 视频标题 |
| `--desc` | 全部 | 否 | 视频简介 |
| `--tags` | 全部 | 否 | 标签，逗号分隔 |
| `--cover` | 全部 | 否 | 封面图片路径 |
| `--scheduled-time` | 全部 | 否 | 定时发布时间，10 位时间戳 |
| `--account` | 全部 | 否 | 使用哪个登录账号，默认 `default` |
| `--human-type2` | B 站 | 否 | 主区，例如 `1010=知识区`、`1026=健康` |
| `--cover43` | B 站 | 否 | 4:3 封面图片路径 |
| `--copyright` | B 站 | 否 | `1=自制`、`2=转载` |
| `--source` | B 站 | 否 | 转载来源，通常在 `--copyright 2` 时填写 |
| `--season-id` | B 站 | 否 | 合集 ID，上传成功后会尝试加入合集 |

抖音定时发布时间必须大于当前时间 2 小时。

## 批量上传

复制模板：

```bash
cp tasks.example.yaml tasks.yaml
```

执行：

```bash
autopublish batch ./tasks.yaml
```

指定默认账号：

```bash
autopublish batch ./tasks.yaml --account work
```

任务文件格式：

```yaml
tasks:
  - platform: bilibili
    video: /path/to/video1.mp4
    title: "视频标题1"
    description: "视频简介"
    tags:
      - 标签1
      - 标签2
    human_type2: 1010

  - platform: douyin
    video: /path/to/douyin-video.mp4
    title: "抖音视频标题"
    description: "抖音视频简介"
    tags:
      - 自动发布
      - 抖音
    cover: /path/to/douyin-cover.jpg
    scheduled_time: 1700000000
```

任务字段：

| 字段 | 平台 | 必填 | 说明 |
|------|------|------|------|
| `platform` | 全部 | 否 | 平台名，默认 `bilibili` |
| `video` | 全部 | 是 | 视频文件路径 |
| `title` | 全部 | 是 | 视频标题 |
| `description` | 全部 | 否 | 视频简介 |
| `tags` | 全部 | 否 | 标签数组 |
| `cover` | 全部 | 否 | 封面图片路径 |
| `scheduled_time` | 全部 | 否 | 定时发布时间，10 位时间戳 |
| `account` | 全部 | 否 | 当前任务使用的账号 |
| `human_type2` | B 站 | 否 | 主区，`1010=知识区`，`1026=健康` |
| `cover43` | B 站 | 否 | 4:3 封面图片路径 |
| `copyright` | B 站 | 否 | `1=自制`、`2=转载` |
| `source` | B 站 | 否 | 转载来源 |
| `dynamic` | B 站 | 否 | 空间动态文案 |
| `season_id` | B 站 | 否 | 合集 ID |

批量任务按顺序串行执行。单个任务失败后，后续任务仍会继续，结束时会输出成功数、失败数和总任务数。

## B 站主区查询

```bash
autopublish categories
```

当前内置主区：

| human_type2 | 名称 |
|-------------|------|
| `1010` | 知识区 |
| `1026` | 健康 |

`human_type2` 可以写数字，也可以写名称，例如 `知识区`、`健康`。为了兼容历史任务，`21`、`36`、`122`、`188`、`228` 会映射到 `1010`。

## 常见问题

### 抖音提示无法启动浏览器

先执行：

```bash
python -m playwright install chromium
```

或安装本机 Chrome，并在配置里保持 `douyin.channel: chrome`。

### 提示“凭证文件不存在”

先执行：

```bash
autopublish login douyin
```

多账号场景下，确认 `--account` 和登录时使用的一致。

### 提示“凭证无效或已过期”

重新登录即可，旧凭证会被覆盖。

### 提示“视频文件不存在”

检查上传命令中的视频路径或任务文件里的 `video` 字段，确保文件存在且当前用户有读取权限。

### 标题没传导致上传失败

单个上传必须传 `--title`，批量上传必须在任务里写 `title`。

### 主区名称报错

执行 `autopublish categories`，从输出中复制正确名称或直接使用数字 ID。
