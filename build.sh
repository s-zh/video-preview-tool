#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# 国内镜像配置
# 可用的 Docker Hub 镜像（选一个快的）
DOCKER_MIRRORS=(
  "docker.m.daocloud.io"
  "dockerhub.timeweb.cloud"
  "mirror.ccs.tencentyun.com"
)
# 可选的 apt 镜像（Debian 源）
APT_MIRROR=""
# 可选的 pip 镜像
PIP_INDEX=""

# 测试 Docker Hub 连通性
echo "==> 测试 Docker Hub 连通性..."
if curl -s --connect-timeout 5 https://registry-1.docker.io/v2/ >/dev/null 2>&1; then
  echo "    Docker Hub 可直接访问"
  BASE_IMAGE="python:3.11-slim"
else
  echo "    Docker Hub 不可用，尝试国内镜像..."
  for mirror in "${DOCKER_MIRRORS[@]}"; do
    echo "    尝试 $mirror ..."
    if docker pull "$mirror/library/python:3.11-slim" 2>/dev/null; then
      docker tag "$mirror/library/python:3.11-slim" python:3.11-slim
      BASE_IMAGE="python:3.11-slim"
      echo "    成功从 $mirror 拉取"
      # 国内环境同时配置 apt/pip 镜像
      APT_MIRROR="mirrors.ustc.edu.cn"
      PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
      break
    fi
  done
  if [ -z "$BASE_IMAGE" ]; then
    echo "   错误：所有镜像都不可用，请手动配置 Docker 镜像加速器"
    echo "   参考：https://docs.docker.com/registry/recipes/mirror/"
    exit 1
  fi
fi

echo ""
echo "==> 构建 Docker 镜像..."
BUILD_ARGS=(
  --build-arg "BASE_IMAGE=$BASE_IMAGE"
)
if [ -n "$APT_MIRROR" ]; then
  BUILD_ARGS+=(--build-arg "APT_MIRROR=$APT_MIRROR")
fi
if [ -n "$PIP_INDEX" ]; then
  BUILD_ARGS+=(--build-arg "PIP_INDEX=$PIP_INDEX")
fi

docker build "${BUILD_ARGS[@]}" -t video-preview-tool:latest ./app

echo ""
echo "==> 导出镜像..."
docker save video-preview-tool:latest | gzip > video-preview-tool.tar.gz

echo ""
echo "==> 构建完成！"
echo "    镜像文件：video-preview-tool.tar.gz"
echo ""
echo "在其他机器导入："
echo "  docker load < video-preview-tool.tar.gz"
echo ""
echo "硬件加速（自动检测）："
echo "  Docker 内 Intel/AMD → 挂载 /dev/dri"
echo "  Docker 内 NVIDIA  → 需要 nvidia-container-toolkit + --gpus all"
echo "  macOS 原生运行    → 自动使用 VideoToolbox"
echo "  Windows 原生运行  → 自动使用 CUDA / D3D11VA"
echo ""
echo "运行容器（Intel/AMD GPU）："
echo "  docker compose up -d"
echo "  或"
echo "  docker run -d --name video-preview-tool \\"
echo "    -p 8080:8080 \\"
echo "    -v /:/mnt/host:rw \\"
echo "    --device /dev/dri:/dev/dri \\"
echo "    -e CONCURRENCY=4 \\"
echo "    --restart unless-stopped \\"
echo "    video-preview-tool:latest"
echo ""
echo "运行容器（NVIDIA GPU，需提前安装 nvidia-container-toolkit）："
echo "  docker run -d --name video-preview-tool \\"
echo "    -p 8080:8080 \\"
echo "    -v /:/mnt/host:rw \\"
echo "    --gpus all \\"
echo "    -e CONCURRENCY=4 \\"
echo "    --restart unless-stopped \\"
echo "    video-preview-tool:latest"
