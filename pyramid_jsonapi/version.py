#!/usr/bin/env python
"""Generate version information from git tags, archive info, or PKG-INFO.

Based on: https://github.com/Changaco/version.py

"""

from os.path import dirname, isdir, isfile, join
import re
from subprocess import CalledProcessError, check_output
import pkg_resources


def get_version():
    """Get version in any way possible."""

    prefix = ''
    tag_re = re.compile(r'\btag: %s([0-9][^,]*)\b' % prefix)
    version_re = re.compile('^Version: (.+)$', re.M)

    # Return the version if it has been injected into the file by git-archive
    version = tag_re.search('$Format:%D$')
    if version:
        return version.group(1)

    project_dir = dirname(__file__)
    pkg_file = join(project_dir, '../PKG-INFO')

    if isdir(join(project_dir, '../.git')):
        # Get the version using "git describe".
        cmd = 'git -C %s describe --tags --match %s[0-9]* --dirty' % (project_dir, prefix)
        try:
            version = check_output(cmd.split()).decode().strip()[len(prefix):]
        except CalledProcessError:
            raise RuntimeError('Unable to get version number from git tags')

        # PEP 440 compatibility
        if '-' in version:
            version = '.dev'.join(version.split('-')[:2])
        return version

    if isfile(pkg_file):
        # Extract the version from the PKG-INFO file.
        with open(pkg_file) as info_f:
            return version_re.search(info_f.read()).group(1)

    # Package was installed (os pkg, pip etc) without PKG-INFO
    return pkg_resources.get_distribution('pyramid-jsonapi').version


if __name__ == '__main__':
    print(get_version())
