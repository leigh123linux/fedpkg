# -*- coding: utf-8 -*-
# fedpkg - a Python library for RPM Packagers
#
# Copyright (C) 2017 Red Hat Inc.
# Author(s): Chenxiong Qi <cqi@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

import six

from six.moves.configparser import NoOptionError
from six.moves.configparser import NoSectionError

from pyrpkg.errors import rpkgError
from utils import CliTestCase

from mock import call, patch, mock_open, PropertyMock


class TestUpdate(CliTestCase):
    """Test update command"""

    def setUp(self):
        super(TestUpdate, self).setUp()

        self.nvr_patcher = patch('fedpkg.Commands.nvr',
                                 new_callable=PropertyMock,
                                 return_value='fedpkg-1.29-9')
        self.mock_nvr = self.nvr_patcher.start()

        self.run_command_patcher = patch('fedpkg.Commands._run_command')
        self.mock_run_command = self.run_command_patcher.start()

        # Let's always use the bodhi 2 command line to test here
        self.get_bodhi_version_patcher = patch('fedpkg._get_bodhi_version',
                                               return_value=[2, 11, 0])
        self.mock_get_bodhi_version = self.get_bodhi_version_patcher.start()

        # Not write clog actually. Instead, file object will be mocked and
        # return fake clog content for tests.
        self.clog_patcher = patch('fedpkg.Commands.clog')
        self.clog_patcher.start()

        self.os_environ_patcher = patch.dict('os.environ', {'EDITOR': 'vi'})
        self.os_environ_patcher.start()

        self.fake_clog = '\n'.join([
            'Add tests for command update',
            'New command update - #1000',
            'Fix tests - #2000'
        ])

    def tearDown(self):
        self.os_environ_patcher.stop()
        self.clog_patcher.stop()
        self.get_bodhi_version_patcher.stop()
        self.run_command_patcher.stop()
        self.nvr_patcher.stop()
        super(TestUpdate, self).tearDown()

    def get_cli(self, cli_cmd, name='fedpkg', cfg=None):
        with patch('sys.argv', new=cli_cmd):
            return self.new_cli(name=name, cfg=cfg)

    def create_bodhi_update(self, cli):
        mocked_open = mock_open(read_data=self.fake_clog)
        with patch('__builtin__.open', mocked_open):
            with patch('os.unlink') as unlink:
                cli.update()

                # Ensure these files are removed in the end
                unlink.assert_has_calls([
                    call('bodhi.template'),
                    call('clog')
                ])

    def test_fail_if_missing_config_options(self):
        cli_cmd = ['fedpkg', '--path', self.cloned_repo_path, 'update']
        cli = self.get_cli(cli_cmd)

        with patch.object(cli.config, 'get',
                          side_effect=NoOptionError('url', 'bodhi')):
            six.assertRaisesRegex(
                self, rpkgError, 'Could not get bodhi options.', cli.update)

        with patch.object(cli.config, 'get',
                          side_effect=NoSectionError('bodhi')):
            six.assertRaisesRegex(
                self, rpkgError, 'Could not get bodhi options.', cli.update)

    @patch('os.path.isfile', return_value=False)
    def test_fail_if_bodhi_template_is_not_a_file(self, isfile):
        cli_cmd = ['fedpkg', '--path', self.cloned_repo_path, 'update']

        cli = self.get_cli(cli_cmd)
        six.assertRaisesRegex(
            self, rpkgError, 'No bodhi update details saved',
            self.create_bodhi_update, cli)

        self.mock_run_command.assert_called_once_with(
            ['vi', 'bodhi.template'], shell=True)

    @patch('os.path.isfile', return_value=True)
    @patch('hashlib.new')
    @patch('fedpkg.lookaside.FedoraLookasideCache.hash_file')
    @patch('fedpkg.Commands.user', new_callable=PropertyMock)
    def test_request_update(self, user, hash_file, hashlib_new, isfile):
        user.return_value = 'cqi'
        hashlib_new.return_value.hexdigest.return_value = 'origin hash'
        hash_file.return_value = 'different hash'

        cli_cmd = ['fedpkg', '--path', self.cloned_repo_path, 'update']

        cli = self.get_cli(cli_cmd)
        self.create_bodhi_update(cli)

        self.mock_run_command.assert_has_calls([
            call(['vi', 'bodhi.template'], shell=True),
            call(['bodhi', 'updates', 'new', '--file', 'bodhi.template',
                  '--user', 'cqi', self.mock_nvr.return_value],
                 shell=True)
        ])

    @patch('os.path.isfile', return_value=True)
    @patch('hashlib.new')
    @patch('fedpkg.lookaside.FedoraLookasideCache.hash_file')
    @patch('fedpkg.Commands.update', side_effect=OSError)
    def test_handle_any_errors_raised_when_execute_bodhi(
            self, update, hash_file, hashlib_new, isfile):
        hashlib_new.return_value.hexdigest.return_value = 'origin hash'
        hash_file.return_value = 'different hash'

        cli_cmd = ['fedpkg', '--path', self.cloned_repo_path, 'update']

        cli = self.get_cli(cli_cmd)
        six.assertRaisesRegex(
            self, rpkgError, 'Could not generate update request',
            self.create_bodhi_update, cli)

    @patch('os.path.isfile', return_value=True)
    @patch('hashlib.new')
    @patch('fedpkg.lookaside.FedoraLookasideCache.hash_file')
    def test_fail_if_bodhi_version_is_not_supported(
            self, hash_file, hashlib_new, isfile):
        # As of writing this test, only supports version v2 and <v2.
        self.mock_get_bodhi_version.return_value = [3, 1, 2]
        hashlib_new.return_value.hexdigest.return_value = 'origin hash'
        hash_file.return_value = 'different hash'

        cli_cmd = ['fedpkg', '--path', self.cloned_repo_path, 'update']

        cli = self.get_cli(cli_cmd)
        six.assertRaisesRegex(
            self, rpkgError, 'This system has bodhi v3, which is unsupported',
            self.create_bodhi_update, cli)

    @patch('os.path.isfile', return_value=True)
    @patch('hashlib.new')
    @patch('fedpkg.lookaside.FedoraLookasideCache.hash_file')
    @patch('fedpkg.Commands.user', new_callable=PropertyMock)
    def test_create_update_in_stage_bodhi(
            self, user, hash_file, hashlib_new, isfile):
        user.return_value = 'someone'
        self.mock_get_bodhi_version.return_value = [2, 8, 1]
        hashlib_new.return_value.hexdigest.return_value = 'origin hash'
        hash_file.return_value = 'different hash'

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path, 'update']
        cli = self.get_cli(cli_cmd,
                           name='fedpkg-stage',
                           cfg='fedpkg-stage.conf')
        self.create_bodhi_update(cli)

        self.mock_run_command.assert_has_calls([
            call(['vi', 'bodhi.template'], shell=True),
            call(['bodhi', 'updates', 'new', '--file', 'bodhi.template',
                  '--user', 'someone', '--staging', self.mock_nvr.return_value],
                 shell=True)
        ])
