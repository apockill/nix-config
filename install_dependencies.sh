#!/bin/bash

set -e


aptPackageList=(
    # For development
    git                     # For version control
    python-pip              # Python package management

    # Applications
    arandr                  # Monitor Settings
    qdirstat                # For exploring filesystems easily
    pavucontrol             # Easily work with sound devices
    nautilus                # For file manager
    insync                  # For google drive file syncing

    # Theming
    lxappearance            # For GTK themes
    
    # awesome-wm specific things
    pasystray               # Sound Widget
    network-manager-gnome   # For wifi and network info
    blueman                 # For bluetooth stuff
    compton                 # For drop-shadows
    xautolock               # For locking my window within a timespan
    i3lock                  # For the lockscreen
    rofi                    # For launching programs
    gnome-system-monitor    # For task manager
)

python2PackageList=(
    nautilus-terminal       # For terminals within nautilus
)
# Install apt packages
sudo apt install --assume-yes ${aptPackageList[@]}

# Install
pip install ${python2PackageList[@]}