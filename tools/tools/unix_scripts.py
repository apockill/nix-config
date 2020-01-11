from pathlib import Path


def ls():
    """ ls clone"""
    files = list(Path(".").iterdir())
    files.sort(key=lambda file: file.name)
    filestr = "\t".join(file.name for file in files)
    print(filestr)
