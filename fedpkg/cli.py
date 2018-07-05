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
import argparse
import hashlib
import io
import os
import re
import json
import pkg_resources
import six
import textwrap

from datetime import datetime

from six.moves.configparser import NoSectionError
from six.moves.configparser import NoOptionError
from six.moves.urllib_parse import urlparse
from pyrpkg import rpkgError
from fedpkg.bugzilla import BugzillaClient
from fedpkg.utils import (
    get_release_branches, sl_list_to_dict, verify_sls, new_pagure_issue,
    get_pagure_token, is_epel, assert_valid_epel_package,
    assert_new_tests_repo, get_dist_git_url)

RELEASE_BRANCH_REGEX = r'^(f\d+|el\d+|epel\d+)$'


def check_bodhi_version():
    try:
        dist = pkg_resources.get_distribution('bodhi_client')
    except pkg_resources.DistributionNotFound:
        raise rpkgError('bodhi-client < 2.0 is not supported.')
    major = int(dist.version.split('.', 1)[0])
    if major >= 4:
        raise rpkgError(
            'This system has bodhi v{0}, which is unsupported.'.format(major))


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
        self.register_request_tests_repo()
        self.register_request_branch()
        self.register_override()

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
        description = '''Request a new dist-git repository

Before requesting a new dist-git repository for a new package, you need to
generate a pagure.io API token at https://{1}/settings/token/new, select both
"Create a new project" and "Create a new ticket" ACLs and save it in your local
user configuration located at ~/.config/rpkg/{0}.conf. For example:

    [{0}.pagure]
    token = <api_key_here>

Below is a basic example of the command to request a dist-git repository for
the package foo:

    fedpkg --name foo request-repo 1234

Request a module with namespace explicitly:

    fedpkg --name foo --namespace modules request-repo
'''.format(self.name, urlparse(self.config.get(
            '{0}.pagure'.format(self.name), 'url')).netloc)

        request_repo_parser = self.subparsers.add_parser(
            'request-repo',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=help_msg,
            description=description)
        request_repo_parser.add_argument(
            'bug', nargs='?', type=int,
            help='Bugzilla bug ID of the package review request. '
                 'Not required for requesting a module repository')
        request_repo_parser.add_argument(
            '--description', '-d', help='The repo\'s description in dist-git')
        monitoring_choices = [
            'no-monitoring', 'monitoring', 'monitoring-with-scratch']
        request_repo_parser.add_argument(
            '--monitor', '-m', help='The Anitya monitoring type for the repo',
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

    def register_request_tests_repo(self):
        help_msg = 'Request a new tests dist-git repository'
        pagure_url = urlparse(self.config.get(
            '{0}.pagure'.format(self.name), 'url')).netloc
        anongiturl = self.config.get(self.name, 'anongiturl', vars={'repo': 'any'})
        description = '''Request a new dist-git repository in tests shared namespace

    {2}/projects/tests/*

For more information about tests shared namespace see

    https://fedoraproject.org/wiki/CI/Share_Test_Code

Please refer to the request-repo command to see what has to be done before
requesting a repository in the tests namespace.

Below is a basic example of the command to request a dist-git repository for
the space tests/foo:

    fedpkg --name foo request-tests-repo "Description of the repository"

Note that the space name needs to reflect the intent of the tests and will
undergo a manual review.

'''.format(self.name, pagure_url, get_dist_git_url(anongiturl))

        request_tests_repo_parser = self.subparsers.add_parser(
            'request-tests-repo',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=help_msg,
            description=description)
        request_tests_repo_parser.add_argument(
            'description',
            help='Description of the tests repository')
        request_tests_repo_parser.set_defaults(command=self.request_tests_repo)

    def register_request_branch(self):
        help_msg = 'Request a new dist-git branch'
        description = '''Request a new dist-git branch

Please refer to the request-repo command to see what has to be done before
requesting a dist-git branch.

Below are various examples of requesting a dist-git branch.

Request a branch inside a cloned package repository:

    fedpkg request-branch f27

Request a branch outside package repository, which could apply to cases of
requested repository has not been approved and created, or just not change
directory to package repository:

    fedpkg request-branch --repo foo f27
'''
        request_branch_parser = self.subparsers.add_parser(
            'request-branch',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=help_msg,
            description=description)
        request_branch_parser.add_argument(
            'branch', nargs='?', help='The branch to request')
        request_branch_parser.add_argument(
            '--repo',
            required=False,
            dest='repo_name_for_branch',
            metavar='NAME',
            help='Repository name the new branch is requested for.'
        )
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
            '--no-auto-module', default=False, action='store_true',
            help='If requesting an rpm arbitrary branch, do not '
            'also request a new matching module.  See '
            'https://pagure.io/fedrepo_req/issue/129'
        )
        request_branch_parser.add_argument(
            '--all-releases', default=False, action='store_true',
            help='Make a new branch request for every active Fedora release'
        )
        request_branch_parser.set_defaults(command=self.request_branch)

    def register_override(self):
        """Register command line parser for subcommand override"""

        def validate_duration(value):
            try:
                duration = int(value)
            except ValueError:
                raise argparse.ArgumentTypeError('duration must be an integer.')
            if duration > 0:
                return duration
            raise argparse.ArgumentTypeError(
                'override should have 1 day to exist at least.')

        def validate_extend_duration(value):
            if value.isdigit():
                return validate_duration(value)
            match = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', value)
            if not match:
                raise argparse.ArgumentTypeError(
                    'Invalid expiration date. Valid format: yyyy-mm-dd.')
            y, m, d = match.groups()
            return datetime(year=int(y), month=int(m), day=int(d))

        override_parser = self.subparsers.add_parser(
            'override',
            help='Manage buildroot overrides')
        override_subparser = override_parser.add_subparsers(
            description='Commands on override')

        create_parser = override_subparser.add_parser(
            'create',
            help='Create buildroot override from build',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description='''\
Create a buildroot override from build guessed from current release branch or
specified explicitly.

Examples:

Create a buildroot override from build guessed from release branch. Note that,
command must run inside a package repository.

    {0} switch-branch f28
    {0} override create --duration 5

Create for a specified build:

    {0} override create --duration 5 package-1.0-1.fc28
'''.format(self.name))
        create_parser.add_argument(
            '--duration',
            type=validate_duration,
            default=7,
            help='Number of days the override should exist. If omitted, '
                 'default to 7 days.')
        create_parser.add_argument(
            '--notes',
            default='No explanation given...',
            help='Optional notes on why this override is in place.')
        create_parser.add_argument(
            'NVR',
            nargs='?',
            help='Create override from this build. If omitted, build will be'
                 ' guessed from current release branch.')
        create_parser.set_defaults(command=self.create_buildroot_override)

        extend_parser = override_subparser.add_parser(
            'extend',
            help='Extend buildroot override expiration',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description='''\
Extend buildroot override expiration.

An override expiration date could be extended by number of days or a specific
date. If override is expired, expiration date will be extended from the date
of today, otherwise from the expiration date.

Command extend accepts an optional build NVR to find out its override in
advance. If there is no such an override created previously, please use
`override create` to create one. If build NVR is omitted, command extend must
run inside a package repository and build will be guessed from current release
branch.

Examples:

1. To give 2 days to override for build somepkg-0.2-1.fc28

    {0} override extend 2 somepkg-0.2-1.fc28

2. To extend expiration date to 2018-7-1

    cd /path/to/somepkg
    {0} switch-branch f28
    {0} override extend 2018-7-1
'''.format(self.name))
        extend_parser.add_argument(
            'duration',
            type=validate_extend_duration,
            help='Number of days to extend the expiration date, or set the '
                 'expiration date directly. Valid date format: yyyy-mm-dd.')
        extend_parser.add_argument(
            'NVR',
            nargs='?',
            help='Buildroot override expiration for this build will be '
                 'extended. If omitted, build will be guessed from current '
                 'release branch.')
        extend_parser.set_defaults(command=self.extend_buildroot_override)

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

    def _get_bodhi_config(self):
        try:
            section = '%s.bodhi' % self.name
            return {
                'staging': self.config.getboolean(section, 'staging'),
            }
        except (ValueError, NoOptionError, NoSectionError) as e:
            self.log.error(str(e))
            raise rpkgError('Could not get bodhi options. It seems configuration is changed. '
                            'Please try to reinstall %s or consult developers to see what '
                            'is wrong with it.' % self.name)

    def update(self):
        check_bodhi_version()
        bodhi_config = self._get_bodhi_config()
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

        bodhi_args = {
            'nvr': self.cmd.nvr,
            'bugs': six.u(''),
            'descr': six.u(
                'Here is where you give an explanation of your update.')
        }

        # Extract bug numbers from the latest changelog entry
        self.cmd.clog()
        clog_file = os.path.join(self.cmd.path, 'clog')
        with io.open(clog_file, encoding='utf-8') as f:
            clog = f.read()
        bugs = re.findall(r'#([0-9]*)', clog)
        if bugs:
            bodhi_args['bugs'] = ','.join(bugs)

        # Use clog as default message
        bodhi_args['descr'], bodhi_args['changelog'] = \
            self._format_update_clog(clog)

        template = textwrap.dedent(template) % bodhi_args

        # Calculate the hash of the unaltered template
        orig_hash = hashlib.new('sha1')
        orig_hash.update(template.encode('utf-8'))
        orig_hash = orig_hash.hexdigest()

        # Write out the template
        with io.open('bodhi.template', 'w', encoding='utf-8') as f:
            f.write(template)

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
        self._request_repo(
            repo_name=self.cmd.repo_name,
            ns=self.cmd.ns,
            branch='master',
            summary=self.args.summary,
            description=self.args.description,
            upstreamurl=self.args.upstreamurl,
            monitor=self.args.monitor,
            bug=self.args.bug,
            exception=self.args.exception,
            name=self.name,
            config=self.config,
        )

    def request_tests_repo(self):
        self._request_repo(
            repo_name=self.cmd.repo_name,
            ns='tests',
            description=self.args.description,
            name=self.name,
            config=self.config,
            anongiturl=self.cmd.anongiturl
        )

    @staticmethod
    def _request_repo(repo_name, ns, description, name, config, branch=None,
                      summary=None, upstreamurl=None, monitor=None, bug=None,
                      exception=None, anongiturl=None):
        """ Implementation of `request_repo`.

        Submits a request for a new dist-git repo.

        :param repo_name: The repository name string.  Typically the
            value of `self.cmd.repo_name`.
        :param ns: The repository namespace string, i.e. 'rpms' or 'modules'.
            Typically takes the value of `self.cmd.ns`.
        :param description: A string, the description of the new repo.
            Typically takes the value of `self.args.description`.
        :param name: A string representing which section of the config should be
            used.  Typically the value of `self.name`.
        :param config: A dict containing the configuration, loaded from file.
            Typically the value of `self.config`.
        :param branch: The git branch string when requesting a repo.
            Typically 'master'.
        :param summary: A string, the summary of the new repo.  Typically
            takes the value of `self.args.summary`.
        :param upstreamurl: A string, the upstreamurl of the new repo.
            Typically takes the value of `self.args.upstreamurl`.
        :param monitor: A string, the monitoring flag of the new repo, i.e.
            `'no-monitoring'`, `'monitoring'`, or `'monitoring-with-scratch'`.
            Typically takes the value of `self.args.monitor`.
        :param bug: An integer representing the bugzilla ID of a "package
            review" associated with this new repo.  Typically takes the
            value of `self.args.bug`.
        :param exception: An boolean specifying whether or not this request is
            an exception to the packaging policy.  Exceptional requests may be
            granted the right to waive their package review at the discretion of
            Release Engineering.  Typically takes the value of
            `self.args.exception`.
        :param anongiturl: A string with the name of the anonymous git url.
            Typically the value of `self.cmd.anongiturl`.
        :return: None
        """

        # bug is not a required parameter in the event the packager has an
        # exception, in which case, they may use the --exception flag
        # neither in case of modules, which don't require a formal review
        if not bug and not exception and ns not in ['tests', 'modules']:
            raise rpkgError(
                'A Bugzilla bug is required on new repository requests')
        repo_regex = r'^[a-zA-Z0-9_][a-zA-Z0-9-_.+]*$'
        if not bool(re.match(repo_regex, repo_name)):
            raise rpkgError(
                'The repository name "{0}" is invalid. It must be at least '
                'two characters long with only letters, numbers, hyphens, '
                'underscores, plus signs, and/or periods. Please note that '
                'the project cannot start with a period or a plus sign.'
                .format(repo_name))

        summary_from_bug = ''
        if bug and ns not in ['tests', 'modules']:
            bz_url = config.get('{0}.bugzilla'.format(name), 'url')
            bz_client = BugzillaClient(bz_url)
            bug_obj = bz_client.get_review_bug(bug, ns, repo_name)
            summary_from_bug = bug_obj.summary.split(' - ', 1)[1].strip()

        if ns == 'tests':
            # check if tests repository does not exist already
            assert_new_tests_repo(repo_name, get_dist_git_url(anongiturl))

            ticket_body = {
                'action': 'new_repo',
                'namespace': 'tests',
                'repo': repo_name,
                'description': description,
            }
        else:
            ticket_body = {
                'action': 'new_repo',
                'branch': branch,
                'bug_id': bug or '',
                'description': description or '',
                'exception': exception,
                'monitor': monitor,
                'namespace': ns,
                'repo': repo_name,
                'summary': summary or summary_from_bug,
                'upstreamurl': upstreamurl or ''
            }

        ticket_body = json.dumps(ticket_body, indent=True)
        ticket_body = '```\n{0}\n```'.format(ticket_body)
        ticket_title = 'New Repo for "{0}/{1}"'.format(ns, repo_name)

        pagure_url = config.get('{0}.pagure'.format(name), 'url')
        pagure_token = get_pagure_token(config, name)
        print(new_pagure_issue(
            pagure_url, pagure_token, ticket_title, ticket_body))

    def request_branch(self):
        try:
            active_branch = self.cmd.repo.active_branch.name
        except rpkgError:
            active_branch = None
        self._request_branch(
            service_levels=self.args.sl,
            all_releases=self.args.all_releases,
            branch=self.args.branch,
            active_branch=active_branch,
            repo_name=self.args.repo_name_for_branch or self.cmd.repo_name,
            ns=self.cmd.ns,
            no_git_branch=self.args.no_git_branch,
            no_auto_module=self.args.no_auto_module,
            name=self.name,
            config=self.config,
        )

    @staticmethod
    def _request_branch(service_levels, all_releases, branch, active_branch,
                        repo_name, ns, no_git_branch, no_auto_module,
                        name, config):
        """ Implementation of `request_branch`.

        Submits a request for a new branch of a given dist-git repo.

        :param service_levels: A list of service level strings.  Typically the
            value of `self.args.service_levels`.
        :param all_releases: A boolean indicating if this request should be made
            for all active Fedora branches.
        :param branch: A string specifying the specific branch to be requested.
        :param active_branch: A string (or None) specifying the active branch in
            the current git repo (the branch that is currently checked out).
        :param repo_name: The repository name string.  Typically the
            value of `self.cmd.repo_name`.
        :param ns: The repository namespace string, i.e. 'rpms' or 'modules'.
            Typically takes the value of `self.cmd.ns`.
        :param no_git_branch: A boolean flag.  If True, the SCM admins should
            create the git branch in PDC, but not in pagure.io.
        :param no_auto_module: A boolean flag.  If True, requests for
            non-standard branches should not automatically result in additional
            requests for matching modules.
        :param name: A string representing which section of the config should be
            used.  Typically the value of `self.name`.
        :param config: A dict containing the configuration, loaded from file.
            Typically the value of `self.config`.
        :return: None
        """

        if all_releases:
            if branch:
                raise rpkgError('You cannot specify a branch with the '
                                '"--all-releases" option')
            elif service_levels:
                raise rpkgError('You cannot specify service levels with the '
                                '"--all-releases" option')
        elif not branch:
            if active_branch:
                branch = active_branch
            else:
                raise rpkgError('You must specify a branch if you are not in '
                                'a git repository')

        pdc_url = config.get('{0}.pdc'.format(name), 'url')
        if branch:
            if is_epel(branch):
                assert_valid_epel_package(repo_name, branch)

            if ns in ['modules', 'test-modules']:
                branch_valid = bool(re.match(r'^[a-zA-Z0-9.\-_+]+$', branch))
                if not branch_valid:
                    raise rpkgError(
                        'Only characters, numbers, periods, dashes, '
                        'underscores, and pluses are allowed in module branch '
                        'names')
            release_branches = get_release_branches(pdc_url)
            if branch in release_branches:
                if service_levels:
                    raise rpkgError(
                        'You can\'t provide SLs for release branches')
            else:
                if re.match(RELEASE_BRANCH_REGEX, branch):
                    raise rpkgError('{0} is a current release branch'
                                    .format(branch))
                elif not service_levels:
                    raise rpkgError(
                        'You must provide SLs for non-release branches (%s)' % branch)

        # If service levels were provided, verify them
        if service_levels:
            sl_dict = sl_list_to_dict(service_levels)
            verify_sls(pdc_url, sl_dict)

        pagure_url = config.get('{0}.pagure'.format(name), 'url')
        pagure_token = get_pagure_token(config, name)
        if all_releases:
            release_branches = get_release_branches(pdc_url)
            branches = [b for b in release_branches
                        if re.match(r'^(f\d+)$', b)]
        else:
            branches = [branch]

        for b in sorted(list(branches), reverse=True):
            ticket_body = {
                'action': 'new_branch',
                'branch': b,
                'namespace': ns,
                'repo': repo_name,
                'create_git_branch': not no_git_branch
            }
            if service_levels:
                ticket_body['sls'] = sl_dict

            ticket_body = json.dumps(ticket_body, indent=True)
            ticket_body = '```\n{0}\n```'.format(ticket_body)
            ticket_title = 'New Branch "{0}" for "{1}/{2}"'.format(
                b, ns, repo_name)

            print(new_pagure_issue(
                pagure_url, pagure_token, ticket_title, ticket_body))

            # For non-standard rpm branch requests, also request a matching new
            # module repo with a matching branch.
            auto_module = (
                ns == 'rpms'
                and not re.match(RELEASE_BRANCH_REGEX, b)
                and not no_auto_module
            )
            if auto_module:
                summary = ('Automatically requested module for '
                           'rpms/%s:%s.' % (repo_name, b))
                fedpkgClient._request_repo(
                    repo_name=repo_name,
                    ns='modules',
                    branch='master',
                    summary=summary,
                    description=summary,
                    upstreamurl=None,
                    monitor='no-monitoring',
                    bug=None,
                    exception=True,
                    name=name,
                    config=config,
                )
                fedpkgClient._request_branch(
                    service_levels=service_levels,
                    all_releases=all_releases,
                    branch=b,
                    active_branch=active_branch,
                    repo_name=repo_name,
                    ns='modules',
                    no_git_branch=no_git_branch,
                    no_auto_module=True,  # Avoid infinite recursion.
                    name=name,
                    config=config,
                )

    def create_buildroot_override(self):
        """Create a buildroot override in Bodhi"""
        check_bodhi_version()
        if self.args.NVR:
            if not self.cmd.anon_kojisession.getBuild(self.args.NVR):
                raise rpkgError(
                    'Build {0} does not exist.'.format(self.args.NVR))
        bodhi_config = self._get_bodhi_config()
        self.cmd.create_buildroot_override(
            bodhi_config,
            build=self.args.NVR or self.cmd.nvr,
            duration=self.args.duration,
            notes=self.args.notes)

    def extend_buildroot_override(self):
        check_bodhi_version()
        if self.args.NVR:
            if not self.cmd.anon_kojisession.getBuild(self.args.NVR):
                raise rpkgError(
                    'Build {0} does not exist.'.format(self.args.NVR))
        bodhi_config = self._get_bodhi_config()
        self.cmd.extend_buildroot_override(
            bodhi_config,
            build=self.args.NVR or self.cmd.nvr,
            duration=self.args.duration)
