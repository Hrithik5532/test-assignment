FROM public.ecr.aws/lambda/python:3.11

# Install system dependencies
RUN yum install -y \
    gcc \
    gcc-c++ \
    make \
    cmake \
    ffmpeg \
    pkgconfig \
    python3-devel

# Copy project files
COPY . ${LAMBDA_TASK_ROOT}

# Install Python dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Set handler
CMD ["api_main.handler"]