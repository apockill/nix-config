### Nautilus-terminal installation
To properly install, it must run in python2, so it cannot be installed via pip3

```
sudo apt install python-pip nautilus-python
pip install --user nautilus_terminal
nautilus -q
```

### Material-shell installation
```
git clone https://github.com/PapyElGringo/material-shell.git ~/.local/share/gnome-shell/extensions/material-shell@papyelgringo
gnome-shell-extension-tool -e material-shell@papyelgringo
```
Now restart the shell by hitting `Alt+F2` and typing 'r'.


### X-Box One Controller Drivers
```
sudo apt-get install dkms linux-headers-`uname -r`
git clone https://github.com/atar-axis/xpadneo.git
cd xpadneo
sudo ./install.sh
```
### Gnome Tweaks
If using ubuntus desktop, try these tweaks:
```
gsettings set org.gnome.mutter workspaces-only-on-primary false
```

## Changing the docker data root
Add the following to the daemon.json
```json
{
  "data-root": "path/to/cache/directory"
}
```