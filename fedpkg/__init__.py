# fedpkg - a Python library for RPM Packagers
#
# Copyright (C) 2011 Red Hat Inc.
# Author(s): Jesse Keating <jkeating@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

import pyrpkg
import os
import git
import re

from datetime import datetime, timedelta

# doc/fedpkg_man_page.py uses the 'cli' import
from . import cli  # noqa
from .lookaside import FedoraLookasideCache
from pyrpkg.utils import cached_property

try:
    from bodhi.client.bindings import BodhiClient as _BodhiClient
except ImportError:
    _BodhiClient = None

try:
    from distro import linux_distribution  # noqa
except ImportError:
    from platform import linux_distribution  # noqa


if _BodhiClient is not None:
    from fedora.client import AuthError

    def clear_csrf_and_retry(func):
        """Clear csrf token and retry

        fedpkg uses Bodhi Python binding API list_overrides first before other
        save and extend APIs. That causes a readonly csrf token is received,
        which will be got again when next time to construct request data to
        modify updates. That is not expected and AuthError will be raised.

        So, the solution is to capture the AuthError error, clear the token and
        try to modify update again by requesting another token with user's
        credential.
        """
        def _decorator(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except AuthError:
                self._session.cookies.clear()
                self.csrf_token = None
                return func(self, *args, **kwargs)
        return _decorator

    class BodhiClient(_BodhiClient):
        """Customized BodhiClient for fedpkg"""

        UPDATE_TYPES = ['bugfix', 'security', 'enhancement', 'newpackage']
        REQUEST_TYPES = ['testing', 'stable']

        @clear_csrf_and_retry
        def save(self, *args, **kwargs):
            return super(BodhiClient, self).save(*args, **kwargs)

        @clear_csrf_and_retry
        def save_override(self, *args, **kwargs):
            return super(BodhiClient, self).save_override(*args, **kwargs)

        @clear_csrf_and_retry
        def extend_override(self, override, expiration_date):
            data = dict(
                nvr=override['nvr'],
                notes=override['notes'],
                expiration_date=expiration_date,
                edited=override['nvr'],
                csrf_token=self.csrf(),
            )
            return self.send_request(
                'overrides/', verb='POST', auth=True, data=data)


class Commands(pyrpkg.Commands):

    def __init__(self, *args, **kwargs):
        """Init the object and some configuration details."""

        super(Commands, self).__init__(*args, **kwargs)

        self.source_entry_type = 'bsd'
        # un-block retirement of packages (module retirement is allowed by default)
        if 'rpms' in self.block_retire_ns:
            self.block_retire_ns.remove('rpms')

    def load_user(self):
        """This sets the user attribute, based on the Fedora SSL cert."""
        fedora_upn = os.path.expanduser('~/.fedora.upn')
        if os.path.exists(fedora_upn):
            with open(fedora_upn, 'r') as f:
                self._user = f.read().strip()
        else:
            self.log.debug('Could not get user from .fedora.upn, falling back'
                           ' to default method')
            super(Commands, self).load_user()

    @cached_property
    def lookasidecache(self):
        """A helper to interact with the lookaside cache

        We override this because we need a different download path.
        """
        return FedoraLookasideCache(
            self.lookasidehash, self.lookaside, self.lookaside_cgi)

    # Overloaded property loaders
    def load_rpmdefines(self):
        """Populate rpmdefines based on branch data"""

        # Determine runtime environment
        self._runtime_disttag = self._determine_runtime_env()

        # We only match the top level branch name exactly.
        # Anything else is too dangerous and --dist should be used
        # This regex works until after Fedora 99.
        if re.match(r'f\d\d$', self.branch_merge):
            self._distval = self.branch_merge.split('f')[1]
            self._distvar = 'fedora'
            self._disttag = 'fc%s' % self._distval
            self.mockconfig = 'fedora-%s-%s' % (self._distval, self.localarch)
            self.override = 'f%s-override' % self._distval
            self._distunset = 'rhel'
        # Works until RHEL 10
        elif re.match(r'el\d$', self.branch_merge) or \
                re.match(r'epel\d$', self.branch_merge):
            self._distval = self.branch_merge.split('el')[1]
            self._distvar = 'rhel'
            self._disttag = 'el%s' % self._distval
            self.mockconfig = 'epel-%s-%s' % (self._distval, self.localarch)
            self.override = 'epel%s-override' % self._distval
            self._distunset = 'fedora'
        elif re.match(r'epel\d+-playground$', self.branch_merge):
            self._distval = re.search(r'\d+', self.branch_merge).group(0)
            self._distvar = 'rhel'
            self._disttag = 'el%s_playground' % self._distval
            self.mockconfig = 'epel-%s-%s' % (self._distval, self.localarch)
            self.override = 'epel%s-override' % self._distval
            self._distunset = 'fedora'
        elif re.match(r'olpc\d$', self.branch_merge):
            self._distval = self.branch_merge.split('olpc')[1]
            self._distvar = 'olpc'
            self._disttag = 'olpc%s' % self._distval
            self.override = 'dist-olpc%s-override' % self._distval
            self._distunset = 'rhel'
        # master
        elif re.match(r'master$', self.branch_merge):
            self._distval = self._findmasterbranch()
            self._distvar = 'fedora'
            self._disttag = 'fc%s' % self._distval
            self.mockconfig = 'fedora-rawhide-%s' % self.localarch
            self.override = None
            self._distunset = 'rhel'
        # If we don't match one of the above, punt
        else:
            raise pyrpkg.rpkgError('Could not find the release/dist from branch name '
                                   '%s\nPlease specify with --release' %
                                   self.branch_merge)
        self._rpmdefines = ["--define '_sourcedir %s'" % self.path,
                            "--define '_specdir %s'" % self.path,
                            "--define '_builddir %s'" % self.path,
                            "--define '_srcrpmdir %s'" % self.path,
                            "--define '_rpmdir %s'" % self.path,
                            "--define 'dist %%{?distprefix}.%s'" % self._disttag,
                            "--define '%s %s'" % (self._distvar,
                                                  self._distval),
                            "--eval '%%undefine %s'" % self._distunset,
                            "--define '%s 1'" % self._disttag]
        if self._runtime_disttag:
            if self._disttag != self._runtime_disttag:
                # This means that the runtime is known, and is different from
                # the target, so we need to unset the _runtime_disttag
                self._rpmdefines.append("--eval '%%undefine %s'" %
                                        self._runtime_disttag)

    def build_target(self, release):
        if release == 'master':
            return 'rawhide'
        else:
            return '%s-candidate' % release

    def load_container_build_target(self):
        if self.branch_merge == 'master':
            self._container_build_target = 'rawhide-%s-candidate' % self.ns
        else:
            super(Commands, self).load_container_build_target()

    def _tag2version(self, dest_tag):
        """ get the '26' part of 'f26-foo' string """
        return dest_tag.split('-')[0].replace('f', '')

    # New functionality
    def _findmasterbranch(self):
        """Find the right "fedora" for master"""

        # If we already have a koji session, just get data from the source
        if self._kojisession:
            rawhidetarget = self.kojisession.getBuildTarget('rawhide')
            return self._tag2version(rawhidetarget['dest_tag_name'])

        # Create a list of "fedoras"
        fedoras = []

        # Create a regex to find branches that exactly match f##.  Should not
        # catch branches such as f14-foobar
        branchre = r'f\d\d$'

        # Find the repo refs
        for ref in self.repo.refs:
            # Only find the remote refs
            if type(ref) == git.RemoteReference:
                # Search for branch name by splitting off the remote
                # part of the ref name and returning the rest.  This may
                # fail if somebody names a remote with / in the name...
                if re.match(branchre, ref.name.split('/', 1)[1]):
                    # Add just the simple f## part to the list
                    fedoras.append(ref.name.split('/')[1])
        if fedoras:
            # Sort the list
            fedoras.sort()
            # Start with the last item, strip the f, add 1, return it.
            return(int(fedoras[-1].strip('f')) + 1)
        else:
            # We may not have Fedoras.  Find out what rawhide target does.
            try:
                rawhidetarget = self.anon_kojisession.getBuildTarget(
                    'rawhide')
            except Exception:
                # We couldn't hit koji, bail.
                raise pyrpkg.rpkgError(
                    'Unable to query koji to find rawhide target')
            return self._tag2version(rawhidetarget['dest_tag_name'])

    def _determine_runtime_env(self):
        """Need to know what the runtime env is, so we can unset anything
           conflicting
        """
        try:
            runtime_os, runtime_version, _ = linux_distribution()
        except Exception:
            return None

        if runtime_os in ['redhat', 'centos']:
            return 'el%s' % runtime_version
        if runtime_os == 'Fedora':
            return 'fc%s' % runtime_version
        if (runtime_os == 'Red Hat Enterprise Linux Server' or
                runtime_os.startswith('CentOS')):
            return 'el{0}'.format(runtime_version.split('.')[0])

    def check_inheritance(self, build_target, dest_tag):
        """Disable check inheritance

        Tag inheritance check is not required in Fedora when make chain build
        in Koji.
        """

    def construct_build_url(self, *args, **kwargs):
        """Override build URL for Fedora Koji build

        In Fedora Koji, anonymous URL should have prefix "git+https://"
        """
        url = super(Commands, self).construct_build_url(*args, **kwargs)
        return 'git+{0}'.format(url)

    def update(self, bodhi_config, template='bodhi.template', bugs=[]):
        """Submit an update to bodhi using the provided template."""
        bodhi = BodhiClient(username=self.user,
                            staging=bodhi_config['staging'])

        update_details = bodhi.parse_file(template)

        for detail in update_details:
            if not detail['type']:
                raise ValueError(
                    'Missing update type, which is required to create update.')
            if detail['type'] not in BodhiClient.UPDATE_TYPES:
                raise ValueError(
                    'Incorrect update type {0}'.format(detail['type']))
            if detail['request'] not in BodhiClient.REQUEST_TYPES:
                raise ValueError(
                    'Incorrect request type {0}'.format(detail['request']))

            try:
                self.log.info(bodhi.update_str(bodhi.save(**detail), minimal=False))
            # Only because tests do not return a valid bodhi.save value
            except TypeError:
                pass

    def create_buildroot_override(self, bodhi_config, build, duration,
                                  notes=''):
        bodhi = BodhiClient(username=self.user,
                            staging=bodhi_config['staging'])
        result = bodhi.list_overrides(builds=build)
        if result['total'] == 0:
            try:
                self.log.debug(
                    'Create override in %s: nvr=%s, duration=%s, notes="%s"',
                    'staging Bodhi' if bodhi_config['staging'] else 'Bodhi',
                    build, duration, notes)
                override = bodhi.save_override(
                    nvr=build, duration=duration, notes=notes)
            except Exception as e:
                self.log.error(str(e))
                raise pyrpkg.rpkgError('Cannot create override.')
            else:
                self.log.info(bodhi.override_str(override, minimal=False))
        else:
            override = result['overrides'][0]
            expiration_date = datetime.strptime(override['expiration_date'],
                                                '%Y-%m-%d %H:%M:%S')
            if expiration_date < datetime.utcnow():
                self.log.info(
                    'Buildroot override for %s exists and is expired. Consider'
                    ' using command `override extend` to extend duration.',
                    build)
            else:
                self.log.info('Buildroot override for %s already exists and '
                              'not expired.', build)

    def extend_buildroot_override(self, bodhi_config, build, duration):
        bodhi = BodhiClient(username=self.user,
                            staging=bodhi_config['staging'])
        result = bodhi.list_overrides(builds=build)

        if result['total'] == 0:
            self.log.info('No buildroot override for build %s', build)
            return

        override = result['overrides'][0]
        expiration_date = datetime.strptime(override['expiration_date'],
                                            '%Y-%m-%d %H:%M:%S')
        utcnow = datetime.utcnow()

        # bodhi-client binding API save_override calculates expiration
        # date by adding duration to datetime.utcnow
        # This comparison should use utcnow as well.
        if expiration_date < utcnow:
            self.log.debug('Buildroot override is expired on %s',
                           override['expiration_date'])
            self.log.debug('Extend expiration date from today in UTC.')
            base_date = utcnow
        else:
            self.log.debug(
                'Extend expiration date from future expiration date.')
            base_date = expiration_date

        if isinstance(duration, datetime):
            if duration < utcnow:
                raise pyrpkg.rpkgError(
                    'At least, specified expiration date {0} should be '
                    'future date.'.format(duration.strftime('%Y-%m-%d')))
            if duration < base_date:
                self.log.warning(
                    'Expiration date %s to be set is before override current'
                    ' expiration date %s',
                    duration, base_date)
            # Keep time unchanged
            new_expiration_date = datetime(
                year=duration.year,
                month=duration.month,
                day=duration.day,
                hour=base_date.hour,
                minute=base_date.minute,
                second=base_date.second)
        else:
            new_expiration_date = base_date + timedelta(days=duration)

        try:
            self.log.debug('Extend override expiration date to %s',
                           new_expiration_date)
            override = bodhi.extend_override(override, new_expiration_date)
        except Exception as e:
            self.log.error('Cannot extend override expiration.')
            raise pyrpkg.rpkgError(str(e))
        else:
            self.log.info(bodhi.override_str(override, minimal=False))


if __name__ == "__main__":
    from fedpkg.__main__ import main
    main()
