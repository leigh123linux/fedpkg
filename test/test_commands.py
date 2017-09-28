# fedpkg - a Python library for RPM Packagers
#
# Copyright (C) 2017 Red Hat Inc.
# Author(s): Chenxiong qi <cqi@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

import unittest

from pyrpkg.errors import rpkgError
from fedpkg import _get_bodhi_version
from utils import CommandTestCase
from mock import patch
from mock import Mock
from mock import PropertyMock


class TestDetermineRuntimeEnv(CommandTestCase):
    """Test Commands._determine_runtime_env"""

    def setUp(self):
        super(TestDetermineRuntimeEnv, self).setUp()
        self.cmd = self.make_commands()

    @patch('platform.linux_distribution')
    def test_return_fedora_disttag(self, linux_distribution):
        linux_distribution.return_value = ('Fedora', '25', 'Twenty Five')

        result = self.cmd._determine_runtime_env()
        self.assertEqual('fc25', result)

    @patch('platform.linux_distribution')
    def test_return_None_if_cannot_os_is_unknown(self, linux_distribution):
        linux_distribution.side_effect = ValueError

        self.assertEqual(None, self.cmd._determine_runtime_env())

    @patch('platform.linux_distribution')
    def test_return_for_rhel(self, linux_distribution):
        linux_distribution.return_value = ('Red Hat Enterprise Linux Server',
                                           '6.8',
                                           'Santiago')

        result = self.cmd._determine_runtime_env()
        self.assertEqual('el6', result)

    def test_return_for_centos(self):
        dists = [
            (('CentOS', '6.9', 'Final'), 'el6'),
            (('CentOS Linux', '7.3.1611', 'Core'), 'el7'),
        ]

        for dist, expected_dist_tag in dists:
            with patch('platform.linux_distribution', return_value=dist):
                result = self.cmd._determine_runtime_env()
                self.assertEqual(expected_dist_tag, result)


class TestLoadTarget(CommandTestCase):
    """Test Commands.load_target"""

    def setUp(self):
        super(TestLoadTarget, self).setUp()
        self.cmd = self.make_commands()

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    def test_load_from_master(self, branch_merge):
        branch_merge.return_value = 'master'

        self.cmd.load_target()
        self.assertEqual('rawhide', self.cmd._target)

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    def test_load_from_release_branch(self, branch_merge):
        branch_merge.return_value = 'f26'

        self.cmd.load_target()
        self.assertEqual('f26-candidate', self.cmd._target)


class TestLoadContainerBuildTarget(CommandTestCase):
    """Test Commands.load_container_build_target"""

    def setUp(self):
        super(TestLoadContainerBuildTarget, self).setUp()
        self.cmd = self.make_commands()

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    @patch('pyrpkg.Commands.ns', new_callable=PropertyMock)
    def test_load_from_master(self, ns, branch_merge):
        ns.return_value = 'container'
        branch_merge.return_value = 'master'

        self.cmd.load_container_build_target()
        self.assertEqual('rawhide-container-candidate',
                         self.cmd._container_build_target)

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    @patch('pyrpkg.Commands.ns', new_callable=PropertyMock)
    def test_load_from_release_branch(self, ns, branch_merge):
        ns.return_value = 'container'
        branch_merge.return_value = 'f26'

        self.cmd.load_container_build_target()
        self.assertEqual('f26-container-candidate',
                         self.cmd._container_build_target)


class TestLoadUser(CommandTestCase):
    """Test Commands.load_user"""

    def setUp(self):
        super(TestLoadUser, self).setUp()
        self.cmd = self.make_commands()

    @patch('fedora_cert.read_user_cert')
    def test_load_from_load_fedora_cert(self, read_user_cert):
        read_user_cert.return_value = 'someone'

        self.cmd.load_user()
        self.assertEqual('someone', self.cmd._user)

    @patch('fedora_cert.read_user_cert')
    @patch('os.getuid')
    @patch('pwd.getpwuid')
    def test_fall_back_to_super_load_user(
            self, getpwuid, getuid, read_user_cert):
        getpwuid.return_value = ('someone', None)
        read_user_cert.side_effect = Exception

        self.cmd.load_user()
        self.assertEqual('someone', self.cmd._user)


