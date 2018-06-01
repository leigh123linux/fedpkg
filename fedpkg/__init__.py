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
import platform
import pkg_resources

from . import cli  # noqa
from .lookaside import FedoraLookasideCache
from pyrpkg.utils import cached_property


class Commands(pyrpkg.Commands):

    def __init__(self, *args, **kwargs):
        """Init the object and some configuration details."""

        super(Commands, self).__init__(*args, **kwargs)

        self.source_entry_type = 'bsd'

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
                            "--define 'dist .%s'" % self._disttag,
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

    def load_target(self):
        """This creates the target attribute based on branch merge"""

        if self.branch_merge == 'master':
            self._target = 'rawhide'
        else:
            self._target = '%s-candidate' % self.branch_merge

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
                raise pyrpkg.rpkgError('Unable to query koji to find rawhide \
                                       target')
            return self._tag2version(rawhidetarget['dest_tag_name'])

    def _determine_runtime_env(self):
        """Need to know what the runtime env is, so we can unset anything
           conflicting
        """
        try:
            runtime_os, runtime_version, _ = platform.linux_distribution()
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

    def retire(self, message):
        """Delete all tracked files and commit a new dead.package file

        Use optional message in commit.

        Runs the commands and returns nothing
        """
        cmd = ['git']
        if self.quiet:
            cmd.append('--quiet')
        cmd.extend(['rm', '-rf', '.'])
        self._run_command(cmd, cwd=self.path)

        fd = open(os.path.join(self.path, 'dead.package'), 'w')
        fd.write(message + '\n')
        fd.close()

        cmd = ['git', 'add', os.path.join(self.path, 'dead.package')]
        self._run_command(cmd, cwd=self.path)

        self.commit(message=message)

    def update(self, bodhi_config, template='bodhi.template', bugs=[]):
        """Submit an update to bodhi using the provided template."""
        check_bodhi_version()
        cmd = ['bodhi', 'updates', 'new', '--file', 'bodhi.template',
               '--user', self.user]
        if bodhi_config['staging']:
            cmd.append('--staging')
        cmd.append(self.nvr)
        self._run_command(cmd, shell=True)


def check_bodhi_version():
    try:
        dist = pkg_resources.get_distribution('bodhi_client')
    except pkg_resources.DistributionNotFound:
        raise pyrpkg.rpkgError('bodhi-client < 2.0 is not supported.')
    major = int(dist.version.split('.', 1))
    if major >= 4:
        raise pyrpkg.rpkgError(
            'This system has bodhi v{0}, which is unsupported.'.format(major))


if __name__ == "__main__":
    from fedpkg.__main__ import main
    main()
