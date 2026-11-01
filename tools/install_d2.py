"""Install a checksum-verified D2 binary for the CI runner's platform."""

import argparse
import hashlib
import io
import os
import platform
import tarfile
from pathlib import Path
from urllib.request import urlopen

VERSION = "v0.9.0"
TIMEOUT = 60
SYSTEMS = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}
ARCHITECTURES = {
    "x86_64": "amd64", "amd64": "amd64",
    "arm64": "arm64", "aarch64": "arm64",
}
CHECKSUMS = {
    "linux-amd64": (
        "5669ddc46b99e942cc96078f4a4e36d5e62103348f4c05179ede27802fdd87a9"
    ),
    "linux-arm64": (
        "ac2c028697199479acb321db1e3d68caee9f2ba492ed73caa3cd13f3829bf913"
    ),
    "macos-amd64": (
        "cad39576a480d6bb02ea142fef1726647914b0d2da51ccc9b30b660a2b1babf0"
    ),
    "macos-arm64": (
        "eaf6c0c143e56dd9fa97bfb6df25ea9c1ebce40245f056a0768cf1a6c15d3064"
    ),
    "windows-amd64": (
        "5f63b643de8f5a6dfb922d172e1b5496e4caf47497c33c4427cf1127f28c340f"
    ),
    "windows-arm64": (
        "dd05cab459410c287d7ca3eb9cf78145a071742ee8e1b81a0122f84f471883e1"
    ),
}


def platform_key():
    """Select the official release matching this operating system and CPU."""
    system = SYSTEMS.get(platform.system())
    architecture = ARCHITECTURES.get(platform.machine().lower())
    key = f"{system}-{architecture}"
    if key not in CHECKSUMS:
        raise ValueError(f"Unsupported D2 platform: {key}")
    return key


def install(destination):
    """Write only the verified executable without extracting archive paths."""
    key = platform_key()
    asset = f"d2-{VERSION}-{key}.tar.gz"
    url = f"https://github.com/d2lang/d2/releases/download/{VERSION}/{asset}"
    with urlopen(url, timeout=TIMEOUT) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != CHECKSUMS[key]:
        raise ValueError("D2 archive checksum mismatch")
    filename = "d2.exe" if key.startswith("windows-") else "d2"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        member = next(item for item in archive.getmembers()
                      if item.isfile() and item.name.endswith("/" + filename))
        binary = archive.extractfile(member).read()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / filename
    target.write_bytes(binary)
    target.chmod(0o755)
    return target


def main():
    """Install into the supplied directory and expose it to later CI steps."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    settings = parser.parse_args()
    target = install(settings.destination.resolve())
    if "GITHUB_PATH" in os.environ:
        path_file = Path(os.environ["GITHUB_PATH"])
        with path_file.open("a", encoding="utf-8") as path:
            path.write(str(target.parent) + "\n")
    print(f"D2 {VERSION}: {target}")


if __name__ == "__main__":
    main()
