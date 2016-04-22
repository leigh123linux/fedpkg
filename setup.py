#!/usr/bin/python
from setuptools import setup
try:
    from subprocess import getstatusoutput
except:
    from commands import getstatusoutput


def bash_completion_dir():
    (sts, output) = getstatusoutput(
        'pkg-config --variable=completionsdir bash-completion')
    return output if not sts and output else '/etc/bash_completion.d'

setup(
    name="fedpkg",
    version="1.23",
    author="Dennis Gilmore",
    author_email="dgilmore@fedoraproject.org",
    description=("Fedora plugin to rpkg to manage "
                 "package sources in a git repository"),
    license="GPLv2+",
    url="http://fedorahosted.org/fedpkg",
    package_dir={'': 'src'},
    packages=['fedpkg'],
    scripts=['src/bin/fedpkg'],
    data_files=[(bash_completion_dir(), ['src/fedpkg.bash']),
                ('/etc/rpkg', ['src/fedpkg.conf']),
                ],
)
