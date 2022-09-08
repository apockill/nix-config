1) Download the theme from https://www.pling.com/p/1727268/
   More themes can be found at: https://github.com/Jacksaur/Gorgeous-GRUB/blob/main/Installation.md
2) Create the themes directory
    ```
    sudo mkdir /boot/grub/themes
    sudo chown $USER /boot/grub/themes
    ```
3) Unzip the themes file and drop the themes into `/boot/grub/themes/
4) Open grub config using `sudo gedit /etc/defaults/grub` and add the line
    ```
    GRUB_THEME=/boot/grub/themes/theme.txt
    ```
5) Run `sudo update-grub`. It should say `Found theme: /boot/grub/themes/theme.txt`
