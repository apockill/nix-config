#!/usr/bin/env bash
set -e
cd builds/nautilus-terminal

##### First build nautilus-python
# Dependencies for nautilus-python
sudo apt-get -y install python-gtk2-dev python-gobject-2-dev python-gnome2-dev libnautilus-extension-dev gnome-common gtk-doc-tools
# Get nautilus-python and build it
git clone https://github.com/GNOME/nautilus-python.git
cd nautilus-python
sh autogen.sh
make
sudo make install
cd ..

##### Next, build nautilus-terminal
# Get nautilus-terminal and build it
git clone https://github.com/flozz/nautilus-terminal.git
cd nautilus-terminal

# Do the build
sudo pip install .
sudo bash tools/update-extension-system.sh install

nautilus -q
