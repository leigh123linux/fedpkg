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

import io
import os
import sys
import json
import pkg_resources

try:
    import unittest2 as unittest
except ImportError:
    import unittest

try:
    import bodhi
except ImportError:
    bodhi = None

from datetime import datetime, timedelta
from tempfile import mkdtemp
from os import rmdir
from freezegun import freeze_time

import six
from six.moves.configparser import NoOptionError
from six.moves.configparser import NoSectionError
from six.moves import StringIO

from pyrpkg.errors import rpkgError
from utils import CliTestCase
from fedpkg.bugzilla import BugzillaClient
from fedpkg.cli import check_bodhi_version

from mock import call, patch, PropertyMock, Mock


class TestUpdate(CliTestCase):
    """Test update command"""

    def setUp(self):
        super(TestUpdate, self).setUp()

        self.nvr_patcher = patch('fedpkg.Commands.nvr',
                                 new_callable=PropertyMock,
                                 return_value='fedpkg-1.29-9.fc27')
        self.mock_nvr = self.nvr_patcher.start()

        self.run_command_patcher = patch('fedpkg.Commands._run_command')
        self.mock_run_command = self.run_command_patcher.start()

        # Let's always use the bodhi 2 command line to test here
        self.check_bodhi_version_patcher = patch('fedpkg.cli.check_bodhi_version')
        self.mock_check_bodhi_version = self.check_bodhi_version_patcher.start()

        # Not write clog actually. Instead, file object will be mocked and
        # return fake clog content for tests.
        self.clog_patcher = patch('fedpkg.Commands.clog')
        self.clog_patcher.start()

        self.os_environ_patcher = patch.dict('os.environ', {'EDITOR': 'vi'})
        self.os_environ_patcher.start()

        self.fake_clog = list(six.moves.map(six.u, [
            'Add tests for command update',
            'New command update - #1000',
            'Fix tests - #2000',
            '处理一些Unicode字符číář',
        ]))
        clog_file = os.path.join(self.cloned_repo_path, 'clog')
        with io.open(clog_file, 'w', encoding='utf-8') as f:
            f.write(os.linesep.join(self.fake_clog))

    def tearDown(self):
        if os.path.exists('bodhi.template'):
            os.unlink('bodhi.template')
        os.unlink(os.path.join(self.cloned_repo_path, 'clog'))
        self.os_environ_patcher.stop()
        self.clog_patcher.stop()
        self.check_bodhi_version_patcher.stop()
        self.run_command_patcher.stop()
        self.nvr_patcher.stop()
        super(TestUpdate, self).tearDown()

    def get_cli(self, cli_cmd, name='fedpkg', cfg=None):
        with patch('sys.argv', new=cli_cmd):
            return self.new_cli(name=name, cfg=cfg)

    def assert_bodhi_update(self, cli):
        with patch('os.unlink') as unlink:
            cli.update()

            unlink.assert_has_calls([
                call('bodhi.template'),
                call('clog')
            ])

        with io.open('bodhi.template', encoding='utf-8') as f:
            bodhi_template = f.read()
        self.assertTrue(self.mock_nvr.return_value in bodhi_template)
        self.assertTrue('1000,2000' in bodhi_template)
        self.assertTrue(self.fake_clog[0] in bodhi_template)
        rest_clog = os.linesep.join([
            six.u('# {0}').format(line) for line in self.fake_clog[1:]
        ])
        self.assertTrue(rest_clog in bodhi_template)

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
            self.assert_bodhi_update, cli)

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
        self.assert_bodhi_update(cli)

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
            self.assert_bodhi_update, cli)

    @patch('os.path.isfile', return_value=True)
    @patch('hashlib.new')
    @patch('fedpkg.lookaside.FedoraLookasideCache.hash_file')
    @patch('fedpkg.Commands.user', new_callable=PropertyMock)
    def test_create_update_in_stage_bodhi(
            self, user, hash_file, hashlib_new, isfile):
        user.return_value = 'someone'
        hashlib_new.return_value.hexdigest.return_value = 'origin hash'
        hash_file.return_value = 'different hash'

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path, 'update']
        cli = self.get_cli(cli_cmd,
                           name='fedpkg-stage',
                           cfg='fedpkg-stage.conf')
        self.assert_bodhi_update(cli)

        self.mock_run_command.assert_has_calls([
            call(['vi', 'bodhi.template'], shell=True),
            call(['bodhi', 'updates', 'new', '--file', 'bodhi.template',
                  '--user', 'someone', '--staging', self.mock_nvr.return_value],
                 shell=True)
        ])


