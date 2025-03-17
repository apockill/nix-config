FROM quay.io/toolbx/ubuntu-toolbox:24.04

# Useful for writing readable Dockerfiles based on this image
ENV APT_CACHE=/var/cache/apt
ENV PIP_CACHE=/root/.cache/pip
ENV UV_CACHE=/root/.cache/uv

# Set up NVIDIA capabilities
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=all

# Fix genesis visualizations
ENV PYOPENGL_PLATFORM=x11

# Install apt dependencies
RUN --mount=type=cache,target="${APT_CACHE}" \
    apt-get update && \
    apt-get upgrade --yes && \
    apt-get install --yes \
    # Common python dependencies
    python-is-python3 \
    python3-poetry \
    # Fix cv2.imshow
    qtwayland5 \
    # Allows pip installation of Pillow
    libjpeg-dev zlib1g-dev \
    # Allows use of swig, for gymnasium environments
    swig clang

