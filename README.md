# Installation

The following is a haphazard todo-list for setting up a newly installed system to my liking. 

## Basic Configuration
1) Run `python3 dependencies.py`

1) Run `cat helpful/scripts/.bashrc-addon.sh >> ~/.bashrc`

1) Install pycharm `sudo snap install pycharm-professional --classic`

1) Install chrome via their deb

1) Set gnome-terminal to be transparent, have a black background, and select "show bold text in bright colors".

1) Install pop-shell using `helpful/pop-shell.md` Do this before the next step, because it will reset some keyboard shortcuts


1) Open `gnome-tweaks` and set:
    - Windows:
        - Focus on Hover
    - Appearance: 
        - Themes: Applications: Yaru

1) Go to Settings -> Multitasking:
    - set the number of fixed workspaces to 5

1) Run `bash helpful/scripts/disable-hotbar-super-keys.sh`

1) Manually configure keyboard shortcuts using instructions under `helpful/keyboard-shortcuts.md`

1) Optionally, configure grub using `helpful/grub_defaults.md`

1) Optionally, install system76-power:
   ```shell
   sudo apt-add-repository ppa:system76-dev/stable
   sudo apt install gnome-shell-extension-system76-power system76-power
   ```

## Install Extra Programs

1) Set up insync. [Instructions](https://www.insynchq.com/downloads)

## Install Gnome Extensions
1) Go to the extensions website and install:
    ```shell
    https://extensions.gnome.org/extension/2950/compiz-alike-windows-effect/
    https://extensions.gnome.org/extension/4679/burn-my-windows/
    https://extensions.gnome.org/extension/120/system-monitor/
    https://extensions.gnome.org/extension/906/sound-output-device-chooser/
    https://extensions.gnome.org/extension/1708/transparent-top-bar/
    ```

## Docker Cheat Sheet
### Docker Cache On a Separate Drive
1) Follow instructions under `helpful/docker-cache-separate-drive.md`

# Screenshots
[Switching screenshot application to flameshot](https://askubuntu.com/questions/1036473/ubuntu-18-how-to-change-screenshot-application-to-flameshot)

# Customizations

## Transparency
You can adjust the taskbar transparency using this command (takes effect after locking/unlocking):

```
gsettings set org.gnome.shell.extensions.dash-to-dock background-opacity 0.2
```
