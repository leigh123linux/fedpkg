# -*- coding: utf-8 -*-
# cli.py - a cli client class module for fedpkg
#
# Copyright (C) 2011 Red Hat Inc.
# Author(s): Jesse Keating <jkeating@redhat.com>
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.  See http://www.gnu.org/copyleft/gpl.html for
# the full text of the license.

from pyrpkg.cli import cliClient
import hashlib
import os
import re
import six
import textwrap

from six.moves.configparser import NoSectionError
from six.moves.configparser import NoOptionError
from pyrpkg import rpkgError


class fedpkgClient(cliClient):
    def __init__(self, config, name=None):
        self.DEFAULT_CLI_NAME = 'fedpkg'
        super(fedpkgClient, self).__init__(config, name)
        self.setup_fed_subparsers()

    def setup_argparser(self):
        super(fedpkgClient, self).setup_argparser()

        opt_release = self.parser._option_string_actions['--release']
        opt_release.help = 'Override the discovered release, e.g. f25, which has to match ' \
                           'the remote branch name created in package repository. ' \
                           'Particularly, use master to build RPMs for rawhide.'

    def setup_fed_subparsers(self):
        """Register the fedora specific targets"""

        self.register_retire()
        self.register_update()

    # Target registry goes here
    def register_retire(self):
        """Register the retire target"""

        retire_parser = self.subparsers.add_parser(
            'retire',
            help='Retire a package',
            description='This command will remove all files from the repo, '
                        'leave a dead.package file, and push the changes.'
        )
        retire_parser.add_argument('reason',
                                   help='Reason for retiring the package')
        retire_parser.set_defaults(command=self.retire)

    def register_update(self):
        update_parser = self.subparsers.add_parser(
            'update',
            help='Submit last build as update',
            description='This will create a bodhi update request for the '
                        'current package n-v-r.'
        )
        update_parser.set_defaults(command=self.update)

    # Target functions go here
    def retire(self):
        # Skip if package is already retired...
        if os.path.isfile(os.path.join(self.cmd.path, 'dead.package')):
            self.log.warn('dead.package found, package probably already '
                          'retired - will not remove files from git or '
                          'overwrite existing dead.package file')
        else:
            self.cmd.retire(self.args.reason)
        self.push()

    def _format_update_clog(self, clog):
        ''' Format clog for the update template. '''
        lines = [l for l in clog.split('\n') if l]
        if len(lines) == 0:
            return "- Rebuilt.", ""
        elif len(lines) == 1:
            return lines[0], ""
        log = ["# Changelog:"]
        log.append('# - ' + lines[0])
        for l in lines[1:]:
            log.append('# ' + l)
        log.append('#')
        return lines[0], "\n".join(log)

    def update(self):
        try:
            section = '%s.bodhi' % self.name
            bodhi_config = {
                'url': self.config.get(section, 'url'),
                'staging': self.config.getboolean(section, 'staging'),
                }
        except (ValueError, NoOptionError, NoSectionError) as e:
            self.log.error(str(e))
            raise rpkgError('Could not get bodhi options. It seems configuration is changed. '
                            'Please try to reinstall %s or consult developers to see what '
                            'is wrong with it.' % self.name)

        template = """\
[ %(nvr)s ]

# bugfix, security, enhancement, newpackage (required)
type=

# testing, stable
request=testing

# Bug numbers: 1234,9876
bugs=%(bugs)s

%(changelog)s
# Here is where you give an explanation of your update.
# Content can span multiple lines, as long as they are indented deeper than
# the first line. For example,
# notes=first line
#     second line
#     and so on
notes=%(descr)s

# Enable request automation based on the stable/unstable karma thresholds
autokarma=True
stable_karma=3
unstable_karma=-3

# Automatically close bugs when this marked as stable
close_bugs=True

# Suggest that users restart after update
suggest_reboot=False
"""

        bodhi_args = {'nvr': self.cmd.nvr,
                      'bugs': '',
                      'descr': 'Here is where you give an explanation'
                               ' of your update.'}

        # Extract bug numbers from the latest changelog entry
        self.cmd.clog()
        with open('clog', 'r') as f:
            clog = f.read()
        bugs = re.findall(r'#([0-9]*)', clog)
        if bugs:
            bodhi_args['bugs'] = ','.join(bugs)

        # Use clog as default message
        bodhi_args['descr'], bodhi_args['changelog'] = \
            self._format_update_clog(clog)

        if six.PY2:
            # log may contain unicode characters, convert log to unicode string
            # to ensure text can be wrapped correctly in follow step.
            bodhi_args['descr'] = bodhi_args['descr'].decode('utf-8')
            bodhi_args['changelog'] = bodhi_args['changelog'].decode('utf-8')

        template = textwrap.dedent(template) % bodhi_args

        # Calculate the hash of the unaltered template
        orig_hash = hashlib.new('sha1')
        orig_hash.update(template.encode('utf-8'))
        orig_hash = orig_hash.hexdigest()

        # Write out the template
        with open('bodhi.template', 'w') as f:
            f.write(template.encode('utf-8'))

        # Open the template in a text editor
        editor = os.getenv('EDITOR', 'vi')
        self.cmd._run_command([editor, 'bodhi.template'], shell=True)

        # Check to see if we got a template written out.  Bail otherwise
        if not os.path.isfile('bodhi.template'):
            raise rpkgError('No bodhi update details saved!')

        # If the template was changed, submit it to bodhi
        new_hash = self.cmd.lookasidecache.hash_file('bodhi.template', 'sha1')
        if new_hash != orig_hash:
            try:
                self.cmd.update(bodhi_config, template='bodhi.template')
            except Exception as e:
                raise rpkgError('Could not generate update request: %s' % e)
        else:
            self.log.info('Bodhi update aborted!')

        # Clean up
        os.unlink('bodhi.template')
        os.unlink('clog')
