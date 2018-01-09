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

from __future__ import print_function
from pyrpkg.cli import cliClient
import hashlib
import os
import re
import json
import six
import textwrap

from six.moves.configparser import NoSectionError
from six.moves.configparser import NoOptionError
from pyrpkg import rpkgError
from fedpkg.bugzilla import BugzillaClient
from fedpkg.utils import (
    get_release_branches, sl_list_to_dict, verify_sls, new_pagure_issue,
    get_pagure_token, is_epel, assert_valid_epel_package)


class fedpkgClient(cliClient):
    def __init__(self, config, name=None):
        self.DEFAULT_CLI_NAME = 'fedpkg'
        super(fedpkgClient, self).__init__(config, name)
        self.setup_fed_subparsers()

    def setup_argparser(self):
        super(fedpkgClient, self).setup_argparser()

        # This line is added here so that it shows up with the "--help" option,
        # but it isn't used for anything else
        self.parser.add_argument(
            '--user-config', help='Specify a user config file to use')
        opt_release = self.parser._option_string_actions['--release']
        opt_release.help = 'Override the discovered release, e.g. f25, which has to match ' \
                           'the remote branch name created in package repository. ' \
                           'Particularly, use master to build RPMs for rawhide.'

    def setup_fed_subparsers(self):
        """Register the fedora specific targets"""

        self.register_retire()
        self.register_update()
        self.register_request_repo()
        self.register_request_branch()

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

    def register_request_repo(self):
        help_msg = 'Request a new dist-git repository'
        request_repo_parser = self.subparsers.add_parser(
            'request-repo', help=help_msg, description=help_msg)
        request_repo_parser.add_argument(
            'bug', nargs='?', type=int,
            help='Bugzilla bug ID of the package review request')
        request_repo_parser.add_argument(
            '--description', '-d', help='The repo\'s description in dist-git')
        monitoring_choices = [
            'no-monitoring', 'monitoring', 'monitoring-with-scratch']
        request_repo_parser.add_argument(
            '--monitor', '-m', help='The Koshei monitoring type for the repo',
            choices=monitoring_choices, default=monitoring_choices[1])
        request_repo_parser.add_argument(
            '--upstreamurl', '-u',
            help='The upstream URL of the project')
        request_repo_parser.add_argument(
            '--summary', '-s',
            help='Override the package\'s summary from the Bugzilla bug')
        request_repo_parser.add_argument(
            '--exception', action='store_true',
            help='The package is an exception to the regular package review '
                 'process (specifically, it does not require a Bugzilla bug)')
        request_repo_parser.set_defaults(command=self.request_repo)

    def register_request_branch(self):
        help_msg = 'Request a new dist-git branch'
        request_branch_parser = self.subparsers.add_parser(
            'request-branch', help=help_msg, description=help_msg)
        request_branch_parser.add_argument(
            'branch', nargs='?', help='The branch to request')
        request_branch_parser.add_argument(
            '--sl', nargs='*',
            help=('The service levels (SLs) tied to the branch. This must be '
                  'in the format of "sl_name:2020-12-01". This is only for '
                  'non-release branches. You may provide more than one by '
                  'separating each SL with a space.')
        )
        request_branch_parser.add_argument(
            '--no-git-branch', default=False, action='store_true',
            help='Don\'t create the branch in git but still create it in PDC'
        )
        request_branch_parser.add_argument(
            '--all-releases', default=False, action='store_true',
            help='Make a new branch request for every active Fedora release'
        )
        request_branch_parser.set_defaults(command=self.request_branch)

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

    def request_repo(self):
        # bug is not a required parameter in the event the packager has an
        # exception, in which case, they may use the --exception flag
        if not self.args.bug and not self.args.exception:
            raise rpkgError(
                'A Bugzilla bug is required on new repository requests')
        repo_regex = r'^[a-zA-Z0-9_][a-zA-Z0-9-_.+]*$'
        if not bool(re.match(repo_regex, self.cmd.module_name)):
            raise rpkgError(
                'The repository name "{0}" is invalid. It must be at least '
                'two characters long with only letters, numbers, hyphens, '
                'underscores, plus signs, and/or periods. Please note that '
                'the project cannot start with a period or a plus sign.'
                .format(self.cmd.module_name))

        summary_from_bug = ''
        if self.args.bug:
            bz_url = self.config.get('{0}.bugzilla'.format(self.name), 'url')
            bz_client = BugzillaClient(bz_url)
            bug = bz_client.get_review_bug(
                self.args.bug, self.cmd.ns, self.cmd.module_name)
            summary_from_bug = bug.summary.split(' - ', 1)[1].strip()

        ticket_body = {
            'action': 'new_repo',
            'branch': 'master',
            'bug_id': self.args.bug or '',
            'description': self.args.description or '',
            'exception': self.args.exception,
            'monitor': self.args.monitor,
            'namespace': self.cmd.ns,
            'repo': self.cmd.module_name,
            'summary': self.args.summary or summary_from_bug,
            'upstreamurl': self.args.upstreamurl or ''
        }

        ticket_body = json.dumps(ticket_body, indent=True)
        ticket_body = '```\n{0}\n```'.format(ticket_body)
        ticket_title = 'New Repo for "{0}/{1}"'.format(
            self.cmd.ns, self.cmd.module_name)

        pagure_url = self.config.get('{0}.pagure'.format(self.name), 'url')
        pagure_token = get_pagure_token(self.config, self.name)
        print(new_pagure_issue(
            pagure_url, pagure_token, ticket_title, ticket_body))

    def request_branch(self):
        service_levels = self.args.sl
        branch = None

        if self.args.all_releases:
            if self.args.branch:
                raise rpkgError('You cannot specify a branch with the '
                                '"--all-releases" option')
            elif service_levels:
                raise rpkgError('You cannot specify service levels with the '
                                '"--all-releases" option')
        elif not self.args.branch:
            try:
                branch = self.cmd.repo.active_branch.name
            except rpkgError:
                raise rpkgError('You must specify a branch if you are not in '
                                'a git repository')
        else:
            branch = self.args.branch

        bodhi_url = self.config.get('{0}.bodhi'.format(self.name), 'url')
        if branch:
            if is_epel(branch):
                assert_valid_epel_package(self.cmd.module_name, branch)

            if self.cmd.ns in ['modules', 'test-modules']:
                branch_valid = bool(re.match(r'^[a-zA-Z0-9.\-_+]+$', branch))
                if not branch_valid:
                    raise rpkgError(
                        'Only characters, numbers, periods, dashes, '
                        'underscores, and pluses are allowed in module branch '
                        'names')
            release_branches = get_release_branches(bodhi_url)
            if branch in release_branches:
                if service_levels:
                    raise rpkgError(
                        'You can\'t provide SLs for release branches')
            else:
                if re.match(r'^(f\d+|el\d+|epel\d+)$', branch):
                    raise rpkgError('{0} is not a current release branch'
                                    .format(branch))
                elif not service_levels:
                    raise rpkgError(
                        'You must provide SLs for non-release branches')

        # If service levels were provided, verify them
        if service_levels:
            pdc_url = self.config.get('{0}.pdc'.format(self.name), 'url')
            sl_dict = sl_list_to_dict(service_levels)
            verify_sls(pdc_url, sl_dict)

        pagure_url = self.config.get('{0}.pagure'.format(self.name), 'url')
        pagure_token = get_pagure_token(self.config, self.name)
        if self.args.all_releases:
            release_branches = get_release_branches(bodhi_url)
            branches = [b for b in release_branches
                        if re.match(r'^(f\d+)$', b)]
        else:
            branches = [branch]

        for b in sorted(list(branches), reverse=True):
            ticket_body = {
                'action': 'new_branch',
                'branch': b,
                'namespace': self.cmd.ns,
                'repo': self.cmd.module_name,
                'create_git_branch': not self.args.no_git_branch
            }
            if service_levels:
                ticket_body['sls'] = sl_dict

            ticket_body = json.dumps(ticket_body, indent=True)
            ticket_body = '```\n{0}\n```'.format(ticket_body)
            ticket_title = 'New Branch "{0}" for "{1}/{2}"'.format(
                b, self.cmd.ns, self.cmd.module_name)

            print(new_pagure_issue(
                pagure_url, pagure_token, ticket_title, ticket_body))
