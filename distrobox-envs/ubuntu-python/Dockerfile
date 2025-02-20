FROM quay.io/toolbx/ubuntu-toolbox:24.04

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=all

# Install apt dependencies
RUN apt-get update && \
    apt-get upgrade --yes && \
    apt-get install --yes \
    # Common python dependencies
    python-is-python3 \
    python3-poetry \
    # Fix cv2.imshow
    qtwayland5 \
    # Allows pip installation of Pillow
    libjpeg-dev zlib1g-dev

# Fix genesis visualizations
ENV PYOPENGL_PLATFORM=x11