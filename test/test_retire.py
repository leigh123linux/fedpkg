# -*- coding: utf-8 -*-

import os
import shutil
import subprocess
import tempfile

import mock
from six.moves import configparser

from fedpkg.cli import fedpkgClient
from utils import unittest

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
            ['git', 'config', 'user.name', 'John Doe'],
            cwd=self.tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.check_call(
            ['git', 'config', 'user.email', 'jdoe@example.com'],
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
                                cwd=self.tmpdir, stdout=subprocess.PIPE,
                                universal_newlines=True)
        out, err = proc.communicate()
        return out.strip()

    def _fake_client(self, args):
        config = configparser.SafeConfigParser()
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

    @mock.patch("requests.get", new=lambda *args, **kwargs: mock.Mock(status_code=404))
    def test_retire_with_namespace(self):
        self._setup_repo('ssh://git@pkgs.example.com/rpms/fedpkg')
        args = ['fedpkg', '--dist=master', 'retire', 'my reason']

        client = self._fake_client(args)
        client.retire()

        self.assertRetired('my reason')
        self.assertEqual(len(client.cmd.push.call_args_list), 1)

    @mock.patch("requests.get", new=lambda *args, **kwargs: mock.Mock(status_code=404))
    def test_retire_without_namespace(self):
        self._setup_repo('ssh://git@pkgs.example.com/fedpkg')
        args = ['fedpkg', '--dist=master', 'retire', 'my reason']

        client = self._fake_client(args)
        client.retire()

        self.assertRetired('my reason')
        self.assertEqual(len(client.cmd.push.call_args_list), 1)

    @mock.patch("requests.get", new=lambda *args, **kwargs: mock.Mock(status_code=404))
    def test_package_is_retired_already(self):
        self._setup_repo('ssh://git@pkgs.example.com/fedpkg')
        with open(os.path.join(self.tmpdir, 'dead.package'), 'w') as f:
            f.write('dead package')

        args = ['fedpkg', '--release=master', 'retire', 'my reason']
        client = self._fake_client(args)
        client.log = mock.Mock()
        client.retire()
        args, kwargs = client.log.warn.call_args
        self.assertIn('dead.package found, package probably already retired',
                      args[0])

    @mock.patch(
        "requests.get",
        new=lambda *args, **kwargs: mock.Mock(
            status_code=200, ok=True, json=lambda: {"state": "archived"}
        ),
    )
    def test_package_on_retired(self):
        self._setup_repo("ssh://git@pkgs.example.com/fedpkg")
        args = ["fedpkg", "--dist=master", "retire", "my reason"]

        client = self._fake_client(args)
        client.retire()
        args, kwargs = client.log.error.call_args
        self.assertIn("retire operation is not allowed", args[0])
