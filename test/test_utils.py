# -*- coding: utf-8 -*-
# fedpkg - a Python library for RPM Packagers
#
# Copyright (C) 2017 Red Hat Inc.
# Author(s): Matt Prahl <mprahl@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

import json
import six

from freezegun import freeze_time
from mock import patch, Mock
from pyrpkg.errors import rpkgError
from requests.exceptions import ConnectionError
from six.moves.configparser import NoOptionError
from six.moves.configparser import NoSectionError

from fedpkg import utils
from utils import unittest


class TestUtils(unittest.TestCase):
    """Test functions in fedpkg.utils"""

    @patch('requests.get')
    def test_get_sl_type(self, mock_get):
        """Test get_sl_type"""
        sl_type = {
            'id': 1,
            'name': 'security_fixes',
            'description': 'security_fixes',
        }
        mock_rv = Mock()
        mock_rv.ok = True
        mock_rv.json.return_value = {
            'count': 1,
            'results': [sl_type]
        }
        mock_get.return_value = mock_rv
        rv = utils.get_sl_type('http://pdc.local/', 'securty_fixes')
        self.assertEqual(rv, sl_type)

    @patch('requests.get')
    def test_get_sl_type_pdc_error(self, mock_request_get):
        """Test get_sl_type when PDC errors"""
        mock_rv = Mock()
        mock_rv.ok = False
        mock_rv.text = 'Some error'
        mock_request_get.return_value = mock_rv
        try:
            utils.get_sl_type('http://pdc.local/', 'securty_fixes')
            assert False, 'rpkgError not raised'
        except rpkgError as error:
            expected_error = ('The following error occurred while validating '
                              'the passed in service level in PDC: Some error')
            self.assertEqual(str(error), expected_error)

    @patch('fedpkg.utils.get_sl_type')
    def test_verify_sls(self, mock_get_sl_type):
        """Test verify_sls"""
        mock_get_sl_type.return_value = {
            'id': 1,
            'name': 'security_fixes',
            'description': 'security_fixes',
        }
        sls = {'security_fixes': '2222-12-01'}
        # If it's invalid, an rpkgError will be raised
        try:
            utils.verify_sls('http://pdc.local/', sls)
        except rpkgError:
            assert False, 'An rpkgError exception was raised but not expected'

    @patch('fedpkg.utils.get_sl_type')
    def test_verify_sls_eol_expired(self, mock_get_sl_type):
        """Test verify_sls raises an exception when an EOL is expired"""
        mock_get_sl_type.return_value = {
            'id': 1,
            'name': 'security_fixes',
            'description': 'security_fixes',
        }
        sls = {'security_fixes': '2001-12-01'}

        try:
            utils.verify_sls('http://pdc.local/', sls)
            assert False, 'An rpkgError exception was not raised'
        except rpkgError as e:
            self.assertEqual(str(e), 'The SL "2001-12-01" is already expired')

    def test_sl_list_dict(self):
        """Test sl_list_to_dict"""
        sls = ['security_fixes:2030-01-01', 'bug_fixes:2029-01-01']
        sls_dict = {'security_fixes': '2030-01-01', 'bug_fixes': '2029-01-01'}
        self.assertEqual(utils.sl_list_to_dict(sls), sls_dict)

    def test_sl_list_to_dict_invalid_format(self):
        """Tests sl_list_to_dict with an invalid SL format. An error is
        expected.
        """
        try:
            sls = ['security_fixes:2030-12-01', 'bug_fixes/2030-12-01']
            utils.sl_list_to_dict(sls)
            assert False, 'An rpkgError exception was not raised'
        except rpkgError as e:
            assert str(e) == \
                'The SL "bug_fixes/2030-12-01" is in an invalid format'

    def test_verify_sls_invalid_date(self):
        """Test verify_sls with an SL that is not June 1st or December 1st. An
        error is expected.
        """
        for eol in ['2030-01-01', '2030-12-25']:
            try:
                sls = {'security_fixes': eol, 'bug_fixes': eol}
                utils.verify_sls('http://pdc.example.com/', sls)
                assert False, 'An rpkgError exception was not raised'
            except rpkgError as e:
                assert str(e) == ('The SL "{0}" must expire on June 1st or '
                                  'December 1st'.format(eol))

    @patch('requests.get')
    def test_get_release_branches(self, mock_request_get):
        """Test that get_release_branches returns all the active Fedora release
        branches.
        """
        mock_rv = Mock()
        mock_rv.ok = True
        # This abbreviated data returned from the product-versions PDC API
        mock_rv.json.return_value = {
            'count': 7,
            'next': None,
            'previous': None,
            'results': [
                {'short': 'epel', 'version': '6'},
                {'short': 'epel', 'version': '7'},
                {'short': 'fedora', 'version': '25'},
                {'short': 'fedora', 'version': '26'},
                {'short': 'fedora', 'version': '27'},
                {'short': 'fedora', 'version': '28'},
                {'short': 'fedora', 'version': 'rawhide'}
            ]
        }
        mock_request_get.return_value = mock_rv
        expected = set(['el6', 'epel7', 'f25', 'f26', 'f27', 'f28'])
        expected = {
            'epel': ['el6', 'epel7'],
            'fedora': ['f25', 'f26', 'f27', 'f28'],
        }
        actual = utils.get_release_branches('http://pdc.local')
        self.assertEqual(expected, actual)