@patch.object(BugzillaClient, 'client')
class TestRequestRepo(CliTestCase):
    """Test the request-repo command"""

    def setUp(self):
        self.mock_bug = Mock()
        self.mock_bug.creator = 'Tom Hanks'
        self.mock_bug.component = 'Package Review'
        self.mock_bug.product = 'Fedora'
        self.mock_bug.assigned_to = 'Tom Brady'
        self.mock_bug.setter = 'Tom Brady'
        mod_date = Mock()
        mod_date.value = datetime.utcnow().strftime('%Y%m%dT%H:%M:%S')
        self.mock_bug.flags = [{
            'status': '+',
            'name': 'fedora-review',
            'type_id': 65,
            'is_active': 1,
            'id': 1441813,
            'setter': 'Tom Brady',
            'modification_date': mod_date
        }]
        self.mock_bug.summary = ('Review Request: nethack - A rogue-like '
                                 'single player dungeon exploration game')
        super(TestRequestRepo, self).setUp()

    def get_cli(self, cli_cmd, name='fedpkg-stage', cfg='fedpkg-stage.conf',
                user_cfg='fedpkg-user-stage.conf'):
        with patch('sys.argv', new=cli_cmd):
            return self.new_cli(name=name, cfg=cfg, user_cfg=user_cfg)

    @patch('requests.post')
    @patch('sys.stdout', new=StringIO())
    def test_request_repo(self, mock_request_post, mock_bz):
        """Tests a standard request-repo call"""
        self.mock_bug.summary = ('Review Request: testpkg - a description')
        mock_bz.getbug.return_value = self.mock_bug
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        cli.request_repo()

        expected_issue_content = {
            'action': 'new_repo',
            'branch': 'master',
            'bug_id': 1441813,
            'description': '',
            'exception': False,
            'monitor': 'monitoring',
            'namespace': 'rpms',
            'repo': 'testpkg',
            'summary': 'a description',
            'upstreamurl': ''
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('sys.stdout', new=StringIO())
    def test_request_repo_override(self, mock_request_post, mock_bz):
        """Tests a request-repo call with an overridden repo name"""
        mock_bz.getbug.return_value = self.mock_bug
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        cli.request_repo()

        expected_issue_content = {
            'action': 'new_repo',
            'branch': 'master',
            'bug_id': 1441813,
            'description': '',
            'exception': False,
            'monitor': 'monitoring',
            'namespace': 'rpms',
            'repo': 'nethack',
            'summary': ('A rogue-like single player dungeon exploration '
                        'game'),
            'upstreamurl': ''
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('sys.stdout', new=StringIO())
    def test_request_repo_module(self, mock_request_post, mock_bz):
        """Tests a request-repo call for a new module"""
        self.mock_bug.product = 'Fedora Modules'
        self.mock_bug.component = 'Module Review'
        mock_bz.getbug.return_value = self.mock_bug
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'modules/nethack', 'request-repo']
        cli = self.get_cli(cli_cmd)
        cli.request_repo()

        expected_issue_content = {
            'action': 'new_repo',
            'branch': 'master',
            'bug_id': '',
            'description': '',
            'exception': False,
            'monitor': 'monitoring',
            'namespace': 'modules',
            'repo': 'nethack',
            'summary': (''),
            'upstreamurl': ''
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('sys.stdout', new=StringIO())
    def test_request_repo_container(self, mock_request_post, mock_bz):
        """Tests a request-repo call for a new container"""
        self.mock_bug.product = 'Fedora Container Images'
        self.mock_bug.component = 'Container Review'
        mock_bz.getbug.return_value = self.mock_bug
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'container/nethack', 'request-repo',
                   '1441813']
        cli = self.get_cli(cli_cmd)
        cli.request_repo()

        expected_issue_content = {
            'action': 'new_repo',
            'branch': 'master',
            'bug_id': 1441813,
            'description': '',
            'exception': False,
            'monitor': 'monitoring',
            'namespace': 'container',
            'repo': 'nethack',
            'summary': ('A rogue-like single player dungeon exploration '
                        'game'),
            'upstreamurl': ''
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('sys.stdout', new=StringIO())
    def test_request_repo_with_optional_details(
            self, mock_request_post, mock_bz):
        """Tests a request-repo call with the optional details"""
        mock_bz.getbug.return_value = self.mock_bug
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813', '-d',
                   'a description', '-s', 'a summary', '-m', 'no-monitoring',
                   '-u', 'http://test.local']
        cli = self.get_cli(cli_cmd)
        cli.request_repo()

        expected_issue_content = {
            'action': 'new_repo',
            'branch': 'master',
            'bug_id': 1441813,
            'description': 'a description',
            'exception': False,
            'monitor': 'no-monitoring',
            'namespace': 'rpms',
            'repo': 'nethack',
            'summary': 'a summary',
            'upstreamurl': 'http://test.local'
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('sys.stdout', new=StringIO())
    def test_request_repo_exception(self, mock_request_post, mock_bz):
        """Tests a request-repo call with the exception flag"""
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '--exception']
        cli = self.get_cli(cli_cmd)
        cli.request_repo()

        expected_issue_content = {
            'action': 'new_repo',
            'branch': 'master',
            'bug_id': '',
            'description': '',
            'exception': True,
            'monitor': 'monitoring',
            'namespace': 'rpms',
            'repo': 'nethack',
            'summary': '',
            'upstreamurl': ''
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)
        # Since it is an exception, Bugzilla will not have been queried
        mock_bz.getbug.assert_not_called()

    def test_request_repo_wrong_package(self, mock_bz):
        """Tests request-repo errors when the package is wrong"""
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'not-nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = ('The package in the Bugzilla bug "nethack" doesn\'t '
                          'match the one provided "not-nethack"')
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_wrong_bug_product(self, mock_bz):
        """Tests request-repo errors when the bug product is not Fedora"""
        self.mock_bug.product = 'Red Hat'
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = \
            'The Bugzilla bug provided is not for "Fedora" or "Fedora EPEL"'
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_invalid_summary(self, mock_bz):
        """Tests request-repo errors when the bug summary has no colon"""
        self.mock_bug.summary = 'I am so wrong'
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = \
            'Invalid title for this Bugzilla bug (no ":" present)'
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_invalid_summary_two(self, mock_bz):
        """Tests request-repo errors when the bug summary has no dash"""
        self.mock_bug.summary = 'So:Wrong'
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = \
            'Invalid title for this Bugzilla bug (no "-" present)'
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_wrong_summary(self, mock_bz):
        """Tests request-repo errors when the bug summary is wrong"""
        self.mock_bug.summary = ('Review Request: fedpkg - lorum ipsum')
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = ('The package in the Bugzilla bug "fedpkg" doesn\'t '
                          'match the one provided "nethack"')
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_expired_bug(self, mock_bz):
        """Tests request-repo errors when the bug was approved over 60 days ago
        """
        self.mock_bug.flags[0]['modification_date'].value = \
            (datetime.utcnow() - timedelta(days=75)).strftime(
                '%Y%m%dT%H:%M:%S')
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = \
            'The Bugzilla bug\'s review was approved over 60 days ago'
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_bug_not_approved(self, mock_bz):
        """Tests request-repo errors when the bug is not approved"""
        self.mock_bug.flags[0]['name'] = 'something else'
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = 'The Bugzilla bug is not approved yet'
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_bug_not_assigned(self, mock_bz):
        """Tests request-repo errors when the bug is not assigned"""
        self.mock_bug.assigned_to = None
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = 'The Bugzilla bug provided is not assigned to anyone'
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_repo_invalid_name(self, mock_bz):
        """Tests request-repo errors when the repo name is invalid"""
        self.mock_bug.product = 'Red Hat'
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', '$nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        expected_error = (
            'The repository name "$nethack" is invalid. It must be at least '
            'two characters long with only letters, numbers, hyphens, '
            'underscores, plus signs, and/or periods. Please note that the '
            'project cannot start with a period or a plus sign.')
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    @patch('requests.post')
    def test_request_repo_pagure_error(self, mock_request_post, mock_bz):
        """Tests a standard request-repo call when the Pagure API call fails"""
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo', '1441813']
        cli = self.get_cli(cli_cmd)
        mock_rv = Mock()
        mock_rv.ok = False
        mock_rv.json.return_value = {'error': 'some error'}
        mock_request_post.return_value = mock_rv
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            expected_error = ('The following error occurred while creating a '
                              'new issue in Pagure: some error')
            self.assertEqual(str(error), expected_error)

    def test_request_repo_no_bug(self, mock_bz):
        """Tests request-repo errors when no bug or exception is provided"""
        self.mock_bug.product = 'Red Hat'
        mock_bz.getbug.return_value = self.mock_bug
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-repo']
        cli = self.get_cli(cli_cmd)
        expected_error = \
            'A Bugzilla bug is required on new repository requests'
        try:
            cli.request_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)


