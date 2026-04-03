"""Distro detection and package manager mapping."""
import os
import platform
import shutil


class DistroInfo:
    __slots__ = (
        "id", "name", "pkg_manager", "pkg_install", "pkg_remove",
        "pkg_search", "pkg_update", "pkg_list", "service_manager",
        "is_root", "sudo_available", "arch",
    )

    def __init__(self):
        self.id = "unknown"
        self.name = "Unknown Linux"
        self.pkg_manager = "unknown"
        self.pkg_install = ""
        self.pkg_remove = ""
        self.pkg_search = ""
        self.pkg_update = ""
        self.pkg_list = ""
        self.service_manager = "systemctl"
        self.is_root = os.geteuid() == 0
        self.sudo_available = shutil.which("sudo") is not None
        self.arch = platform.machine() or "unknown"


# Package manager command templates.
# {} is replaced with the package name(s).
PKG_MANAGERS = {
    "apt": {
        "install": "apt install -y {}",
        "remove": "apt remove -y {}",
        "search": "apt search {}",
        "update": "apt update && apt upgrade -y",
        "list": "apt list --installed 2>/dev/null",
    },
    "dnf": {
        "install": "dnf install -y {}",
        "remove": "dnf remove -y {}",
        "search": "dnf search {}",
        "update": "dnf upgrade -y",
        "list": "dnf list installed",
    },
    "yum": {
        "install": "yum install -y {}",
        "remove": "yum remove -y {}",
        "search": "yum search {}",
        "update": "yum update -y",
        "list": "yum list installed",
    },
    "pacman": {
        "install": "pacman -S --noconfirm {}",
        "remove": "pacman -R --noconfirm {}",
        "search": "pacman -Ss {}",
        "update": "pacman -Syu --noconfirm",
        "list": "pacman -Q",
    },
    "zypper": {
        "install": "zypper install -y {}",
        "remove": "zypper remove -y {}",
        "search": "zypper search {}",
        "update": "zypper update -y",
        "list": "zypper packages --installed-only",
    },
    "apk": {
        "install": "apk add {}",
        "remove": "apk del {}",
        "search": "apk search {}",
        "update": "apk upgrade",
        "list": "apk list --installed",
    },
}

# Detection order matters — apt before dpkg, dnf before yum.
_DETECT_ORDER = ["apt", "dnf", "yum", "pacman", "zypper", "apk"]


def _parse_os_release():
    """Parse /etc/os-release into a dict. Works on Python 3.8+."""
    info = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if "=" not in line or line.startswith("#"):
                        continue
                    key, _, val = line.partition("=")
                    info[key] = val.strip('"').strip("'")
            break
        except (FileNotFoundError, PermissionError):
            continue
    return info


def detect_distro():
    """Detect the current Linux distribution and package manager."""
    d = DistroInfo()
    osrel = _parse_os_release()

    d.id = osrel.get("ID", "unknown").lower()
    d.name = osrel.get("PRETTY_NAME", osrel.get("NAME", "Unknown Linux"))

    # Auto-detect package manager binary.
    for pm in _DETECT_ORDER:
        if shutil.which(pm):
            d.pkg_manager = pm
            break

    cmds = PKG_MANAGERS.get(d.pkg_manager, {})
    d.pkg_install = cmds.get("install", "")
    d.pkg_remove = cmds.get("remove", "")
    d.pkg_search = cmds.get("search", "")
    d.pkg_update = cmds.get("update", "")
    d.pkg_list = cmds.get("list", "")

    # Service manager.
    if shutil.which("systemctl"):
        d.service_manager = "systemctl"
    elif shutil.which("rc-service"):
        d.service_manager = "rc-service"
    else:
        d.service_manager = "service"

    return d
