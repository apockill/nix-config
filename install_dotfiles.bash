#!/bin/bash
set -e
xfconf-query -c xfce4-session -p /sessions/Failsafe/Client0_Command -t string -sa $HOME/dotfiles/scripts/start_awesome_xfce.bash