class TestRequestBranch(CliTestCase):
    """Test the request-branch command"""

    def setUp(self):
        super(TestRequestBranch, self).setUp()

    def tearDown(self):
        super(TestRequestBranch, self).tearDown()

    def get_cli(self, cli_cmd, name='fedpkg-stage', cfg='fedpkg-stage.conf',
                user_cfg='fedpkg-user-stage.conf'):
        with patch('sys.argv', new=cli_cmd):
            return self.new_cli(name=name, cfg=cfg, user_cfg=user_cfg)

    @patch('requests.post')
    @patch('fedpkg.cli.get_release_branches')
    @patch('sys.stdout', new=StringIO())
    def test_request_branch(self, mock_grb, mock_request_post):
        """Tests request-branch"""
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv
        # Checkout the f27 branch
        self.run_cmd(['git', 'checkout', 'f27'], cwd=self.cloned_repo_path)

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   'request-branch']
        cli = self.get_cli(cli_cmd)
        cli.request_branch()

        expected_issue_content = {
            'action': 'new_branch',
            'repo': 'testpkg',
            'namespace': 'rpms',
            'branch': 'f27',
            'create_git_branch': True
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('fedpkg.cli.get_release_branches')
    @patch('sys.stdout', new=StringIO())
    def test_request_branch_override(self, mock_grb, mock_request_post):
        """Tests request-branch with an overriden package and branch name"""
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-branch', 'f27']
        cli = self.get_cli(cli_cmd)
        cli.request_branch()

        expected_issue_content = {
            'action': 'new_branch',
            'repo': 'nethack',
            'namespace': 'rpms',
            'branch': 'f27',
            'create_git_branch': True
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('fedpkg.cli.get_release_branches')
    @patch('sys.stdout', new=StringIO())
    def test_request_branch_module(self, mock_grb, mock_request_post):
        """Tests request-branch for a new module branch"""
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'modules/nethack', 'request-branch', 'f27']
        cli = self.get_cli(cli_cmd)
        cli.request_branch()

        expected_issue_content = {
            'action': 'new_branch',
            'repo': 'nethack',
            'namespace': 'modules',
            'branch': 'f27',
            'create_git_branch': True
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('fedpkg.cli.get_release_branches')
    @patch('sys.stdout', new=StringIO())
    def test_request_branch_container(self, mock_grb, mock_request_post):
        """Tests request-branch for a new container branch"""
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {'issue': {'id': 2}}
        mock_request_post.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'container/nethack', 'request-branch',
                   'f27']
        cli = self.get_cli(cli_cmd)
        cli.request_branch()

        expected_issue_content = {
            'action': 'new_branch',
            'repo': 'nethack',
            'namespace': 'container',
            'branch': 'f27',
            'create_git_branch': True
        }
        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)
        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/2')
        self.assertEqual(output, expected_output)

    @patch('requests.post')
    @patch('fedpkg.cli.get_release_branches')
    @patch('fedpkg.cli.verify_sls')
    @patch('sys.stdout', new=StringIO())
    def test_request_branch_sls(self, mock_verify_sls, mock_grb,
                                mock_request_post):
        """Tests request-branch with service levels"""
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])
        responses = []
        for idx in range(2, 5):
            mock_rv_post = Mock()
            mock_rv_post.ok = True
            mock_rv_post.json.return_value = {'issue': {'id': idx}}
            responses.append(mock_rv_post)
        mock_request_post.side_effect = responses

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-branch', '9', '--sl',
                   'security_fixes:2030-12-01', 'bug_fixes:2030-12-01']
        cli = self.get_cli(cli_cmd)
        cli.request_branch()

        # Get the data that was submitted to Pagure
        output = sys.stdout.getvalue().strip()
        # Three bugs are filed.  One for the rpm branch, and one for a new
        # module repo, and one for the matching module branch.
        expected_output = (
            'https://pagure.stg.example.com/releng/'
            'fedora-scm-requests/issue/2\n'
            'https://pagure.stg.example.com/releng/'
            'fedora-scm-requests/issue/3\n'
            'https://pagure.stg.example.com/releng/'
            'fedora-scm-requests/issue/4'
        )
        self.assertMultiLineEqual(output, expected_output)

        # Check for rpm branch..
        expected_issue_content = {
            'action': 'new_branch',
            'repo': 'nethack',
            'namespace': 'rpms',
            'branch': '9',
            'create_git_branch': True,
            'sls': {
                'security_fixes': '2030-12-01',
                'bug_fixes': '2030-12-01'
            }
        }
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertDictEqual(expected_issue_content, actual_issue_content)

        # Check for the module repo request..
        summary = u'Automatically requested module for rpms/nethack:9.'
        expected_issue_content = {
            u'action': u'new_repo',
            u'branch': u'master',
            u'bug_id': u'',
            u'description': summary,
            u'exception': True,
            u'monitor': u'no-monitoring',
            u'namespace': u'modules',
            u'repo': u'nethack',
            u'summary': summary,
            u'upstreamurl': u''
        }
        post_data = mock_request_post.call_args_list[1][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertDictEqual(expected_issue_content, actual_issue_content)

        # Check for module branch..
        expected_issue_content = {
            'action': 'new_branch',
            'repo': 'nethack',
            'namespace': 'modules',
            'branch': '9',
            'create_git_branch': True,
            'sls': {
                'security_fixes': '2030-12-01',
                'bug_fixes': '2030-12-01'
            }
        }
        post_data = mock_request_post.call_args_list[2][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertDictEqual(expected_issue_content, actual_issue_content)

    @patch('requests.post')
    @patch('fedpkg.cli.get_release_branches')
    @patch('sys.stdout', new=StringIO())
    def test_request_branch_all_releases(self, mock_grb, mock_request_post):
        """Tests request-branch with the '--all-releases' option """
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])
        post_side_effect = []
        for i in range(1, 4):
            mock_rv = Mock()
            mock_rv.ok = True
            mock_rv.json.return_value = {'issue': {'id': i}}
            post_side_effect.append(mock_rv)
        mock_request_post.side_effect = post_side_effect

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-branch',
                   '--all-releases']
        cli = self.get_cli(cli_cmd)
        cli.request_branch()

        for i in range(3):
            expected_issue_content = {
                'action': 'new_branch',
                'repo': 'nethack',
                'namespace': 'rpms',
                'branch': 'f' + str(27 - i),
                'create_git_branch': True
            }
            post_data = mock_request_post.call_args_list[i][1]['data']
            actual_issue_content = json.loads(json.loads(
                post_data)['issue_content'].strip('```'))
            self.assertEqual(expected_issue_content, actual_issue_content)

        output = sys.stdout.getvalue().strip()
        expected_output = """\
https://pagure.stg.example.com/releng/fedora-scm-requests/issue/1
https://pagure.stg.example.com/releng/fedora-scm-requests/issue/2
https://pagure.stg.example.com/releng/fedora-scm-requests/issue/3"""
        self.assertEqual(output, expected_output)

    def test_request_branch_invalid_use_of_all_releases(self):
        """Tests request-branch with a branch and the '--all-releases' option
        """
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-branch', 'f27',
                   '--all-releases']
        cli = self.get_cli(cli_cmd)
        expected_error = \
            'You cannot specify a branch with the "--all-releases" option'
        try:
            cli.request_branch()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_branch_invalid_use_of_all_releases_sl(self):
        """Tests request-branch with an SL and the '--all-releases' option
        """
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-branch',
                   '--all-releases', '--sl', 'security_fixes:2020-01-01']
        cli = self.get_cli(cli_cmd)
        expected_error = ('You cannot specify service levels with the '
                          '"--all-releases" option')
        try:
            cli.request_branch()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    @patch('fedpkg.cli.get_release_branches')
    def test_request_branch_invalid_sls(self, mock_grb):
        """Tests request-branch with invalid service levels"""
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-branch', '9', '--sl',
                   'security_fixes-2030-12-01', 'bug_fixes:2030-12-01']
        cli = self.get_cli(cli_cmd)
        expected_error = \
            'The SL "security_fixes-2030-12-01" is in an invalid format'
        try:
            cli.request_branch()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    @patch('fedpkg.cli.get_release_branches')
    def test_request_branch_sls_on_release_branch_error(self, mock_grb):
        """Tests request-branch with a release branch and service levels"""
        mock_grb.return_value = set(['el6', 'epel7', 'f25', 'f26', 'f27'])

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'nethack', 'request-branch', 'f27', '--sl',
                   'security_fixes-2030-12-01', 'bug_fixes:2030-12-01']
        cli = self.get_cli(cli_cmd)
        expected_error = 'You can\'t provide SLs for release branches'
        try:
            cli.request_branch()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_branch_invalid_module_branch_name(self):
        """Test request-branch raises an exception when a invalid module branch
        name is supplied"""
        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'modules/nethack', 'request-branch',
                   'some:branch']
        cli = self.get_cli(cli_cmd)
        expected_error = (
            'Only characters, numbers, periods, dashes, underscores, and '
            'pluses are allowed in module branch names')
        try:
            cli.request_branch()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)

    def test_request_branch_no_branch(self):
        """Test request-branch raises an exception when a branch isn't supplied
        """
        tempdir = mkdtemp()
        cli_cmd = ['fedpkg-stage', '--path', tempdir,
                   '--module-name', 'nethack', 'request-branch']
        cli = self.get_cli(cli_cmd)
        expected_error = (
            'You must specify a branch if you are not in a git repository')
        try:
            cli.request_branch()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)
        finally:
            rmdir(tempdir)

    @patch('requests.get')
    def test_request_branch_invalid_epel_package(self, mock_get):
        """Test request-branch raises an exception when an EPEL branch is
        requested but ths package is already an EL package on all supported
        arches"""
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {
            'arches': ['noarch', 'x86_64', 'i686', 'ppc64', 'ppc', 'ppc64le'],
            'packages': {
                'kernel': {'arch': [
                    'noarch', 'x86_64', 'ppc64', 'ppc64le']},
                'glibc': {'arch': [
                    'i686', 'x86_64', 'ppc', 'ppc64', 'ppc64le']}
            }
        }
        mock_get.return_value = mock_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'kernel', 'request-branch', 'epel7']
        cli = self.get_cli(cli_cmd)
        expected_error = (
            'This package is already an EL package and is built on all '
            'supported arches, therefore, it cannot be in EPEL. If this is a '
            'mistake or you have an exception, please contact the Release '
            'Engineering team.')
        with six.assertRaisesRegex(self, rpkgError, expected_error):
            cli.request_branch()


