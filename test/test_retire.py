# -*- coding: utf-8 -*-

import os
import shutil
import unittest
import mock
import ConfigParser
import tempfile
import subprocess

from fedpkg.cli import fedpkgClient


TEST_CONFIG = os.path.join(os.path.dirname(__file__), 'fedpkg-test.conf')


class RetireTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log = mock.Mock()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def _setup_repo(self, origin):
        subprocess.check_call(
            ['git', 'init'],
            cwd=self.tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.check_call(
            ['git', 'remote', 'add', 'origin', origin],
            cwd=self.tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.check_call(
            ['touch', 'fedpkg.spec'],
            cwd=self.tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.check_call(
            ['git', 'add', '.'],
            cwd=self.tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.check_call(
            ['git', 'commit', '-m', 'Initial commit'],
            cwd=self.tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _get_latest_commit(self):
        proc = subprocess.Popen(['git', 'log', '-n', '1', '--pretty=%s'],
                                cwd=self.tmpdir, stdout=subprocess.PIPE)
        out, err = proc.communicate()
        return out.strip()

    def _fake_client(self, args):
        config = ConfigParser.SafeConfigParser()
        config.read(TEST_CONFIG)
        with mock.patch('sys.argv', new=args):
            client = fedpkgClient(config)
            client.do_imports(site='fedpkg')
            client.setupLogging(self.log)

            client.parse_cmdline()
            client.args.path = self.tmpdir
            client.cmd.push = mock.Mock()
        return client

    def assertRetired(self, reason):
        self.assertTrue(os.path.isfile(os.path.join(self.tmpdir,
                                                    'dead.package')))
        self.assertFalse(os.path.isfile(os.path.join(self.tmpdir,
                                                     'fedpkg.spec')))
        self.assertEqual(self._get_latest_commit(), reason)

    @mock.patch('pkgdb2client.PkgDB')
    def test_retire_with_namespace(self, PkgDB):
        self._setup_repo('ssh://git@pkgs.example.com/rpms/fedpkg')
        args = ['fedpkg', '--dist=master', 'retire', 'my reason']

        client = self._fake_client(args)
        client.retire()

        self.assertRetired('my reason')
        self.assertEqual(client.cmd.push.call_args_list, [mock.call()])
        self.assertEqual(PkgDB.return_value.retire_packages.call_args_list,
                         [mock.call('fedpkg', 'master', namespace='rpms')])

    @mock.patch('fedora_cert.read_user_cert')
    @mock.patch('pkgdb2client.PkgDB')
    def test_retire_without_namespace(self, PkgDB, read_user_cert):
        self._setup_repo('ssh://git@pkgs.example.com/fedpkg')
        args = ['fedpkg', '--dist=master', 'retire', 'my reason']

        read_user_cert.return_value = 'packager'

        client = self._fake_client(args)
        client.retire()

        self.assertRetired('my reason')
        self.assertEqual(client.cmd.push.call_args_list, [mock.call()])
        self.assertEqual(PkgDB.return_value.retire_packages.call_args_list,
                         [mock.call('fedpkg', 'master', namespace='rpms')])