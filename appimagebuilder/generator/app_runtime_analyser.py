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
import fnmatch
import logging
import os
import re
import subprocess

from appimagebuilder.commands.patchelf import PatchElf, PatchElfError
from appimagebuilder.common import shell, elf
from appimagebuilder.common.finder import Finder

DEPENDS_ON = ["strace", "patchelf"]


class AppRuntimeAnalyser:
    def __init__(self, app_dir, bin, args):
        self.appdir = os.path.abspath(app_dir)
        self.bin = os.path.join(self.appdir, bin)
        self.args = args
        self.runtime_libs = set()
        self.runtime_execs = set()
        self.runtime_data = set()
        self.logger = logging.getLogger("AppRuntimeAnalyser")
        self._deps = shell.resolve_commands_paths(DEPENDS_ON)

    def run_app_analysis(self):
        self.runtime_libs.clear()
        runtime_files = self._trace_app_execution()

        # remove dirs, non existent files and excluded paths
        runtime_files = [
            path
            for path in runtime_files
            if os.path.exists(path)
            and not os.path.isdir(path)
            and not path.startswith(self.appdir)
            and not self._is_excluded_data_path(path)
        ]

        self.runtime_execs = [
            path for path in runtime_files if os.access(path, os.X_OK)
        ]
        self.runtime_libs = [path for path in runtime_files if elf.has_soname(path)]
        self.runtime_data = [
            path
            for path in runtime_files
            if path not in self.runtime_execs and path not in self.runtime_libs
        ]

        interpreter_paths = self._resolve_bin_interpreters()
        self.runtime_execs.extend(interpreter_paths)

        if not self.runtime_libs:
            logging.warning(
                "No dependencies were found, "
                "please make sure that all the required libraries are reachable."
            )

        return runtime_files

    def _trace_app_execution(self):
        # find dirs containing libraries that may be needed by the application at runtime
        library_paths = self._resolve_appdir_library_paths()
        library_paths = ":".join(library_paths)

        # use strace to discover which files are accessed at runtime
        # arguments:
        #   "-f" trace children processes
        #   "-E LD_LIBRARY_PATH={library_paths}" set LD_LIBRARY_PATH in the application environment
        #   "-e trace=openat --status=successful" trace file access operations that succeed
        command = "{strace} -f -E LD_LIBRARY_PATH={library_paths} -e trace=openat --status=successful {bin} {args}"
        command = command.format(
            bin=self.bin, args=self.args, **self._deps, library_paths=library_paths
        )
        self.logger.info(command)
        _proc = subprocess.run(command, stderr=subprocess.PIPE, shell=True)

        if _proc.returncode != 0:
            self.logger.warning(
                "%s exited with code %d" % (_proc.args, _proc.returncode)
            )
            self.logger.warning(
                "This may produce an incomplete/wrong recipe. Please make sure that the application runs properly."
            )

        # parse results
        stderr_data = _proc.stderr.decode()
        accessed_files = re.findall(r'openat\(.*?"(?P<path>.*?)".*', stderr_data)
        return accessed_files

    def _resolve_appdir_library_paths(self):
        finder = Finder(self.appdir)
        lib_paths = finder.find("*", [Finder.is_elf_shared_lib])
        library_paths = set([os.path.dirname(path) for path in lib_paths])
        return library_paths

    def _resolve_bin_interpreters(self):
        patch_elf = PatchElf()
        patch_elf.log_stderr = False
        interpreter_paths = set()
        for bin in self.runtime_execs:
            try:
                interpreter = patch_elf.get_interpreter(bin)
                if not interpreter.startswith("/tmp"):
                    interpreter_paths.add(interpreter)
            except PatchElfError:
                pass
        return interpreter_paths

    @staticmethod
    def _is_excluded_data_path(path):
        excluded_data_paths = [
            # don't include virtual fs
            "/sys/**",
            "/proc/**",
            "/dev/**",
            "/run/**",
            # don't include system settings
            "/etc/**",
            # don't include user settings or cache
            os.getenv("HOME") + "/.cache/*",
            os.getenv("HOME") + "/.config/*",
            # don't include dbus as it will not be reachable from the bundle
            "/var/lib/dbus/*",
            # do not include font files
            "**/fonts/*.conf",
            "**/fonts/*.otf",
            "**/fontconfig/**/*.conf",
            "**/fontconfig/**/*.cache*",
            os.getenv("HOME") + "/.fonts/*",
            # don't include GTK caches
            "**/gdk-pixbuf-2.0/**/loaders.cache",
            "**/gio/**/giomodule.cache",
            "**/glib-2.0/**/gschemas.compiled",
        ]

        for expr in excluded_data_paths:
            if fnmatch.fnmatch(path, expr):
                return True

        return False