class TestRequestTestsRepo(CliTestCase):
    """Test the request-tests-repo command"""

    def setUp(self):
        super(TestRequestTestsRepo, self).setUp()

    def tearDown(self):
        super(TestRequestTestsRepo, self).tearDown()

    def get_cli(self, cli_cmd, name='fedpkg-stage', cfg='fedpkg-stage.conf',
                user_cfg='fedpkg-user-stage.conf'):
        with patch('sys.argv', new=cli_cmd):
            return self.new_cli(name=name, cfg=cfg, user_cfg=user_cfg)

    @patch('requests.post')
    @patch('requests.get')
    @patch('sys.stdout', new=StringIO())
    def test_request_tests_repo(self, mock_request_get, mock_request_post):
        """Tests request-tests-repo"""

        # mock the request.get from assert_new_tests_repo
        mock_get_rv = Mock()
        mock_get_rv.ok = False
        mock_request_get.return_value = mock_get_rv

        # mock the request.post to Pagure
        mock_post_rv = Mock()
        mock_post_rv.ok = True
        mock_post_rv.json.return_value = {'issue': {'id': 1}}
        mock_request_post.return_value = mock_post_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'foo', 'request-tests-repo',
                   'Some description']
        cli = self.get_cli(cli_cmd)
        cli.request_tests_repo()

        expected_issue_content = {
            'action': 'new_repo',
            'repo': 'foo',
            'namespace': 'tests',
            'description': 'Some description'
        }

        # Get the data that was submitted to Pagure
        post_data = mock_request_post.call_args_list[0][1]['data']
        actual_issue_content = json.loads(json.loads(
            post_data)['issue_content'].strip('```'))
        self.assertEqual(expected_issue_content, actual_issue_content)

        output = sys.stdout.getvalue().strip()
        expected_output = ('https://pagure.stg.example.com/releng/'
                           'fedora-scm-requests/issue/1')
        self.assertEqual(output, expected_output)

    @patch('requests.get')
    def test_request_tests_repo_exists(self, mock_request_get):
        """Tests request-tests-repo exception if repo already exists"""

        # mock the request.get from assert_new_tests_repo
        mock_get_rv = Mock()
        mock_get_rv.ok = True
        mock_request_get.return_value = mock_get_rv

        cli_cmd = ['fedpkg-stage', '--path', self.cloned_repo_path,
                   '--module-name', 'foo', 'request-tests-repo',
                   'Some description']
        cli = self.get_cli(cli_cmd)

        expected_error = (
            'Repository git://pkgs.stg.example.com/tests/foo already exists')

        try:
            cli.request_tests_repo()
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            self.assertEqual(str(error), expected_error)


