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

from utils import CommandTestCase
from mock import patch


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
