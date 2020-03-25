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

import argparse
import io
import itertools
import json
import os
import re
import shutil
import textwrap
from datetime import datetime

import pkg_resources
import six
from six.moves import configparser
from six.moves.configparser import NoOptionError, NoSectionError
from six.moves.urllib_parse import urlparse

from fedpkg.bugzilla import BugzillaClient
from fedpkg.utils import (assert_new_tests_repo, assert_valid_epel_package,
                          do_fork, expand_release, get_dist_git_url,
                          get_distgit_token, get_fedora_release_state,
                          get_pagure_token, get_release_branches,
                          get_stream_branches, is_epel, new_pagure_issue,
                          sl_list_to_dict, verify_sls)
from pyrpkg import rpkgError
from pyrpkg.cli import cliClient

RELEASE_BRANCH_REGEX = r'^(f\d+|el\d+|epel\d+)$'
LOCAL_PACKAGE_CONFIG = 'package.cfg'

BODHI_TEMPLATE = """\
[ %(nvr)s ]

# bugfix, security, enhancement, newpackage (required)
type=%(type_)s

# testing, stable
request=%(request)s

# Bug numbers: 1234,9876
bugs=%(bugs)s

# Severity: low, medium, high, urgent
# This is required for security updates.
# severity=unspecified

%(changelog)s
# Here is where you give an explanation of your update.
# Content can span multiple lines, as long as they are indented deeper than
# the first line. For example,
# notes=first line
#     second line
#     and so on
notes=%(descr)s

# Enable request automation based on the stable/unstable karma thresholds
autokarma=%(autokarma)s
stable_karma=%(stable_karma)s
unstable_karma=%(unstable_karma)s

# Automatically close bugs when this marked as stable
close_bugs=%(close_bugs)s

# Suggest that users restart after update
suggest_reboot=%(suggest_reboot)s

# A boolean to require that all of the bugs in your update have been confirmed by testers.
require_bugs=%(require_bugs)s

# A boolean to require that this update passes all test cases before reaching stable.
require_testcases=%(require_testcases)s
"""