class GetBodhiVersion(unittest.TestCase):
    """Test fedpkg._get_bodhi_version"""

    @patch('subprocess.Popen')
    def test_get_bodhi_version(self, Popen):
        Popen.return_value.communicate.return_value = ('1.2.3\n', '')

        version = _get_bodhi_version()
        self.assertEqual([1, 2, 3], version)


class TestLookaside(CommandTestCase):
    """Test Commands.lookasidecache"""

    def setUp(self):
        super(TestLookaside, self).setUp()
        self.cmd = self.make_commands()

    @patch('fedpkg.Commands.cert_file', new_callable=PropertyMock)
    @patch('fedpkg.Commands.ca_cert', new_callable=PropertyMock)
    def test_get_lookaside(self, ca_cert, cert_file):
        ca_cert.return_value = None
        cert_file.return_value = None

        lookaside = self.cmd.lookasidecache

        self.assertEqual(self.cmd.lookasidehash, lookaside.hashtype)
        self.assertEqual(self.cmd.lookaside, lookaside.download_url)
        self.assertEqual(self.cmd.lookaside_cgi, lookaside.upload_url)
        self.assertEqual(None, lookaside.client_cert)
        self.assertEqual(None, lookaside.ca_cert)


class TestLoadRpmDefines(CommandTestCase):
    """Test Commands.load_rpmdefines"""

    def setUp(self):
        super(TestLoadRpmDefines, self).setUp()

        self.determine_runtime_env = patch(
            'fedpkg.Commands._determine_runtime_env',
            return_value='fc25')
        self.determine_runtime_env.start()

        self.localarch = patch(
            'pyrpkg.Commands.localarch',
            new_callable=PropertyMock,
            return_value='i686')
        self.localarch.start()

        self.cmd = self.make_commands()

    def tearDown(self):
        self.localarch.stop()
        self.determine_runtime_env.stop()
        super(TestLoadRpmDefines, self).tearDown()

    def assert_rpmdefines(self):
        """Assert Commands._rpmdefines after calling load_rpmdefines"""
        expected_rpmdefines = [
            "--define '_sourcedir %s'" % self.cmd.path,
            "--define '_specdir %s'" % self.cmd.path,
            "--define '_builddir %s'" % self.cmd.path,
            "--define '_srcrpmdir %s'" % self.cmd.path,
            "--define '_rpmdir %s'" % self.cmd.path,
            "--define 'dist .%s'" % self.cmd._disttag,
            "--define '%s %s'" % (self.cmd._distvar, self.cmd._distval),
            "--eval '%%undefine %s'" % self.cmd._distunset,
            "--define '%s 1'" % self.cmd._disttag,
            "--eval '%%undefine %s'" % self.cmd._runtime_disttag
        ]
        self.assertEqual(expected_rpmdefines, self.cmd._rpmdefines)

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    def test_raise_error_if_branch_name_is_unknown(self, branch_merge):
        branch_merge.return_value = 'private-branch'

        self.assertRaises(rpkgError, self.cmd.load_rpmdefines)

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    def test_load_fedora_dist_tag(self, branch_merge):
        branch_merge.return_value = 'f26'

        self.cmd.load_rpmdefines()

        self.assertEqual('26', self.cmd._distval)
        self.assertEqual('fedora', self.cmd._distvar)
        self.assertEqual('fc26', self.cmd._disttag)
        self.assertEqual('fedora-26-i686', self.cmd.mockconfig)
        self.assertEqual('f26-override', self.cmd.override)
        self.assertEqual('rhel', self.cmd._distunset)

        self.assert_rpmdefines()

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    def test_load_epel6_dist_tag(self, branch_merge):
        branch_merge.return_value = 'el6'

        self.cmd.load_rpmdefines()

        self.assertEqual('6', self.cmd._distval)
        self.assertEqual('rhel', self.cmd._distvar)
        self.assertEqual('el6', self.cmd._disttag)
        self.assertEqual('epel-6-i686', self.cmd.mockconfig)
        self.assertEqual('epel6-override', self.cmd.override)
        self.assertTrue(hasattr(self.cmd, '_distunset'))

        self.assert_rpmdefines()

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    def test_load_epel7_dist_tag(self, branch_merge):
        branch_merge.return_value = 'epel7'

        self.cmd.load_rpmdefines()

        self.assertEqual('7', self.cmd._distval)
        self.assertEqual('rhel', self.cmd._distvar)
        self.assertEqual('el7', self.cmd._disttag)
        self.assertEqual('epel-7-i686', self.cmd.mockconfig)
        self.assertEqual('epel7-override', self.cmd.override)
        self.assertTrue(hasattr(self.cmd, '_distunset'))

        self.assert_rpmdefines()

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    @patch('fedpkg.Commands._findmasterbranch')
    def test_load_master_dist_tag(self, _findmasterbranch, branch_merge):
        _findmasterbranch.return_value = '28'
        branch_merge.return_value = 'master'

        self.cmd.load_rpmdefines()

        self.assertEqual('28', self.cmd._distval)
        self.assertEqual('fedora', self.cmd._distvar)
        self.assertEqual('fc28', self.cmd._disttag)
        self.assertEqual('fedora-rawhide-i686', self.cmd.mockconfig)
        self.assertEqual(None, self.cmd.override)
        self.assertEqual('rhel', self.cmd._distunset)

        self.assert_rpmdefines()

    @patch('pyrpkg.Commands.branch_merge', new_callable=PropertyMock)
    def test_load_olpc_dist_tag(self, branch_merge):
        branch_merge.return_value = 'olpc7'

        self.cmd.load_rpmdefines()

        self.assertEqual('7', self.cmd._distval)
        self.assertEqual('olpc', self.cmd._distvar)
        self.assertEqual('olpc7', self.cmd._disttag)
        self.assertEqual(None, self.cmd._mockconfig)
        self.assertEqual('dist-olpc7-override', self.cmd.override)
        self.assertEqual('rhel', self.cmd._distunset)

        self.assert_rpmdefines()