@patch('requests.get')
class TestAssertNewTestsRepo(unittest.TestCase):
    """Test assert_new_tests_repo"""

    def test_should_raise_error_if_connection_error_to_distgit(self, get):
        get.side_effect = ConnectionError

        six.assertRaisesRegex(
            self, rpkgError, 'The error was',
            utils.assert_new_tests_repo, 'testrepo', 'http://distgit/')

    def test_test_repo_exists(self, get):
        get.return_value = Mock(ok=True)

        six.assertRaisesRegex(
            self, rpkgError, 'Repository .+ already exists',
            utils.assert_new_tests_repo, 'testrepo', 'http://distgit/')

    def test_keep_quiet_if_repo_not_exist(self, get):
        get.return_value = Mock(ok=False)
        utils.assert_new_tests_repo('testrepo', 'http://distgit/')


class TestGetPagureToken(unittest.TestCase):
    """Test get_pagure_token"""

    def test_return_token(self):
        config = Mock()
        config.get.return_value = '123456'

        token = utils.get_pagure_token(config, 'fedpkg')

        self.assertEqual('123456', token)
        config.get.assert_called_once_with('fedpkg.pagure', 'token')

    def test_config_does_not_have_token(self):
        config = Mock()

        config.get.side_effect = NoOptionError('token', 'fedpkg.pagure')
        six.assertRaisesRegex(self, rpkgError, 'Missing a Pagure token',
                              utils.get_pagure_token, config, 'fedpkg')

        config.get.side_effect = NoSectionError('fedpkg.pagure')
        six.assertRaisesRegex(self, rpkgError, 'Missing a Pagure token',
                              utils.get_pagure_token, config, 'fedpkg')


@patch('requests.get')
class TestGetServiceLevelType(unittest.TestCase):
    """Test get_sl_type"""

    def test_raise_error_if_connection_error_to_pdc(self, get):
        get.side_effect = ConnectionError

        six.assertRaisesRegex(
            self, rpkgError, 'The connection to PDC failed',
            utils.get_sl_type, 'http://localhost/', 'bug_fixes:2020-12-01')

    def test_sl_type_not_exist(self, get):
        rv = Mock(ok=True)
        rv.json.return_value = {'count': 0}
        get.return_value = rv

        sl_type = utils.get_sl_type('http://localhost/',
                                    'bug_fixes:2020-12-01')
        self.assertIsNone(sl_type)

    def test_raise_error_if_response_not_ok(self, get):
        get.return_value = Mock(ok=False)

        six.assertRaisesRegex(
            self, rpkgError, 'The following error occurred',
            utils.get_sl_type, 'http://localhost/', 'bug_fixes:2020-12-01')


