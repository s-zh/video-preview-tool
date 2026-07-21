# Video Preview Tile Generator

为目录下所有视频文件批量生成平铺预览图（sprite sheet），支持硬件加速，提供浏览器 UI 和 REST API。

## 功能特性

- **批量生成** — 扫描指定目录（含子目录），自动识别视频文件，并行生成预览图
- **平铺预览** — 每张预览图由多帧缩略图拼成网格（默认 6×4），可自定义行列数
- **时间戳叠加** — 每帧缩略图左上角叠加对应时间，可选关闭
- **硬件加速** — 自动检测并启用 GPU 解码：
  - Linux: VAAPI（Intel/AMD）、CUDA（NVIDIA）
  - macOS: VideoToolbox（Apple Silicon & Intel）
  - Windows: CUDA / D3D11VA
- **并行处理** — 可配置并发数，充分利用多核 CPU 和 GPU
- **任务管理** — 支持查询进度、取消任务、删除任务，刷新页面不丢失
- **失败重试** — 每个视频独立追踪状态，失败文件可一键重试
- **预览下载** — 所有预览图打包为 ZIP 一键下载
- **Docker 部署** — 一键容器化，支持 `/dev/dri` 透传实现硬件加速

## 效果预览

每张预览图是一个 JPG 文件，与原视频放在同一目录，文件名 `{视频名}.jpg`。

```
默认规格：
  ┌──────┬──────┬──────┬──────┬──────┬──────┐
  │00:00 │00:30 │01:00 │01:30 │02:00 │02:30 │
  ├──────┼──────┼──────┼──────┼──────┼──────┤
  │03:00 │03:30 │04:00 │04:30 │05:00 │05:30 │
  ├──────┼──────┼──────┼──────┼──────┼──────┤
  │06:00 │06:30 │07:00 │07:30 │08:00 │08:30 │
  ├──────┼──────┼──────┼──────┼──────┼──────┤
  │09:00 │09:30 │10:00 │10:30 │11:00 │11:30 │
  └──────┴──────┴──────┴──────┴──────┴──────┘
  缩略图尺寸: 320×180  网格: 6×4 → 预览图: 1920×720
```

## 快速开始

### Docker 部署（推荐）

```bash
docker compose up -d
```

更新镜像：

```bash
docker compose pull && docker compose up -d
```

或手动运行：

```bash
docker run -d --name video-preview \
  -p 8080:8080 \
  -v /:/mnt/host:rw \
  --device /dev/dri:/dev/dri \
  -e CONCURRENCY=4 \
  --restart unless-stopped \
  ghcr.io/s-zh/video-preview-tool:latest
```

然后打开浏览器访问 `http://<主机IP>:8080`。

### 原生运行（macOS / Linux）

```bash
# 安装依赖
pip install -r app/requirements.txt

# 启动服务
BASE_PATH=/ CONCURRENCY=4 uvicorn main:app --host 0.0.0.0 --port 8080

# Windows PowerShell:
# $env:BASE_PATH="/"; $env:CONCURRENCY=4; uvicorn main:app --host 0.0.0.0 --port 8080
```

### 构建镜像

```bash
bash build.sh
# 构建完成后导出为 tar.gz，可在离线环境 docker load 导入
```

国内网络环境脚本会自动使用 Docker Hub 镜像加速（DaoCloud / TimeWeb / Tencent）及 APT/PyPI 国内源。

## 使用指南

### 1. 浏览目录
在页面"选择目录"区域浏览文件系统，点击目录进入子目录。

### 2. 扫描视频
进入目标目录后点击"扫描视频"，自动递归扫描所有视频文件（支持的格式：`.mp4 .avi .mov .mkv .wmv .flv .webm .m4v .mpg .mpeg .ts .3gp`）。

### 3. 选择文件
勾选需要生成预览图的视频文件，支持全选。

### 4. 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 网格列 | 6 | 平铺网格的列数 |
| 网格行 | 4 | 平铺网格的行数 |
| 缩略图宽 | 320 | 每帧缩略图的宽度（px） |
| 缩略图高 | 180 | 每帧缩略图的高度（px） |
| 显示时间戳 | 开启 | 在每帧左上角叠加时间戳 |

### 5. 生成预览
点击"生成预览图"创建任务，在任务详情中可实时查看处理进度和每个文件的状态。

### 6. 结果管理
- **下载** — 任务完成后点击"下载预览图 (ZIP)"打包所有预览图
- **重试** — 失败的文件可在任务详情中一键重试
- **删除** — 清理任务列表（不影响已生成的图片文件）

