#!/usr/bin/python
from setuptools import setup

setup(
    name = "fedpkg",
    version = "1.15",
    author = "Dennis Gilmore",
    author_email = "dgilmore@fedoraproject.org",
    description = ("Fedora plugin to rpkg to manage "
                   "package sources in a git repository"),
    license = "GPLv2+",
    url = "http://fedorahosted.org/fedpkg",
    package_dir = {'': 'src'},
    packages = ['fedpkg'],
    scripts = ['src/bin/fedpkg'],
    data_files = [('/etc/bash_completion.d', ['src/fedpkg.bash']),
                  ('/etc/rpkg', ['src/fedpkg.conf']),
                  ('/usr/libexec/', ['src/fedpkg-fixbranches.py']),
                 ]
)
