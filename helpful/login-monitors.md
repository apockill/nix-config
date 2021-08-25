# Instructions

Instructions were pulled from [here](https://albertomatus.com/changing-login-display-in-ubuntu-20-04/).

1) Set up the monitors the way you want them to be during the login step

1) Copy the monitors.xml file to gdm's home folder
    ```shell
    sudo cp ~/.config/monitors.xml ~gdm/.config/monitors.xml

    ```
    
1) Change the permissions on this new copied file.
    ```shell
    sudo chown gdm:gdm ~gdm/.config/monitors.xml
    ```
    
1) You must also uncomment the line below in “/etc/gdm3/custom.conf” .

    ```shell
    WaylandEnable=false
    ```
