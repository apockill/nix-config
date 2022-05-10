```
sudo gedit /etc/default/grub
```

Then change
```
GRUB_DEFAULT=saved
GRUB_SAVEDEFAULT=true
GRUB_TIMEOUT=3
```

Then run 
```
sudo update-grub
```
