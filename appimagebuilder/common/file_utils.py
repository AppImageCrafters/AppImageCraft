#  Copyright  2020 Alexis Lopez Zubieta
#
#  Permission is hereby granted, free of charge, to any person obtaining a
#  copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation the
#  rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
#  sell copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in
#  all copies or substantial portions of the Software.
import os
import stat
import subprocess


def is_elf(path):
    with open(path, "rb") as f:
        bits = f.read(4)
        if bits == b"\x7fELF":
            return True

    return False


def is_elf_executable(path):
    """
    Determine if an elf is executable

    The `__libc_start_main` symbol should be present in every runnable elf file.
    https://refspecs.linuxbase.org/LSB_3.1.1/LSB-Core-generic/LSB-Core-generic/baselib---libc-start-main-.html
    """
    has_main_method = False
    _proc = subprocess.run("readelf -s %s" % path, stdout=subprocess.PIPE, shell=True)
    if _proc.returncode == 0:
        output = _proc.stdout.decode("utf-8")
        has_main_method = "__libc_start_main" in output
    return has_main_method


def read_elf_arch(path):
    """
    Read the target instructions set architecture and maps it to a name known by appimage-builder

    https://en.wikipedia.org/wiki/Executable_and_Linkable_Format#File_header
    """
    known_architectures = {
        b"\xB7": "aarch64",
        b"\x28": "gnueabihf",
        b"\x03": "i386",
        b"\x3E": "x86_64",
    }

    with open(path, "rb") as f:
        f.seek(18)
        e_machine = f.read(1)
        if e_machine in known_architectures:
            return known_architectures[e_machine]
        else:
            raise RuntimeError(
                "Unknown instructions set architecture `%s` on: %s"
                % (e_machine.hex(), path)
            )


def set_permissions_rx_all(path):
    os.chmod(
        path,
        stat.S_IRUSR
        | stat.S_IRGRP
        | stat.S_IROTH
        | stat.S_IXUSR
        | stat.S_IXGRP
        | stat.S_IXOTH
        | stat.S_IWUSR,
    )