## 硬件加速

系统自动检测最佳解码方案，优先级：CUDA > VAAPI > VideoToolbox > D3D11VA > Software。

| 平台 | 加速方案 | 要求 | Docker 额外配置 |
|------|----------|------|----------------|
| Linux Intel | VAAPI | `/dev/dri/renderD128` | `--device /dev/dri:/dev/dri` |
| Linux AMD | VAAPI | `/dev/dri/renderD128` | `--device /dev/dri:/dev/dri` |
| Linux NVIDIA | CUDA | nvidia-smi + 驱动 | `--gpus all` + nvidia-container-toolkit |
| macOS | VideoToolbox | 内置 | 无（不支持 Docker 内） |
| Windows | CUDA / D3D11VA | 相应驱动 | 无（不支持 Docker 内） |

## API 参考

| 方法 | 端点 | 说明 |
|------|------|------|
| `GET` | `/api/config` | 获取服务配置（硬件加速、并发数等） |
| `GET` | `/api/health` | 健康检查 |
| `POST` | `/api/browse` | 浏览目录内容 |
| `POST` | `/api/scan` | 递归扫描目录下的视频文件 |
| `POST` | `/api/start` | 创建预览生成任务 |
| `GET` | `/api/tasks` | 获取所有任务列表 |
| `GET` | `/api/status/{task_id}` | 获取任务详细状态（含每个文件的状态和错误信息） |
| `POST` | `/api/tasks/{task_id}/retry` | 重试任务中失败的文件 |
| `POST` | `/api/cancel/{task_id}` | 取消正在运行的任务 |
| `POST` | `/api/tasks/{task_id}/delete` | 删除任务 |
| `GET` | `/api/download/{task_id}` | 下载任务的预览图 ZIP 包 |

### 启动任务示例

```bash
curl -X POST http://localhost:8080/api/start \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/mnt/host/videos",
    "files": ["/mnt/host/videos/clip1.mp4", "/mnt/host/videos/clip2.mp4"],
    "grid_cols": 6,
    "grid_rows": 4,
    "thumb_width": 320,
    "thumb_height": 180,
    "show_timestamps": true
  }'

# 返回: {"task_id": "uuid-string"}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BASE_PATH` | `/mnt/host` | 文件系统浏览的根路径 |
| `CONCURRENCY` | `2` | 最大并行处理的视频数 |
| `PORT` | `8080` | HTTP 监听端口 |
| `DRAWTEXT_FONT` | 自动检测 | 自定义时间戳字体路径 |

## 项目结构

```
├── app/
│   ├── main.py              # FastAPI 后端应用
│   ├── Dockerfile           # Docker 镜像构建文件
│   ├── requirements.txt     # Python 依赖
│   ├── .dockerignore        # Docker 构建忽略规则
│   └── static/              # 前端静态资源
│       ├── index.html       # 主页面
│       ├── app.js           # 前端逻辑
│       └── style.css        # 样式
├── docker-compose.yml       # Docker Compose 编排
├── build.sh                 # 构建脚本（国内镜像适配）
├── .gitignore
└── README.md
```

## 技术栈

- **后端**: Python 3.11 + FastAPI + aiofiles + subprocess
- **前端**: Vanilla JS + CSS（无框架依赖）
- **视频处理**: ffmpeg（drawtext / tile / scale 滤镜）
- **容器**: Docker + docker-compose
- **硬件加速**: VAAPI / CUDA / VideoToolbox / D3D11VA

## 常见问题

### `vainfo` not found

容器内未安装 `vainfo`（`libva-utils`），但不影响 VAAPI 解码。可通过以下命令确认驱动状态：

```bash
docker exec video-preview vainfo
```

如果未安装，请进入容器后安装：

```bash
apt-get update && apt-get install -y libva-utils
```

### 预览图生成失败

1. 检查视频文件是否损坏：`ffprobe <视频路径>`
2. 查看任务详情中的错误信息，点击失败文件展开具体错误
3. 若为 ffmpeg 错误，可在容器内手动执行相同命令排查

### 国内网络构建失败

`build.sh` 已内置 Docker Hub、APT、PyPI 的国内镜像切换逻辑。如果仍有问题，可手动设置：

```bash
# 使用阿里云 PyPI 镜像
docker build --build-arg PIP_INDEX=https://mirrors.aliyun.com/pypi/simple/ -t video-preview-tool:latest ./app
```

## License

MIT
