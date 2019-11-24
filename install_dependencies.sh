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
    google-chrome-stable    # Chrome

    # Theming
    lxappearance            # For GTK themes
    nitrogen                # For setting wallpapers

    # awesome-wm specific things
    awesome                 # The actual window manager
    pasystray               # Sound Widget
    network-manager-gnome   # For wifi and network info
    cbatticon               # Battery icon
    blueman                 # For bluetooth stuff
    parcellite              # A clipboard manager
    compton                 # For drop-shadows
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

    # Theming
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
)

python2PackageList=(
    nautilus-terminal       # For terminals within nautilus
)
# Install packages, based on the OS
if [  -n "$(uname -a | grep Ubuntu)" ]; then
    sudo apt-get update && sudo apt-get upgrade 
    sudo apt install --assume-yes ${aptPackageList[@]}
else
    sudo pacman -S --noconfirm pacaur
    sudo pacman -S --noconfirm ${pacmanPackageList[@]}
    sudo pacaur -S --noconfirm ${pacaurPackageList[@]}
fi  

# Install
pip install --user ${python2PackageList[@]}