class TestVerifySLS(unittest.TestCase):
    """Test verify_sls"""

    def test_sl_date_format_is_invalid(self):
        six.assertRaisesRegex(
            self, rpkgError, 'The EOL date .+ is in an invalid format',
            utils.verify_sls, 'http://localhost/', {'bug_fixes': '2018/7/21'})

    @freeze_time('2018-01-01')
    @patch('requests.get')
    def test_sl_not_exist(self, get):
        rv = Mock(ok=True)
        rv.json.return_value = {'count': 0}

        six.assertRaisesRegex(
            self, rpkgError, 'The SL .+ is not in PDC',
            utils.verify_sls, 'http://localhost/', {'some_sl': '2018-06-01'})

    @freeze_time('2018-01-01')
    @patch('requests.get')
    def test_keep_quiet_if_service_levels_are_ok(self, get):
        rv = Mock(ok=True)
        rv.json.side_effect = [
            {
                'count': 1,
                'results': [{
                    'id': 1,
                    'name': 'bug_fixes',
                    'description': 'Bug fixes'
                }],
            },
            {
                'count': 1,
                'results': [{
                    'id': 2,
                    'name': 'security_fixes',
                    'description': 'Security fixes'
                }],
            }
        ]
        get.return_value = rv

        utils.verify_sls('http://localhost/',
                         {
                            'bug_fixes': '2018-06-01',
                            'security_fixes': '2018-12-01'
                         })


@patch('requests.get')
class TestAssertValidEPELPackage(unittest.TestCase):
    """Test assert_valid_epel_package"""

    def test_raise_error_if_connection_error(self, get):
        get.side_effect = ConnectionError

        six.assertRaisesRegex(
            self, rpkgError, 'The error was:',
            utils.assert_valid_epel_package, 'pkg', 'epel7')

    def test_raise_error_if_GET_response_not_ok(self, get):
        get.return_value = Mock(ok=False, status_code=404)

        six.assertRaisesRegex(
            self, rpkgError, 'The status code was: 404',
            utils.assert_valid_epel_package, 'pkg', 'epel7')

    def test_should_not_have_epel_branch_for_el6_pkg(self, get):
        get.return_value.json.return_value = {
            'arches': [
                'i686', 'noarch', 'i386', 'ppc64', 'ppc', 'x86_64'
            ],
            'packages': {
                'pkg1': {
                    # For el6, these arches will cause error raised.
                    'arch': ['i686', 'noarch', 'ppc64', 'x86_64']
                }
            }
        }

        six.assertRaisesRegex(
            self, rpkgError, 'is built on all supported arches',
            utils.assert_valid_epel_package, 'pkg1', 'el6')

    def test_should_not_have_epel_branch_for_el7_pkg(self, get):
        get.return_value.json.return_value = {
            'arches': [
                'i686', 'noarch', 'i386', 'ppc64', 'ppc', 'x86_64'
            ],
            'packages': {
                'pkg1': {
                    # For epel7, these arches will cause error raised.
                    'arch': ['i386', 'noarch', 'ppc64', 'x86_64']
                }
            }
        }

        six.assertRaisesRegex(
            self, rpkgError, 'is built on all supported arches',
            utils.assert_valid_epel_package, 'pkg1', 'epel7')

    def test_raise_error_if_package_has_noarch_only(self, get):
        get.return_value.json.return_value = {
            'arches': [
                'i686', 'noarch', 'i386', 'ppc64', 'ppc', 'x86_64'
            ],
            'packages': {
                'pkg1': {
                    'arch': ['noarch']
                }
            }
        }

        six.assertRaisesRegex(
            self, rpkgError, 'This package is already an EL package',
            utils.assert_valid_epel_package, 'pkg1', 'epel7')


