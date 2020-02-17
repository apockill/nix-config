import shutil
import subprocess

# Verify system
is_ubuntu = shutil.which("apt") is not None
if not is_ubuntu:
    assert shutil.which("pacman") is not None


class Dependency:
    def __init__(self, *, apt=None, arch=None, aur=None, pip3=None):
        assert not (arch is not None and aur is not None), \
            f"That doesn't make any sense! Pacman: {arch} Aur: {aur}"
        assert not (pip3 is not None and
                    (apt is not None or arch is not None or aur is not None)), \
            "pip3 is platform independent! It must be the only dependency"
        assert apt or arch or aur or pip3, \
            "At least one package manager must be specified"
        self.apt = apt
        self.pacman = arch
        self.aur = aur
        self.pip3 = pip3

    def install(self):
        """Install the relevant package"""
        if self.pip3 is not None:
            subprocess.run(
                ["pip3", "install", self.pip3],
                check=True)
        elif is_ubuntu:
            subprocess.run(
                ["sudo", "apt-get", "--assume-yes", self.apt],
                check=True)
        elif self.pacman is not None:
            subprocess.run(
                ["sudo", "pacman", "-S", "--noconfirm", self.pacman],
                check=True)
        elif self.aur is not None:
            subprocess.run(
                ["pacaur", "-S", "--noconfirm", "--noedit", self.aur],
                check=True)
        else:
            raise RuntimeError("A package should have been specified!")


dependencies = [
    # For development
    Dependency(apt="git", arch="git"),
    Dependency(apt="python-pip", arch="python-pip"),
    Dependency(apt="trickle", aur="trickle"),

    # Applications
    Dependency(apt="spectacle", arch="spectacle"),
    Dependency(apt="arandr", arch="arandr"),
    Dependency(apt="qdirstat", aur="qdirstat"),
    Dependency(apt="pavucontrol", arch="pavucontrol"),
    Dependency(apt="nautilus", arch="nautilus"),
    Dependency(apt="chromium-browser", aur="google-chrome"),
    Dependency(apt="gnome-terminal", arch="gnome-terminal"),

    # Configuration
    Dependency(apt="gnome-disks", aur="gnome-disk-utility"),
    Dependency(apt="lxappearance", arch="lxappearance"),
    Dependency(apt="nitrogen", arch="nitrogen"),

    # Window manager
    Dependency(apt=None, arch="gnome-shell-extension-material-shell-git"),

    # Useful applications
    Dependency(apt="gnome-system-monitor", arch="gnome-system-monitor"),
]

# Add platform-specific dependencies
if is_ubuntu:
    dependencies += [
        Dependency(pip3="nautilus-terminal")
    ]
else:
    dependencies += [
        Dependency(aur="nautilus-terminal")
    ]


def install_dependencies():
    for dep in dependencies:
        dep.install()


if __name__ == "__main__":
    input("Press enter to install dependencies")
    install_dependencies()
