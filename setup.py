#!/usr/bin/python
from setuptools import setup, find_packages

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
    version="1.25",
    author="Dennis Gilmore",
    author_email="dgilmore@fedoraproject.org",
    description=("Fedora plugin to rpkg to manage "
                 "package sources in a git repository"),
    license="GPLv2+",
    url="http://fedorahosted.org/fedpkg",
    packages=find_packages(),
    scripts=[
        'bin/fedpkg',
        'bin/fedpkg-stage',
    ],
    data_files=[(bash_completion_dir(), ['conf/bash-completion/fedpkg.bash']),
                ('/etc/rpkg', ['conf/etc/rpkg/fedpkg.conf',
                               'conf/etc/rpkg/fedpkg-stage.conf']),
                ('/usr/share/zsh/site-functions', ['conf/zsh-completion/_fedpkg']),
                ],

    tests_require=['nose', 'mock'],
    test_suite='nose.collector',
)
