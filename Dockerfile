FROM public.ecr.aws/lambda/python:3.11

# Install system dependencies
RUN yum install -y \
    gcc \
    gcc-c++ \
    make \
    cmake \
    pkgconfig \
    python3-devel \
    xz \
    tar

# Install static FFmpeg for ARM64
RUN curl -LO https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz && \
    tar -xJf ffmpeg-release-arm64-static.tar.xz && \
    mv ffmpeg-*-arm64-static/ffmpeg /usr/local/bin/ && \
    mv ffmpeg-*-arm64-static/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg-release-arm64-static.tar.xz ffmpeg-*-arm64-static

WORKDIR ${LAMBDA_TASK_ROOT}

# Copy requirements first (for Docker caching)
COPY requirements.txt .

# Upgrade pip
RUN pip install --upgrade pip

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Lambda handler
CMD ["api_main.handler"]