class TestCheckBodhiVersion(unittest.TestCase):
    """Test check_bodhi_version"""

    @patch('pkg_resources.get_distribution')
    def test_no_2_x_version_installed(self, get_distribution):
        get_distribution.side_effect = pkg_resources.DistributionNotFound

        six.assertRaisesRegex(
            self, rpkgError, r'bodhi-client < 2\.0 is not supported\.',
            check_bodhi_version)


@unittest.skipUnless(bodhi, 'Skip if no supported bodhi-client is available')
class TestBodhiOverride(CliTestCase):
    """Test command override"""

    @patch('fedpkg.cli.check_bodhi_version')
    @patch('fedpkg.BodhiClient')
    def test_create_for_given_build(self, BodhiClient, check_bodhi_version):
        bodhi_client = BodhiClient.return_value
        bodhi_client.list_overrides.return_value = {'total': 0}
        expiration_date = datetime.now() + timedelta(days=7)
        new_override = {
            'expiration_date': expiration_date.strftime('%Y-%m-%d %H:%M:%S'),
            'notes': 'build for fedpkg'
        }
        bodhi_client.save_override.return_value = new_override

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'create',
            '--duration', '7', '--notes', 'build for fedpkg',
            'rpkg-1.54-1.fc28'
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            with patch.object(cli.cmd, 'log') as log:
                cli.create_buildroot_override()

                log.info.assert_any_call('Expiration date: %s',
                                         new_override['expiration_date'])
                log.info.assert_any_call('Notes: %s', new_override['notes'])

        bodhi_client.save_override.assert_called_once_with(
            nvr='rpkg-1.54-1.fc28',
            duration=7,
            notes='build for fedpkg')

    @patch('fedpkg.cli.check_bodhi_version')
    @patch('fedpkg.BodhiClient')
    @patch('fedpkg.Commands.nvr', new_callable=PropertyMock)
    def test_create_from_current_branch(
            self, nvr, BodhiClient, check_bodhi_version):
        nvr.return_value = 'rpkg-1.54-2.fc28'
        bodhi_client = BodhiClient.return_value
        bodhi_client.list_overrides.return_value = {'total': 0}

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'create',
            '--duration', '7', '--notes', 'build for fedpkg',
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            cli.create_buildroot_override()

        bodhi_client.save_override.assert_called_once_with(
            nvr='rpkg-1.54-2.fc28',
            duration=7,
            notes='build for fedpkg')

    @patch('fedpkg.cli.check_bodhi_version')
    @patch('fedpkg.BodhiClient')
    @patch('fedpkg.Commands.nvr', new_callable=PropertyMock)
    def test_override_already_exists_but_expired(
            self, nvr, BodhiClient, check_bodhi_version):
        nvr.return_value = 'rpkg-1.54-2.fc28'
        today = datetime.today()
        fake_expiration_date = today - timedelta(days=10)
        BodhiClient.return_value.list_overrides.return_value = {
            'total': 1,
            'overrides': [{
                'expiration_date': fake_expiration_date.strftime(
                    '%Y-%m-%d %H:%M:%S')
            }]
        }

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'create',
            '--duration', '7', '--notes', 'build for fedpkg',
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            with patch.object(cli.cmd, 'log') as log:
                cli.create_buildroot_override()
                log.info.assert_any_call(
                    'Buildroot override for %s exists and is expired. Consider'
                    ' using command `override extend` to extend duration.',
                    'rpkg-1.54-2.fc28')

    @patch('fedpkg.cli.check_bodhi_version')
    @patch('fedpkg.BodhiClient')
    @patch('fedpkg.Commands.nvr', new_callable=PropertyMock)
    def test_override_already_exists_but_not_expired(
            self, nvr, BodhiClient, check_bodhi_version):
        nvr.return_value = 'rpkg-1.54-2.fc28'
        today = datetime.today()
        fake_expiration_date = today + timedelta(days=10)
        BodhiClient.return_value.list_overrides.return_value = {
            'total': 1,
            'overrides': [{
                'expiration_date': fake_expiration_date.strftime(
                    '%Y-%m-%d %H:%M:%S')
            }]
        }

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'create',
            '--duration', '7', '--notes', 'build for fedpkg',
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            with patch.object(cli.cmd, 'log') as log:
                cli.create_buildroot_override()
                log.info.assert_any_call(
                    'Buildroot override for %s already exists and not '
                    'expired.', 'rpkg-1.54-2.fc28')


