#!/bin/bash

set -e


aptPackageList=(
    # For development
    git                     # For version control
    python-pip              # Python package management
    trickle                 # For bandwidth-limiting insync

    # Applications
    spectacle               # For screenshots
    arandr                  # Monitor Settings
    qdirstat                # For exploring filesystems easily
    pavucontrol             # Easily work with sound devices
    nautilus                # For file manager
    chromium-browser        # Chrome

    # Configuration
    gnome-disks             # For editing fstab
    lxappearance            # For GTK themes
    nitrogen                # For setting wallpapers

    # awesome-wm specific things
    awesome                 # The actual window manager
    pasystray               # Sound Widget
    network-manager-gnome   # For wifi and network info
    blueman                 # For bluetooth stuff
    parcellite              # A clipboard manager
    compton                 # For drop-shadowsz
    xautolock               # For locking my window within a timespan
    i3lock                  # For the lockscreen
    rofi                    # For launching programs (Windows+P)
    gnome-system-monitor    # For task manager
)

pacmanPackageList=(
    # Manjaro specific installs
    gnome-terminal

    # For development
    git                     
    python-pip              


    # Applications
    spectacle               
    arandr                  
    pavucontrol             
    nautilus                

    # Configuration
    lxappearance            
    nitrogen                

    # awesome-wm specific things
    awesome                 
    pasystray         
    cbatticon

    # network-manager-gnome   
    blueman                 
    parcellite              
    compton                 
    xautolock               
    i3lock                  
    rofi                    
    gnome-system-monitor    
)
pacaurPackageList=(
    trickle
    qdirstat
    google-chrome
    nautilus-terminal
    gnome-disks
)


# Install packages, based on the OS
if hash apt 2>/dev/null; then
    pip install --user nautilus-terminal
    sudo apt-get update && sudo apt-get upgrade 
    sudo apt install --assume-yes ${aptPackageList[@]}
else
    sudo pacman -Syu --noconfirm # Update lists
    sudo pacman -S --noconfirm pacaur
    sudo pacman -S --noconfirm ${pacmanPackageList[@]}
    pacaur -S --noconfirm ${pacaurPackageList[@]}
fi  