def check_bodhi_version():
    try:
        pkg_resources.get_distribution('bodhi_client')
    except pkg_resources.DistributionNotFound:
        raise rpkgError('bodhi-client < 2.0 is not supported.')


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

        self.register_releases_info()
        self.register_update()
        self.register_request_repo()
        self.register_request_tests_repo()
        self.register_request_branch()
        self.register_do_fork()
        self.register_override()

    # Target registry goes here
    def register_update(self):
        description = textwrap.dedent('''
            This will create a bodhi update request for the current package n-v-r.

            There are two ways to specify update details. Without any argument from command
            line, either update type or notes is omitted, a template editor will be shown
            and let you edit the detail information interactively.

            Alternatively, you could specify argument from command line to create an update
            directly, for example:

                {0} update --type bugfix --notes 'Rebuilt' --bugs 1000 1002

            When all lines in template editor are commented out or deleted, the creation
            process is aborted. If the template keeps unchanged, {0} continues on creating
            update. That gives user a chance to confirm the auto-generated notes from
            change log if option --notes is omitted.
        '''.format(self.name))

        update_parser = self.subparsers.add_parser(
            'update',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help='Submit last build as update',
            description=description,
        )

        def validate_stable_karma(value):
            error = argparse.ArgumentTypeError(
                'Stable karma must be an integer which is greater than zero.')
            try:
                karma = int(value)
            except ValueError:
                raise error
            if karma <= 0:
                raise error
            return karma

        def validate_unstable_karma(value):
            error = argparse.ArgumentTypeError(
                'Unstable karma must be an integer which is less than zero.')
            try:
                karma = int(value)
            except ValueError:
                raise error
            if karma >= 0:
                raise error
            return karma

        def validate_bugs(value):
            if not value.isdigit():
                raise argparse.ArgumentTypeError(
                    'Invalid bug {0}. It should be an integer.'.format(value))
            return value

        update_parser.add_argument(
            '--type',
            choices=['bugfix', 'security', 'enhancement', 'newpackage'],
            dest='update_type',
            help='Update type. Template editor will be shown if type is '
                 'omitted.')
        update_parser.add_argument(
            '--request',
            choices=['testing', 'stable'],
            default='testing',
            help='Requested repository.')
        update_parser.add_argument(
            '--bugs',
            nargs='+',
            type=validate_bugs,
            help='Bug numbers. If omitted, bug numbers will be extracted from'
                 ' change logs.')
        update_parser.add_argument(
            '--notes',
            help='Update description. Multiple lines of notes could be '
                 'specified. If omitted, template editor will be shown.')
        update_parser.add_argument(
            '--disable-autokarma',
            action='store_false',
            default=True,
            dest='autokarma',
            help='Karma automatism is enabled by default. Use this option to '
                 'disable that.')
        update_parser.add_argument(
            '--stable-karma',
            type=validate_stable_karma,
            metavar='KARMA',
            default=3,
            help='Stable karma. Default is 3.')
        update_parser.add_argument(
            '--unstable-karma',
            type=validate_unstable_karma,
            metavar='KARMA',
            default=-3,
            help='Unstable karma. Default is -3.')
        update_parser.add_argument(
            '--not-close-bugs',
            action='store_false',
            default=True,
            dest='close_bugs',
            help='By default, update will be created by enabling to close bugs'
                 ' automatically. If this is what you do not want, use this '
                 'option to disable the default behavior.')
        update_parser.add_argument(
            '--suggest-reboot',
            action='store_true',
            default=False,
            dest='suggest_reboot',
            help='Suggest user to reboot after update. Default is False.')
        update_parser.add_argument(
            '--no-require-bugs',
            action='store_false',
            default=True,
            dest='require_bugs',
            help='Disables the requirement that all of the bugs in your update '
                 'have been confirmed by testers. Default is True.')
        update_parser.add_argument(
            '--no-require-testcases',
            action='store_false',
            default=True,
            dest='require_testcases',
            help='Disables the requirement that this update passes all test cases '
                 'before reaching stable. Default is True.')
        update_parser.set_defaults(command=self.update)

    def get_distgit_namespaces(self):
        dg_namespaced = self._get_bool_opt('distgit_namespaced')
        if dg_namespaced and self.config.has_option(
                self.name, 'distgit_namespaces'):
            return self.config.get(self.name, 'distgit_namespaces').split()
        else:
            return None

    def register_request_repo(self):
        help_msg = 'Request a new dist-git repository'
        description = textwrap.dedent('''
            Request a new dist-git repository

            Before the operation, you need to generate a pagure.io API token at
            https://{1}/settings/token/new, select the relevant ACL(s)
            and save it in your local user configuration located
            at ~/.config/rpkg/{0}.conf. For example:

                [{0}.pagure]
                token = <api_key_here>

            Below is a basic example of the command to request a dist-git repository for
            the package foo:

                fedpkg request-repo foo 1234

            Another example to request a module foo:

                fedpkg request-repo --namespace modules foo
        '''.format(self.name, urlparse(self.config.get(
            '{0}.pagure'.format(self.name), 'url')).netloc))

        request_repo_parser = self.subparsers.add_parser(
            'request-repo',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=help_msg,
            description=description)
        request_repo_parser.add_argument(
            'name',
            help='Repository name to request.')
        request_repo_parser.add_argument(
            'bug', nargs='?', type=int,
            help='Bugzilla bug ID of the package review request. '
                 'Not required for requesting a module repository')
        request_repo_parser.add_argument(
            '--namespace',
            required=False,
            default='rpms',
            choices=self.get_distgit_namespaces(),
            dest='new_repo_namespace',
            help='Namespace of repository. If omitted, default to rpms.')
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
        request_repo_parser.add_argument(
            '--no-initial-commit',
            action='store_true',
            help='Do not include an initial commit in the repository.')
        request_repo_parser.set_defaults(command=self.request_repo)

    def register_request_tests_repo(self):
        help_msg = 'Request a new tests dist-git repository'
        pagure_url = urlparse(self.config.get(
            '{0}.pagure'.format(self.name), 'url')).netloc
        anongiturl = self.config.get(
            self.name, 'anongiturl', vars={'repo': 'any', 'module': 'any'}
        )
        description = textwrap.dedent('''
            Request a new dist-git repository in tests shared namespace

                {2}/projects/tests/*

            For more information about tests shared namespace see

                https://fedoraproject.org/wiki/CI/Share_Test_Code

            Please refer to the request-repo command to see what has to be done before
            requesting a repository in the tests namespace.

            Below is a basic example of the command to request a dist-git repository for
            the space tests/foo:

                {0} request-tests-repo foo "Description of the repository"

            Note that the space name needs to reflect the intent of the tests and will
            undergo a manual review.
        '''.format(self.name, pagure_url, get_dist_git_url(anongiturl)))

        request_tests_repo_parser = self.subparsers.add_parser(
            'request-tests-repo',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=help_msg,
            description=description)
        request_tests_repo_parser.add_argument(
            'name',
            help='Repository name to request.')
        request_tests_repo_parser.add_argument(
            'description',
            help='Description of the tests repository')
        request_tests_repo_parser.add_argument(
            '--bug', type=int,
            help='Bugzilla bug ID of the package review request.')
        request_tests_repo_parser.set_defaults(command=self.request_tests_repo)

    def register_request_branch(self):
        help_msg = 'Request a new dist-git branch'
        description = textwrap.dedent('''
            Request a new dist-git branch

            Please refer to the help of the request-repo command to see what has
            to be done before requesting a dist-git branch.

            Branch name could be one of current active Fedora and EPEL releases. Use
            command ``{0} releases-info`` to get release names that can be used to request
            a branch.

            Below are various examples of requesting a dist-git branch.

            Request a branch inside a cloned package repository:

                {0} request-branch f27

            Request a branch outside package repository, which could apply to cases of
            requested repository has not been approved and created, or just not change
            directory to package repository:

                {0} request-branch --repo foo f27

            Request a branch with service level tied to the branch. In this case branch
            argument has to be before --sl argument, because --sl allows multiple values.

                {0} request-branch branch_name --sl bug_fixes:2020-06-01 rawhide:2019-12-01
        '''.format(self.name))

        request_branch_parser = self.subparsers.add_parser(
            'request-branch',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=help_msg,
            description=description)
        request_branch_parser.add_argument(
            'branch', nargs='?', help='The branch to request.')
        request_branch_parser.add_argument(
            '--repo',
            required=False,
            dest='repo_name_for_branch',
            metavar='NAME',
            help='Repository name the new branch is requested for.'
        )
        request_branch_parser.add_argument(
            '--namespace',
            required=False,
            dest='repo_ns_for_branch',
            choices=self.get_distgit_namespaces(),
            help='Repository name the new branch is requested for.'
        )
        request_branch_parser.add_argument(
            '--sl', nargs='*',
            help=('The service levels (SLs) tied to the branch. This must be '
                  'in the format of "sl_name:2020-12-01". This is only for '
                  'non-release branches. You may provide more than one by '
                  'separating each SL with a space. When the argument is used, '
                  'branch argument has to be placed before --sl.')
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

    def register_do_fork(self):
        help_msg = 'Create a new fork of the current repository'
        description = textwrap.dedent('''
            Create a new fork of the current repository

            Before the operation, you need to generate an API token at
            https://{1}/settings/token/new, select the relevant ACL(s)
            and save it in your local user configuration located
            at ~/.config/rpkg/{0}.conf. For example:

                [{0}.distgit]
                token = <api_key_here>

            Below is a basic example of the command to fork a current repository:

                {0} fork

            Operation requires username (FAS_ID). by default, current logged
            username is taken. It could be overridden by reusing an argument:

                {0} --user FAS_ID fork
        '''.format(self.name, urlparse(self.config.get(
            '{0}.distgit'.format(self.name), 'apibaseurl')).netloc))

        fork_parser = self.subparsers.add_parser(
            'fork',
            formatter_class=argparse.RawDescriptionHelpFormatter,
            help=help_msg,
            description=description)
        fork_parser.add_argument(
            '--namespace',
            required=False,
            default='rpms',
            choices=self.get_distgit_namespaces(),
            dest='fork_namespace',
            help='Namespace of the fork. If omitted, default to rpms.')
        fork_parser.set_defaults(command=self.do_distgit_fork)

    def register_releases_info(self):
        help_msg = 'Print Fedora or EPEL current active releases'
        parser = self.subparsers.add_parser(
            'releases-info',
            help=help_msg,
            description=help_msg)

        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            '-e', '--epel',
            action='store_true',
            dest='show_epel_only',
            help='Only show EPEL releases.')
        group.add_argument(
            '-f', '--fedora',
            action='store_true',
            dest='show_fedora_only',
            help='Only show Fedora active releases.')
        group.add_argument(
            '-j', '--join',
            action='store_true',
            help='Show all releases in one line separated by a space.')

        parser.set_defaults(command=self.show_releases_info)

    def register_override(self):
        """Register command line parser for subcommand override

        .. versionadded:: 1.34
        """

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
            description=textwrap.dedent('''
                Create a buildroot override from build guessed from current release branch or
                specified explicitly.

                Examples:

                Create a buildroot override from build guessed from release branch. Note that,
                command must run inside a package repository.

                    {0} switch-branch f28
                    {0} override create --duration 5

                Create for a specified build:

                    {0} override create --duration 5 package-1.0-1.fc28
            '''.format(self.name)))
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
            description=textwrap.dedent('''
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
            '''.format(self.name)))
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

    def register_build(self):
        super(fedpkgClient, self).register_build()

        build_parser = self.subparsers.choices['build']
        build_parser.formatter_class = argparse.RawDescriptionHelpFormatter
        build_parser.description = textwrap.dedent('''
            {0}

            fedpkg is also able to submit multiple builds to Koji at once from stream
            branch based on a local config, which is inside the repository. The config file
            is named package.cfg in INI format. For example,

                [koji]
                targets = master fedora epel7

            You only need to put Fedora releases and EPEL in option targets and fedpkg will
            convert it to proper Koji build target for submitting builds. Beside regular
            release names, option targets accepts two shortcut names as well, fedora and
            epel, as you can see in the above example. Name fedora stands for current
            active Fedora releases, and epel stands for the active EPEL releases, which are
            el6 and epel7 currently.

            Note that the config file is a branch specific file. That means you could
            create package.cfg for each stream branch separately to indicate on which
            targets to build the package for a particular stream.
        '''.format('\n'.join(textwrap.wrap(build_parser.description))))

    # Target functions go here
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

    @staticmethod
    def is_update_aborted(template_file):
        """Check if the update is aborted

        As long as the template file cannot be loaded by configparse, abort
        immediately.

        From user's perspective, it is similar with aborting commit when option
        -m is omitted. If all lines are commented out, abort.
        """
        config = configparser.ConfigParser()
        try:
            loaded_files = config.read(template_file)
        except configparser.MissingSectionHeaderError:
            return True
        # Something wrong with the template, which causes it cannot be loaded.
        if not loaded_files:
            return True
        # template can be loaded even if it's empty.
        if not config.sections():
            return True
        return False

    def _prepare_bodhi_template(self, template_file):
        try:
            nvr = self.cmd.nvr
        except rpkgError:
            # This is not an RPM, can't get NVR
            nvr = "FILL_IN_NVR_HERE"
        bodhi_args = {
            'nvr': nvr,
            'bugs': six.u(''),
            'descr': six.u(
                'Here is where you give an explanation of your update.'),
            'request': self.args.request,
            'autokarma': str(self.args.autokarma),
            'stable_karma': self.args.stable_karma,
            'unstable_karma': self.args.unstable_karma,
            'close_bugs': str(self.args.close_bugs),
            'suggest_reboot': str(self.args.suggest_reboot),
            'require_bugs': str(self.args.require_bugs),
            'require_testcases': str(self.args.require_testcases),
        }

        if self.args.update_type:
            bodhi_args['type_'] = self.args.update_type
        else:
            bodhi_args['type_'] = ''

        try:
            self.cmd.clog()
            clog_file = os.path.join(self.cmd.path, 'clog')
            with io.open(clog_file, encoding='utf-8') as f:
                clog = f.read()
            os.unlink(clog_file)
        except rpkgError:
            # Not an RPM, no changelog to work with
            clog = ""

        if self.args.bugs:
            bodhi_args['bugs'] = ','.join(self.args.bugs)
        else:
            # Extract bug numbers from the latest changelog entry
            bugs = re.findall(r'#([0-9]+)', clog)
            if bugs:
                bodhi_args['bugs'] = ','.join(bugs)

        if self.args.notes:
            bodhi_args['descr'] = self.args.notes.replace('\n', '\n    ')
            bodhi_args['changelog'] = ''
        else:
            # Use clog as default message
            bodhi_args['descr'], bodhi_args['changelog'] = \
                self._format_update_clog(clog)

        template = textwrap.dedent(BODHI_TEMPLATE) % bodhi_args

        with io.open(template_file, 'w', encoding='utf-8') as f:
            f.write(template)

        if not self.args.update_type or not self.args.notes:
            # Open the template in a text editor
            editor = os.getenv('EDITOR', 'vi')
            self.cmd._run_command([editor, template_file], shell=True)

            # Check to see if we got a template written out.  Bail otherwise
            if not os.path.isfile(template_file):
                raise rpkgError('No bodhi update details saved!')

            return not self.is_update_aborted(template_file)

        return True

    def update(self):
        check_bodhi_version()
        bodhi_config = self._get_bodhi_config()

        bodhi_template_file = 'bodhi.template'
        ready = self._prepare_bodhi_template(bodhi_template_file)

        if ready:
            try:
                self.cmd.update(bodhi_config, template=bodhi_template_file)
            except Exception as e:
                # Reserve original edited bodhi template so that packager could
                # have a chance to recover content on error for next try.
                shutil.copyfile(bodhi_template_file,
                                '{0}.last'.format(bodhi_template_file))
                raise rpkgError('Could not generate update request: %s\n'
                                'A copy of the filled in template is saved '
                                'as bodhi.template.last' % e)
            finally:
                os.unlink(bodhi_template_file)
        else:
            self.log.info('Bodhi update aborted!')

    def request_repo(self):
        self._request_repo(
            repo_name=self.args.name,
            ns=self.args.new_repo_namespace,
            branch='master',
            summary=self.args.summary,
            description=self.args.description,
            upstreamurl=self.args.upstreamurl,
            monitor=self.args.monitor,
            bug=self.args.bug,
            exception=self.args.exception,
            name=self.name,
            config=self.config,
            initial_commit=not self.args.no_initial_commit,
        )

    def request_tests_repo(self):
        self._request_repo(
            repo_name=self.args.name,
            ns='tests',
            description=self.args.description,
            bug=self.args.bug,
            name=self.name,
            config=self.config,
            anongiturl=self.cmd.anongiturl
        )

    @staticmethod
    def _request_repo(repo_name, ns, description, name, config, branch=None,
                      summary=None, upstreamurl=None, monitor=None, bug=None,
                      exception=None, anongiturl=None, initial_commit=True):
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
        if not bug and not exception and ns not in ['tests', 'modules', 'flatpaks']:
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
        if bug and ns not in ['modules', 'flatpaks']:
            bz_url = config.get('{0}.bugzilla'.format(name), 'url')
            bz_client = BugzillaClient(bz_url)
            bug_obj = bz_client.get_review_bug(bug, ns, repo_name)
            summary_from_bug = bug_obj.summary.split(' - ', 1)[1].strip()

        if ns == 'tests':
            # check if tests repository does not exist already
            assert_new_tests_repo(repo_name, get_dist_git_url(anongiturl))

            ticket_body = {
                'action': 'new_repo',
                'branch': 'master',
                'bug_id': bug or '',
                'monitor': 'no-monitoring',
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
            if not initial_commit:
                ticket_body['initial_commit'] = False

        ticket_body = json.dumps(ticket_body, indent=True)
        ticket_body = '```\n{0}\n```'.format(ticket_body)
        ticket_title = 'New Repo for "{0}/{1}"'.format(ns, repo_name)

        pagure_url = config.get('{0}.pagure'.format(name), 'url')
        pagure_token = get_pagure_token(config, name)
        print(new_pagure_issue(
            pagure_url, pagure_token, ticket_title, ticket_body, name))

    def request_branch(self):
        if self.args.repo_name_for_branch:
            self.cmd.repo_name = self.args.repo_name_for_branch
            self.cmd.ns = self.args.repo_ns_for_branch or 'rpms'

        try:
            active_branch = self.cmd.repo.active_branch.name
        except rpkgError:
            active_branch = None
        self._request_branch(
            service_levels=self.args.sl,
            all_releases=self.args.all_releases,
            branch=self.args.branch,
            active_branch=active_branch,
            repo_name=self.cmd.repo_name,
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
        # When a 'epel\d' branch is requested, it should automatically request
        # 'epel\d+-playground' branch.
        epel_playground = False
        epel_version = None
        if branch:
            # Check if the requested branch is an epel branch
            match = re.match(r'^epel(?P<epel_version>\d+)$', branch)
            if match:
                epel_playground = True
                epel_version = int(match.groupdict()["epel_version"])

            if is_epel(branch):
                assert_valid_epel_package(repo_name, branch)

            # Requesting epel\d-playground branches is not allowed
            if bool(re.match(r'^epel\d+-playground$', branch)):
                raise rpkgError(
                    'You cannot directly request {0} branch, as they are '
                    'created as part of epel branch requests'.format(branch))

            if ns in ['modules', 'test-modules', 'flatpaks']:
                branch_valid = bool(re.match(r'^[a-zA-Z0-9.\-_+]+$', branch))
                if not branch_valid:
                    raise rpkgError(
                        'Only characters, numbers, periods, dashes, '
                        'underscores, and pluses are allowed in {0} branch '
                        'names'.format('flatpak' if ns == 'flatpaks' else 'module'))
            release_branches = list(itertools.chain(
                *list(get_release_branches(pdc_url).values())))
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
            release_branches = list(itertools.chain(
                *list(get_release_branches(pdc_url).values())))
            branches = [b for b in release_branches
                        if re.match(r'^(f\d+)$', b)]
        # If the requested branch is epel branch then also add epel\d+-playground branch
        # to the request list.
        # TODO: Remove the check for epel version >= 7 when we enable playground for epel7
        elif epel_playground and epel_version >= 8:
            branches = [branch, branch+"-playground"]
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
                pagure_url, pagure_token, ticket_title, ticket_body, name))

            # For non-standard rpm branch requests, also request a matching new
            # module repo with a matching branch.
            auto_module = (
                ns == 'rpms'
                and not re.match(RELEASE_BRANCH_REGEX, b)
                and not epel_playground  # Dont run auto_module on epel requests
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

    def do_distgit_fork(self):
        """create fork of the distgit repository"""
        distgit_api_base_url = self.config.get('{0}.distgit'.format(self.name), "apibaseurl")
        distgit_remote_base_url = self.config.get(
            '{0}'.format(self.name),
            "gitbaseurl",
            vars={'user': 'any', 'repo': 'any'},
        )
        distgit_token = get_distgit_token(self.config, self.name)

        fork_url = do_fork(
            base_url=distgit_api_base_url,
            remote_base_url=distgit_remote_base_url,
            token=distgit_token,
            username=self.cmd.user,
            repo=self.cmd.repo,
            namespace=self.args.fork_namespace,
            cli_name=self.name,
        )
        if fork_url:
            msg = "Fork of the repository has been created: {0}"
            self.log.info(msg.format(fork_url))

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

    def read_releases_from_local_config(self, active_releases):
        """Read configured releases from build config from repo"""
        config_file = os.path.join(self.cmd.path, LOCAL_PACKAGE_CONFIG)
        if not os.path.exists(config_file):
            self.log.warning('No local config file exists.')
            self.log.warning(
                'Create %s to specify build targets to build.',
                LOCAL_PACKAGE_CONFIG)
            return None
        config = configparser.ConfigParser()
        if not config.read([config_file]):
            raise rpkgError('Package config {0} is not accessible.'.format(
                LOCAL_PACKAGE_CONFIG))
        if not config.has_option('koji', 'targets'):
            self.log.warning(
                'Build target is not configured. Continue to build as normal.')
            return None
        target_releases = config.get('koji', 'targets', raw=True).split()
        expanded_releases = []
        for rel in target_releases:
            expanded = expand_release(rel, active_releases)
            if expanded:
                expanded_releases += expanded
            else:
                self.log.error('Target %s is unknown. Skip.', rel)
        return sorted(set(expanded_releases))

    @staticmethod
    def is_stream_branch(stream_branches, name):
        """Determine if a branch is stream branch

        :param stream_branches: list of stream branches of a package. Each of
            them is a mapping containing name and active status, which are
            minimum set of properties to be included. For example, ``[{'name':
            '8', 'active': true}, {'name': '10', 'active': true}]``.
        :type stream_branches: list[dict]
        :param str name: branch name to check if it is a stream branch.
        :return: True if branch is a stream branch, False otherwise.
        :raises rpkgError: if branch is a stream branch but it is inactive.
        """
        for branch_info in stream_branches:
            if branch_info['name'] != name:
                continue
            if branch_info['active']:
                return True
            else:
                raise rpkgError('Cannot build from stream branch {0} as it is '
                                'inactive.'.format(name))
        return False

    def _build(self, sets=None):
        if hasattr(self.args, 'chain') or self.args.scratch:
            return super(fedpkgClient, self)._build(sets)

        server_url = self.config.get('{0}.pdc'.format(self.name), 'url')

        stream_branches = get_stream_branches(server_url, self.cmd.repo_name)
        self.log.debug(
            'Package %s has stream branches: %r',
            self.cmd.repo_name, [item['name'] for item in stream_branches])

        if not self.is_stream_branch(stream_branches, self.cmd.branch_merge):
            return super(fedpkgClient, self)._build(sets)

        self.log.debug('Current branch %s is a stream branch.',
                       self.cmd.branch_merge)

        releases = self.read_releases_from_local_config(
            get_release_branches(server_url))

        if not releases:
            # If local config file is not created yet, or no build targets
            # are not configured, let's build as normal.
            return super(fedpkgClient, self)._build(sets)

        self.log.debug('Build on release targets: %r', releases)
        task_ids = []
        for release in releases:
            self.cmd.branch_merge = release
            self.cmd.target = self.cmd.build_target(release)
            # self.rel has to be regenerated by self.load_nameverrel, because it differs
            # for every release. It is used in nvr-already-built check (self.nvr) later.
            self.cmd.load_nameverrel()
            task_id = super(fedpkgClient, self)._build(sets)
            task_ids.append(task_id)
        return task_ids

    def show_releases_info(self):
        server_url = self.config.get('{0}.pdc'.format(self.name), 'url')
        releases = get_release_branches(server_url)

        def _join(l):
            return ' '.join(l)

        if self.args.show_epel_only:
            print(_join(releases['epel']))
        elif self.args.show_fedora_only:
            print(_join(releases['fedora']))
        elif self.args.join:
            print(' '.join(itertools.chain(releases['fedora'],
                                           releases['epel'])))
        else:
            print('Fedora: {0}'.format(_join(releases['fedora'])))
            print('EPEL: {0}'.format(_join(releases['epel'])))

    def retire(self):
        """
        Runs the rpkg retire command after check. Check includes reading the state
        of Fedora release.
        """
        state = get_fedora_release_state(self.config, self.name, self.cmd.branch_merge)

        if state is None or state == 'pending':
            super(fedpkgClient, self).retire()
        else:
            self.log.error("Fedora release (%s) is in state '%s' - retire operation "
                           "is not allowed." % (self.cmd.branch_merge, state))
