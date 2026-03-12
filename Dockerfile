FROM python:3.11

# 运行期禁止 uv 触发隐式同步/下载，避免离线环境访问外网
ENV UV_NO_SYNC=1 \
    UV_PYTHON_DOWNLOADS=never

# 安装 Node.js（满足 >=18）及 Python 编译依赖
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm build-essential curl \
  && rm -rf /var/lib/apt/lists/*

# 从 uv 官方镜像复制 uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# 先复制依赖描述文件以利用缓存
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock backend/requirements.txt ./backend/

# 安装依赖（Node + Python）
RUN npm ci \
  && npm ci --prefix frontend \
  && cd backend \
  && uv sync --frozen \
  && uv pip install --python .venv/bin/python -r requirements.txt

# 复制项目源码
COPY . .

EXPOSE 3000 5001

# 同时启动前后端（开发模式）
CMD ["npm", "run", "dev"]