class TestFindMasterBranch(CommandTestCase):
    """Test Commands._findmasterbranch"""

    def setUp(self):
        super(TestFindMasterBranch, self).setUp()

        self.cmd = self.make_commands()

    @patch('pyrpkg.Commands.kojisession', new_callable=PropertyMock)
    def test_get_from_koji_tag(self, kojisession):
        self.cmd._kojisession = Mock()
        koji_session = kojisession.return_value
        koji_session.getBuildTarget.return_value = {'dest_tag_name': 'f28'}

        result = self.cmd._findmasterbranch()

        koji_session.getBuildTarget.assert_called_once_with('rawhide')
        self.assertEqual('28', result)

    def test_find_from_fedora_branches(self):
        result = self.cmd._findmasterbranch()
        self.assertEqual(28, result)

    @patch('pyrpkg.Commands.anon_kojisession', new_callable=PropertyMock)
    @patch('pyrpkg.Commands.repo', new_callable=PropertyMock)
    def test_get_from_koji_for_the_last_chance(self, repo, anon_kojisession):
        # Must mock there is no f* branches
        repo.return_value.refs = ['rhel', 'private-branch']

        koji_session = anon_kojisession.return_value
        koji_session.getBuildTarget.return_value = {'dest_tag_name': 'f28'}

        result = self.cmd._findmasterbranch()

        koji_session.getBuildTarget.assert_called_once_with('rawhide')
        self.assertEqual('28', result)


class TestOverrideBuildURL(CommandTestCase):
    """Test Commands.construct_build_url"""

    @patch('pyrpkg.Commands.construct_build_url')
    def test_override(self, super_construct_build_url):
        super_construct_build_url.return_value = 'https://localhost/rpms/pkg'
        cmd = self.make_commands()

        overrided_url = cmd.construct_build_url()
        self.assertEqual(
            'git+{0}'.format(super_construct_build_url.return_value),
            overrided_url)
