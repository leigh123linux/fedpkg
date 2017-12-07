# -*- coding: utf-8 -*-
# cli.py - a cli client class module for fedpkg
#
# Copyright (C) 2017 Red Hat Inc.
# Author(s): Matt Prahl <mprahl@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

# So that we import the bugzilla package and not fedpkg.bugzilla
from __future__ import absolute_import
from datetime import datetime

import bugzilla
from pyrpkg import rpkgError


class BugzillaClient(object):
    """A Bugzilla helper class"""
    api_url = None
    _client = None

    def __init__(self, url):
        self.api_url = '{0}/xmlrpc.cgi'.format(url.rstrip('/'))

    @property
    def client(self):
        """
        Only connect to Bugzilla when the client property is first used. This
        will make the unit tests less complicated and shorten the connections
        to the Bugzilla server.
        """
        if not self._client:
            # use_creds is only available in python-bugzilla 2.0+
            try:
                self._client = bugzilla.Bugzilla(self.api_url, use_creds=False)
            except TypeError:
                self._client = bugzilla.Bugzilla(self.api_url)

        return self._client

    def get_review_bug(self, bug_id, namespace, pkg):
        """
        Gets a Bugzilla bug representing a Fedora package review and does as
        much validation as it can without authenticating to Bugzilla. This
        function was inspired by:
        https://github.com/fedora-infra/pkgdb2/blob/master/pkgdb2/api/extras.py
        https://pagure.io/pkgdb-cli/blob/master/f/pkgdb2client/utils.py
        :param bug_id: string or integer of the Bugzilla bug ID
        :param namespace: string of the dist-git namespace
        :param pkg: string of the package name
        """
        try:
            bug = self.client.getbug(bug_id)
        except Exception as error:
            raise rpkgError(
                'The Bugzilla bug could not be verified. The following '
                'error was encountered: {0}'.format(str(error)))

        # Do some basic validation on the bug
        pagure_namespace_to_component = {
            'rpms': 'Package Review',
            'container': 'Container Review',
            'modules': 'Module Review',
            'test-modules': 'Module Review'
        }
        pagure_namespace_to_product = {
            'rpms': ['Fedora', 'Fedora EPEL'],
            'container': ['Fedora Container Images'],
            'modules': ['Fedora Modules'],
            'test-modules': ['Fedora']
        }
        bz_proper_component = pagure_namespace_to_component.get(namespace)
        bz_proper_products = pagure_namespace_to_product.get(namespace)
        if bz_proper_component is None or bug.component != bz_proper_component:
            raise rpkgError('The Bugzilla bug provided is not the proper type')
        elif bug.product not in bz_proper_products:
            raise rpkgError('The Bugzilla bug provided is not for "{0}"'
                            .format('" or "'.join(bz_proper_products)))
        elif bug.assigned_to in ['', None, 'nobody@fedoraproject.org']:
            raise rpkgError(
                'The Bugzilla bug provided is not assigned to anyone')
        # Check if the review was approved
        flag_set = False
        for flag in bug.flags:
            name, status = flag.get('name'), flag.get('status')
            if name == 'fedora-review' and status == '+':
                flag_set = True
                update_dt = flag.get('modification_date')
                if update_dt:
                    dt = datetime.strptime(
                        update_dt.value, '%Y%m%dT%H:%M:%S')
                    delta = datetime.utcnow().date() - dt.date()
                    if delta.days > 60:
                        raise rpkgError('The Bugzilla bug\'s review was '
                                        'approved over 60 days ago')
                break
        if not flag_set:
            raise rpkgError('The Bugzilla bug is not approved yet')
        # Check the format of the Bugzilla bug title
        tmp_summary = bug.summary.partition(':')[2]
        if not tmp_summary:
            raise rpkgError(
                'Invalid title for this Bugzilla bug (no ":" present)')
        if ' - ' not in tmp_summary:
            raise rpkgError(
                'Invalid title for this Bugzilla bug (no "-" present)')
        pkg_in_bug = tmp_summary.split(' - ', 1)[0].strip()
        if pkg != pkg_in_bug:
            error = ('The package in the Bugzilla bug "{0}" doesn\'t match '
                     'the one provided "{1}"'.format(pkg_in_bug, pkg))
            raise rpkgError(error)
        return bug
