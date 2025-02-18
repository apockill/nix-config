FROM quay.io/toolbx/ubuntu-toolbox:24.04

# Install apt dependencies
RUN apt-get update && \
    apt-get upgrade --yes && \
    apt-get install --yes \
    # Common python dependencies
    python-is-python3 \
    python3-poetry