@patch('requests.post')
class TestNewPagureIssue(unittest.TestCase):
    """Test new_pagure_issue"""

    def test_raise_error_if_connection_error(self, post):
        post.side_effect = ConnectionError

        six.assertRaisesRegex(
            self, rpkgError, 'The connection to Pagure failed',
            utils.new_pagure_issue,
            'http://distgit/', '123456', 'new package', {'repo': 'pkg1'}, 'fedpkg')

    def test_responses_not_ok_and_response_body_is_not_json(self, post):
        rv = Mock(ok=False, text='error')
        rv.json.side_effect = ValueError
        post.return_value = rv

        six.assertRaisesRegex(
            self, rpkgError,
            'The following error occurred while creating a new issue',
            utils.new_pagure_issue,
            'http://distgit/', '123456', 'new package', {'repo': 'pkg1'}, 'fedpkg')

    def test_responses_not_ok_when_token_is_expired(self, post):
        rv = Mock(
            ok=False,
            text='Invalid or expired token. Please visit '
                 'https://pagure.io/settings#api-keys to get or renew your API token.')
        rv.json.side_effect = ValueError
        post.return_value = rv

        six.assertRaisesRegex(
            self, rpkgError,
            'For invalid or expired token refer to "fedpkg request-repo -h" to set '
            'a token in your user configuration.',
            utils.new_pagure_issue,
            'http://distgit/', '123456', 'new package', {'repo': 'pkg1'}, 'fedpkg')

    def test_create_pagure_issue(self, post):
        rv = Mock(ok=True)
        rv.json.return_value = {'issue': {'id': 1}}
        post.return_value = rv

        pagure_api_url = 'http://distgit'
        issue_ticket_body = {'repo': 'pkg1'}

        issue_url = utils.new_pagure_issue(pagure_api_url,
                                           '123456',
                                           'new package',
                                           issue_ticket_body,
                                           'fedpkg',)

        expected_issue_url = (
            '{0}/releng/fedora-scm-requests/issue/1'
            .format(pagure_api_url)
        )
        self.assertEqual(expected_issue_url, issue_url)

        post.assert_called_once_with(
            '{0}/api/0/releng/fedora-scm-requests/new_issue'
            .format(pagure_api_url),
            headers={
                'Authorization': 'token {0}'.format(123456),
                'Accept': 'application/json',
                'Content-Type': 'application/json'
            },
            data=json.dumps({
                'title': 'new package',
                'issue_content': issue_ticket_body,
            }),
            timeout=60
        )


@patch('requests.get')
class TestQueryPDC(unittest.TestCase):
    """Test utils.query_pdc"""

    def test_connection_error(self, get):
        get.side_effect = ConnectionError

        result = utils.query_pdc('http://localhost/', 'endpoint', {})
        six.assertRaisesRegex(
            self, rpkgError, 'The connection to PDC failed',
            list, result)

    def test_response_not_ok(self, get):
        get.return_value.ok = False

        result = utils.query_pdc('http://localhost/', 'endpoint', {})
        six.assertRaisesRegex(
            self, rpkgError, 'The following error occurred',
            list, result)

    def test_read_yield_data_normally(self, get):
        rv = Mock()
        rv.ok = True
        rv.json.side_effect = [
            {'results': ['item1', 'item2'],
             'next': 'http://localhost/?page=2'},
            {'results': ['item3'], 'next': None}
        ]
        get.return_value = rv

        result = utils.query_pdc('http://localhost/', 'endpoint', {})
        self.assertEqual(['item1', 'item2', 'item3'], list(result))


class TestGetStreamBranches(unittest.TestCase):
    """Test get_stream_branches"""

    @patch('requests.get')
    def test_fedora_and_epel_branches_are_filtered_out(self, get):
        rv = Mock(ok=True)
        rv.json.return_value = {
            'results': [
                {'name': '8'},
                {'name': '10'},
                {'name': 'f28'},
                {'name': 'epel7'},
                {'name': 'master'},
            ],
            'next': None
        }
        get.return_value = rv

        result = utils.get_stream_branches('http://localhost/', 'pkg')
        self.assertEqual([{'name': '8'}, {'name': '10'}], list(result))


class TestExpandRelease(unittest.TestCase):
    """Test expand_release"""

    def setUp(self):
        self.releases = {
            'fedora': ['f28', 'f27'],
            'epel': ['el6', 'epel7']
        }

    def test_expand_fedora(self):
        result = utils.expand_release('fedora', self.releases)
        self.assertEqual(self.releases['fedora'], result)

    def test_expand_epel(self):
        result = utils.expand_release('epel', self.releases)
        self.assertEqual(self.releases['epel'], result)

    def test_expand_master(self):
        result = utils.expand_release('master', self.releases)
        self.assertEqual(['master'], result)

    def test_normal_release(self):
        result = utils.expand_release('f28', self.releases)
        self.assertEqual(['f28'], result)

        result = utils.expand_release('el6', self.releases)
        self.assertEqual(['el6'], result)

    def test_expand_unknown_name(self):
        result = utils.expand_release('some_branch', self.releases)
        self.assertEqual(None, result)
