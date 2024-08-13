# Run this command in order for Ubuntu to not use Super+# to be for the favorites bar, but for whatever I actually want it to do:
# https://askubuntu.com/questions/1160234/customize-super-n-behavior

# Then you have to do that for each number you want to override, 
# by changing "1" to the requisite digit

gsettings set org.gnome.shell.extensions.dash-to-dock hot-keys false


set -e
gsettings set org.gnome.mutter dynamic-workspaces false
gsettings set org.gnome.desktop.wm.preferences num-workspaces 9
for i in {1..4}; do 
  gsettings set "org.gnome.shell.keybindings" "switch-to-application-${i}" "[]"
  gsettings set "org.gnome.desktop.wm.keybindings" "switch-to-workspace-${i}" "['<Super>${i}']"
  gsettings set "org.gnome.desktop.wm.keybindings" "move-to-workspace-${i}" "['<Super><Alt>${i}']"
  gsettings set "org.gnome.shell.extensions.dash-to-dock" "app-hotkey-${i}" "[]"
done
