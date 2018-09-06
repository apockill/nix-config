#!/bin/bash

sudo apt install --assume-yes git

packagelist=(

    # Applications
    arandr                  # Monitor Settings
    qdirstat                # For exploring filesystems easily
    pavucontrol             # Easily work with sound devices
    nautilus                # For file manager

    # Theming
    lxappearance            # For GTK themes
    
    # awesome specific things
    pasystray               # Sound Widget
    network-manager-gnome   # For wifi and network info
    blueman                 # For bluetooth stuff
    compton                 # For drop-shadows
    xautolock               # For locking my window within a timespan
    i3lock                  # For the lockscreen
    rofi                    # For launching programs
    gnome-system-monitor    # For task manager
)

# Monitor Settings
sudo apt install --assume-yes ${packagelist[@]}
