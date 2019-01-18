# -*- coding: utf-8 -*-
# Utilities used for running tests
#
# Copyright (C) 2017 Red Hat Inc.
# Author(s): Chenxiong Qi <cqi@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

import os
import subprocess
import tempfile
import shutil
import logging

import pyrpkg
import fedpkg.cli

from six.moves import configparser
from fedpkg import Commands

try:
    import unittest2 as unittest
except ImportError:
    import unittest


class Assertions(object):

    def get_exists_method(self, search_dir=None):
        if search_dir is None:
            def exists(filename):
                return os.path.exists(filename)
        else:
            def exists(filename):
                return os.path.exists(os.path.join(search_dir, filename))
        return exists

    def assertFilesExist(self, filenames, search_dir=None):
        """Assert existence of files within package repository

        :param filenames: a sequence of file names within package repository to be checked.
        :type filenames: list or tuple
        """
        assert isinstance(filenames, (tuple, list))
        exists = self.get_exists_method(search_dir)
        for filename in filenames:
            self.assertTrue(exists(filename), 'Failure because {0} does not exist'.format(filename))

    def assertFilesNotExist(self, filenames, search_dir=None):
        assert isinstance(filenames, (tuple, list))
        exists = self.get_exists_method(search_dir)
        for filename in filenames:
            self.assertFalse(exists(filename), 'Failure because {0} exists.'.format(filename))


class Utils(object):

    @staticmethod
    def run_cmd(cmd, allow_output=None, **kwargs):
        if not allow_output:
            kwargs.update({
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE
            })
        subprocess.call(cmd, **kwargs)

    def read_file(self, filename):
        with open(filename, 'r') as f:
            return f.read()

    def write_file(self, filename, content=''):
        with open(filename, 'w') as f:
            f.write(content)


class fedpkgConfig(object):

    def __init__(self, config_file=None):
        if config_file:
            self.config_file = config_file
        else:
            self.config_file = os.path.join(
                os.path.dirname(os.path.realpath(__file__)),
                'fedpkg-test.conf')

        config = configparser.RawConfigParser()
        config.read([self.config_file])

        self.anongiturl = config.get('fedpkg', 'anongiturl')
        self.gitbaseurl = config.get('fedpkg', 'gitbaseurl')
        self.lookaside_cgi = config.get('fedpkg', 'lookaside_cgi')
        self.lookasidehash = config.get('fedpkg', 'lookasidehash')
        self.lookaside = config.get('fedpkg', 'lookaside')
        self.branchre = config.get('fedpkg', 'branchre')
        self.kojiprofile = config.get('fedpkg', 'kojiprofile')
        self.build_client = config.get('fedpkg', 'build_client')
        self.distgit_namespaced = config.getboolean(
            'fedpkg', 'distgit_namespaced')
        self.kerberos_realms = config.get('fedpkg', 'kerberos_realms')


fedpkg_test_config = fedpkgConfig()


class RepoCreationMixin(object):
    """Mixin providing method to create repos for running tests"""

    spec_file_content = '''Summary: Dummy summary
Name: docpkg
Version: 1.2
Release: 2%{dist}
License: GPL
#Source0:
#Patch0:
Group: Applications/Productivity
BuildRoot: %(mktemp -ud %{_tmppath}/%{name}-%{version}-%{release}-XXXXXX)
%description
Dummy docpkg for tests
%prep
%check
%build
touch README.rst
%clean
rm -rf $$RPM_BUILD_ROOT
%install
rm -rf $$RPM_BUILD_ROOT
%files
%defattr(-,root,root,-)
%doc README.rst
%changelog
* Thu Apr 21 2016 Tester <tester@example.com> - 1.2-2
- Initial version
'''

    @classmethod
    def create_fake_repos(cls):
        # create a base repo
        cls.repo_base = tempfile.mkdtemp(prefix='fedpkg-commands-tests-')
        # Have a namespace of rpms and a repo name of testpkg
        cls.repo_path = os.path.join(cls.repo_base, 'rpms', 'testpkg')
        os.makedirs(cls.repo_path)

        cls.spec_filename = 'docpkg.spec'

        # Add spec file to this repo and commit
        spec_file_path = os.path.join(cls.repo_path, cls.spec_filename)
        with open(spec_file_path, 'w') as f:
            f.write(cls.spec_file_content)

        git_cmds = [
            ['git', 'init'],
            ['touch', 'sources', 'CHANGELOG.rst'],
            ['git', 'add', spec_file_path, 'sources', 'CHANGELOG.rst'],
            ['git', 'config', 'user.email', 'tester@example.com'],
            ['git', 'config', 'user.name', 'tester'],
            ['git', 'commit', '-m', '"initial commit"'],
            ['git', 'branch', 'rhel-6.8'],
            ['git', 'branch', 'rhel-7'],
            ['git', 'branch', 'f26'],
            ['git', 'branch', 'f27'],
            # Representing a stream branch
            ['git', 'branch', '8'],
            ]
        for cmd in git_cmds:
            cls.run_cmd(cmd, cwd=cls.repo_path)

        # Clone the repo
        cls.cloned_repo_path = tempfile.mkdtemp(
            prefix='fedpkg-commands-tests-cloned-')
        cls.run_cmd(['git', 'clone', cls.repo_path, cls.cloned_repo_path])
        git_cmds = [
            ['git', 'config', 'user.email', 'tester@example.com'],
            ['git', 'config', 'user.name', 'tester'],
            ['git', 'branch', '--track', 'rhel-7', 'origin/rhel-7'],
            ['git', 'branch', '--track', 'f26', 'origin/f26'],
            ['git', 'branch', '--track', 'f27', 'origin/f27'],
            ['git', 'branch', '--track', '8', 'origin/8'],
            ]
        for cmd in git_cmds:
            cls.run_cmd(cmd, cwd=cls.cloned_repo_path)

    @classmethod
    def destroy_fake_repos(cls):
        shutil.rmtree(cls.repo_base)
        shutil.rmtree(cls.cloned_repo_path)


