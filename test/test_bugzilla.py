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

from fedpkg.bugzilla import BugzillaClient
from pyrpkg import rpkgError
from utils import unittest
from mock import patch, Mock


class BugzillaSideEffect(object):
    def __init__(self):
        self._counter = 1
        self.mock = Mock()

    def __call__(self, *args, **kwargs):
        if self._counter == 1:
            self._counter += 1
            raise TypeError
        else:
            return self.mock(*args, **kwargs)


class TestPropertyClient(unittest.TestCase):
    """Test property BugzillaClient.client"""

    @patch('bugzilla.Bugzilla')
    def test_get_client(self, Bugzilla):
        bzc = BugzillaClient('http://bugzilla.example.com')
        self.assertEqual(Bugzilla.return_value, bzc.client)
        Bugzilla.assert_called_once_with(bzc.api_url, use_creds=False)

    @patch('bugzilla.Bugzilla')
    def test_work_with_older_python_bugzilla(self, Bugzilla):
        Bugzilla.side_effect = BugzillaSideEffect()
        bzc = BugzillaClient('http://bugzilla.example.com')
        self.assertEqual(Bugzilla.side_effect.mock.return_value, bzc.client)
        Bugzilla.side_effect.mock.assert_called_once_with(bzc.api_url)


class TestGetReviewBug(unittest.TestCase):
    """Test Bugzilla.get_review_bug"""

    @patch('bugzilla.Bugzilla')
    def test_raise_error_if_bz_raise_error(self, Bugzilla):
        Bugzilla.return_value.getbug.side_effect = ValueError

        bzc = BugzillaClient('http://bugzilla.example.com')
        six.assertRaisesRegex(
            self, rpkgError, 'The Bugzilla bug could not be verified.',
            bzc.get_review_bug, 123, 'rpms', 'mypkg')

    @patch('bugzilla.Bugzilla')
    def test_raise_error_if_distgit_namespace_is_unknown(self, Bugzilla):
        Bugzilla.return_value.getbug.return_value = Mock()

        bzc = BugzillaClient('http://bugzilla.example.com')
        six.assertRaisesRegex(
            self, rpkgError, 'not the proper type',
            bzc.get_review_bug, 123, 'xxx', 'mypkg')

    @patch('bugzilla.Bugzilla')
    def test_raise_error_if_bug_component_is_incorrect(self, Bugzilla):
        Bugzilla.return_value.getbug.return_value = Mock(component='xxx')

        bzc = BugzillaClient('http://bugzilla.example.com')
        # namespace container requires bug component is Container Review,
        # but fake bug has a different component.
        six.assertRaisesRegex(
            self, rpkgError, 'not the proper type',
            bzc.get_review_bug, 123, 'container', 'mypkg')
