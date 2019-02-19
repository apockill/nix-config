#!/usr/bin/env bash
set -e
cd builds/i3lock

INSTALL_PATH=/usr/local/i3lock-color

if [ -e $INSTALL_PATH ]; then
   echo "i3lock already built. Skipping build & installation!"
    exit 0
fi

# Build and install i3lock color
mkdir i3lock
cd i3lock
git clone https://github.com/PandorasFox/i3lock-color.git
cd i3lock-color

# Install dependencies for building i3lock
sudo apt --assume-yes install libev-dev \
    autoconf \
    libcairo-dev \
    libxcb-composite0 \
    libxcb-composite0-dev \
    libxcb-xinerama0 \
    libxcb-randr0 \
    libxcb-randr0-dev \
    libxcb-xinerama0-dev \
    libxcb-xkb-dev \
    libxcb-image0-dev \
    libxcb-util-dev \
    libxkbcommon-x11-dev \
    libjpeg-turbo8-dev \
    libpam0g-dev \
    libxcb-xrm-dev

# Build
autoreconf -i && ./configure && make

# Install to /usr/local/i3lock-color
cd ..

sudo ln -s $PWD/i3lock-color $INSTALL_PATH

