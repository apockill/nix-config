#!/bin/bash

sudo apt install --assume-yes git

packagelist=(
    arandr                  # Monitor Settings
    pasystray               # Sound Widget
    network-manager-gnome   # Bluetooth
    compton                 # For drop-shadows
    xautolock               # For locking my window within a timespan
    i3lock                  # For the lockscreen
    rofi                    # For launching programs
    gnome-system-monitor    # For task manager
)

# Monitor Settings
sudo apt install --assume-yes ${packagelist[@]}