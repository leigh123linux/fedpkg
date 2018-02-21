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

from mock import patch, Mock
from pyrpkg.errors import rpkgError

from utils import CliTestCase
from fedpkg import utils


class TestUtils(CliTestCase):
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
                sls = {'security_fixes': eol, 'bug_fixes': '2030-12-01'}
                utils.verify_sls('abc', sls)
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
        actual = utils.get_release_branches('http://pdc.local')
        self.assertEqual(expected, actual)