class CommandTestCase(RepoCreationMixin, Assertions, Utils, unittest.TestCase):

    create_repo_per_test = True
    require_test_repos = True

    @classmethod
    def setUpClass(cls):
        if cls.require_test_repos and not cls.create_repo_per_test:
            cls.create_fake_repos()

    @classmethod
    def tearDownClass(cls):
        if cls.require_test_repos and not cls.create_repo_per_test:
            cls.destroy_fake_repos()

    def setUp(self):
        if self.require_test_repos and self.create_repo_per_test:
            self.create_fake_repos()

    def tearDown(self):
        if self.require_test_repos and self.create_repo_per_test:
            self.destroy_fake_repos()

    def make_commands(self, path=None, user=None, dist=None, target=None,
                      quiet=None):
        """Helper method for creating Commands object for test cases

        This is where you should extend to add more features to support
        additional requirements from other Commands specific test cases.

        Some tests need customize one of user, dist, target, and quiet options
        when creating an instance of Commands. Keyword arguments user, dist,
        target, and quiet here is for this purpose.

        :param str path: path to repository where this Commands will work on
        top of
        :param str user: user passed to --user option
        :param str dist: dist passed to --dist option
        :param str target: target passed to --target option
        :param str quiet: quiet passed to --quiet option
        """
        return Commands(path or self.cloned_repo_path,
                        fedpkg_test_config.lookaside,
                        fedpkg_test_config.lookasidehash,
                        fedpkg_test_config.lookaside_cgi,
                        fedpkg_test_config.gitbaseurl,
                        fedpkg_test_config.anongiturl,
                        fedpkg_test_config.branchre,
                        fedpkg_test_config.kojiprofile,
                        fedpkg_test_config.build_client,
                        user=user, dist=dist, target=target, quiet=quiet)

    def checkout_branch(self, repo, branch_name):
        """Checkout to a local branch

        :param git.Repo repo: `git.Repo` instance represents a git repository
        that current code works on top of.
        :param str branch_name: name of local branch to checkout
        """
        heads = [head for head in repo.heads if head.name == branch_name]
        assert len(heads) > 0, \
            'Repo must have a local branch named {0} that ' \
            'is for running tests. But now, it does not exist. Please check ' \
            'if the repo is correct.'.format(branch_name)

        heads[0].checkout()

    def create_branch(self, repo, branch_name):
        repo.git.branch(branch_name)


class CliTestCase(CommandTestCase):
    """Base test case for testing from command line interface"""

    default_config_file = os.path.join(os.path.dirname(__file__),
                                       'fedpkg-test.conf')

    def new_cli(self, name='fedpkg', cfg=None, user_cfg=None):
        config = configparser.ConfigParser()
        if cfg:
            config_file = os.path.join(os.path.dirname(__file__), cfg)
        else:
            config_file = self.default_config_file
        config.read(config_file)

        if user_cfg:
            user_config_file = os.path.join(
                os.path.dirname(__file__), user_cfg)
            config.read(user_config_file)

        client = fedpkg.cli.fedpkgClient(config, name=name)
        client.setupLogging(pyrpkg.log)
        pyrpkg.log.setLevel(logging.CRITICAL)
        client.do_imports(site='fedpkg')
        client.parse_cmdline()

        return client