@unittest.skipUnless(bodhi, 'Skip if no supported bodhi-client is available')
class TestBodhiOverrideExtend(CliTestCase):
    """Test command `override extend`"""

    def setUp(self):
        super(TestBodhiOverrideExtend, self).setUp()

        # No need to check bodhi version for tests
        self.cbv_p = patch('fedpkg.cli.check_bodhi_version')
        self.cbv_p.start()

        self.anon_kojisession_p = patch('fedpkg.Commands.anon_kojisession',
                                        new_callable=PropertyMock)
        self.anon_kojisession_m = self.anon_kojisession_p.start()
        self.kojisession = self.anon_kojisession_m.return_value

        # Fake build returned from Koji for the specified build NVR in tests
        self.kojisession.getBuild.return_value = {'build_id': 1}

    def tearDown(self):
        self.anon_kojisession_p.stop()
        self.cbv_p.stop()
        super(TestBodhiOverrideExtend, self).tearDown()

    def test_specified_build_not_exist(self):
        self.kojisession.getBuild.return_value = None

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'extend', '7', 'somepkg-1.54-2.fc28'
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            six.assertRaisesRegex(
                self, rpkgError, 'Build somepkg-1.54-2.fc28 does not exist.',
                cli.extend_buildroot_override)

    @patch('fedpkg.BodhiClient.list_overrides')
    def test_no_override_for_build(self, list_overrides):
        list_overrides.return_value = {'total': 0}

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'extend', '7', 'somepkg-1.54-2.fc28'
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            with patch.object(cli.cmd, 'log') as log:
                cli.extend_buildroot_override()
                log.info.assert_any_call('No buildroot override for build %s',
                                         'somepkg-1.54-2.fc28')

    @patch('fedpkg.BodhiClient.list_overrides')
    @patch('fedpkg.BodhiClient.csrf')
    @patch('fedpkg.BodhiClient.send_request')
    def test_extend_override_by_days(
            self, send_request, csrf, list_overrides):
        utcnow = datetime.utcnow()
        override_expiration_date = utcnow + timedelta(days=7)
        build_nvr = 'somepkg-1.54-2.fc28'
        build_override = {
            'expiration_date':
                override_expiration_date.strftime('%Y-%m-%d %H:%M:%S'),
            'nvr': build_nvr,
            'notes': 'build for other package',
            'build': {'nvr': build_nvr},
            'submitter': {'name': 'someone'},
            'expired_date': utcnow - timedelta(days=20)
        }

        list_overrides.return_value = {
            'total': 1,
            'overrides': [build_override]
        }
        edited_override = build_override.copy()
        expected_expiration_date = override_expiration_date + timedelta(days=2)
        edited_override['expiration_date'] = \
            expected_expiration_date.strftime('%Y-%m-%d %H:%M:%S')
        send_request.return_value = edited_override

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'extend', '2', build_nvr
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            cli.extend_buildroot_override()

        # Ensure no microsecond is included in the expected expiration data
        new_date = override_expiration_date + timedelta(days=2)
        expected_expiration_date = datetime(year=new_date.year,
                                            month=new_date.month,
                                            day=new_date.day,
                                            hour=new_date.hour,
                                            minute=new_date.minute,
                                            second=new_date.second)
        request_data = {
            'expiration_date': expected_expiration_date,
            'nvr': build_nvr,
            'notes': build_override['notes'],
            'edited': build_nvr,
            'csrf_token': csrf.return_value,
        }
        send_request.assert_called_once_with(
            'overrides/', verb='POST', auth=True, data=request_data)

    @patch('fedpkg.BodhiClient.list_overrides')
    @patch('fedpkg.BodhiClient.csrf')
    @patch('fedpkg.BodhiClient.send_request')
    def test_extend_override_by_specific_date(
            self, send_request, csrf, list_overrides):
        utcnow = datetime.utcnow()
        override_expiration_date = utcnow + timedelta(days=7)
        build_nvr = 'somepkg-1.54-2.fc28'
        build_override = {
            'expiration_date':
                override_expiration_date.strftime('%Y-%m-%d %H:%M:%S'),
            'nvr': build_nvr,
            'notes': 'build for other package',
            'build': {'nvr': build_nvr},
            'submitter': {'name': 'someone'},
            'expired_date': utcnow - timedelta(days=20)
        }

        list_overrides.return_value = {
            'total': 1,
            'overrides': [build_override]
        }

        new_expiration_date = override_expiration_date + timedelta(days=4)
        # Ensure no microsecond is included in the expected expiration data
        expected_expiration_date = datetime(
            year=new_expiration_date.year,
            month=new_expiration_date.month,
            day=new_expiration_date.day,
            hour=override_expiration_date.hour,
            minute=override_expiration_date.minute,
            second=override_expiration_date.second)

        edited_override = build_override.copy()
        edited_override['expiration_date'] = \
            expected_expiration_date.strftime('%Y-%m-%d %H:%M:%S')
        send_request.return_value = edited_override

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'extend', new_expiration_date.strftime('%Y-%m-%d'),
            build_nvr
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            cli.extend_buildroot_override()

        request_data = {
            'expiration_date': expected_expiration_date,
            'nvr': build_nvr,
            'notes': build_override['notes'],
            'edited': build_nvr,
            'csrf_token': csrf.return_value,
        }
        send_request.assert_called_once_with(
            'overrides/', verb='POST', auth=True, data=request_data)

    @patch('fedpkg.BodhiClient.list_overrides')
    @patch('fedpkg.BodhiClient.csrf')
    @patch('fedpkg.BodhiClient.send_request')
    @freeze_time('2018-06-08 16:17:30')
    def test_extend_for_expired_override(
            self, send_request, csrf, list_overrides):
        utcnow = datetime.utcnow()
        # Make override expired
        override_expiration_date = utcnow - timedelta(days=7)
        build_nvr = 'somepkg-1.54-2.fc28'
        build_override = {
            'expiration_date':
                override_expiration_date.strftime('%Y-%m-%d %H:%M:%S'),
            'nvr': build_nvr,
            'notes': 'build for other package',
            'build': {'nvr': build_nvr},
            'submitter': {'name': 'someone'},
            'expired_date': utcnow - timedelta(days=20)
        }

        list_overrides.return_value = {
            'total': 1,
            'overrides': [build_override]
        }

        # Ensure no microsecond is included in the expected expiration data
        new_date = utcnow + timedelta(days=2)
        expected_expiration_date = datetime(
            year=new_date.year,
            month=new_date.month,
            day=new_date.day,
            hour=new_date.hour,
            minute=new_date.minute,
            second=new_date.second)

        edited_override = build_override.copy()
        edited_override['expiration_date'] = \
            expected_expiration_date.strftime('%Y-%m-%d %H:%M:%S')
        send_request.return_value = edited_override

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'extend', '2', build_nvr
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            cli.extend_buildroot_override()

        request_data = {
            'expiration_date': expected_expiration_date,
            'nvr': build_nvr,
            'notes': build_override['notes'],
            'edited': build_nvr,
            'csrf_token': csrf.return_value,
        }
        send_request.assert_called_once_with(
            'overrides/', verb='POST', auth=True, data=request_data)

    @patch('fedpkg.BodhiClient.list_overrides')
    @patch('fedpkg.BodhiClient.csrf')
    @patch('fedpkg.BodhiClient.extend_override')
    def test_error_handled_properly_when_fail_to_request(
            self, extend_override, csrf, list_overrides):
        extend_override.side_effect = Exception

        utcnow = datetime.utcnow()
        override_expiration_date = utcnow + timedelta(days=7)
        build_nvr = 'somepkg-1.54-2.fc28'

        list_overrides.return_value = {
            'total': 1,
            'overrides': [{
                'expiration_date':
                    override_expiration_date.strftime('%Y-%m-%d %H:%M:%S'),
                'nvr': build_nvr,
                'notes': 'build for other package',
                'build': {'nvr': build_nvr},
                'submitter': {'name': 'someone'},
                'expired_date': utcnow - timedelta(days=20)
            }]
        }

        cli_cmd = [
            'fedpkg', '--path', self.cloned_repo_path,
            'override', 'extend', '2', build_nvr
        ]

        with patch('sys.argv', new=cli_cmd):
            cli = self.new_cli()
            six.assertRaisesRegex(self, rpkgError, '',
                                  cli.extend_buildroot_override)
