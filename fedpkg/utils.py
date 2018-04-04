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

import re
import json
from datetime import datetime

from six.moves.urllib.parse import urlencode, urlparse
from six.moves.configparser import NoSectionError, NoOptionError
import requests
from requests.exceptions import ConnectionError
from pyrpkg import rpkgError


def get_sl_type(url, sl_name):
    """
    Gets the service level (SL) type from PDC
    :param url: a string of the URL to PDC
    :param sl_name: a string of the SL name
    :return: a dictionary representing the SL type or None
    """
    api_url = '{0}/rest_api/v1/component-sla-types/'.format(url.rstrip('/'))
    api_url_w_args = '{0}?{1}'.format(api_url, urlencode({'name': sl_name}))
    try:
        rv = requests.get(api_url_w_args, timeout=60)
    except ConnectionError as error:
        error_msg = ('The connection to PDC failed while trying to validate '
                     'the passed in service level. The error was: {0}'
                     .format(str(error)))
        raise rpkgError(error_msg)

    if not rv.ok:
        base_error_msg = ('The following error occurred while validating the '
                          'passed in service level in PDC: {0}')
        raise rpkgError(base_error_msg.format(rv.text))

    rv_json = rv.json()
    if rv_json['count'] == 1:
        return rv_json['results'][0]
    else:
        return None


def new_pagure_issue(url, token, title, body):
    """
    Posts a new Pagure issue
    :param url: a string of the URL to Pagure
    :param token: a string of the Pagure API token that has rights to create
    a ticket
    :param title: a string of the issue's title
    :param body: a string pf the issue's body
    :return: a string of the URL to the created issue in the UI
    """
    api_url = '{0}/api/0'.format(url.rstrip('/'))
    new_issue_url = '{0}/releng/fedora-scm-requests/new_issue'.format(api_url)

    headers = {
        'Authorization': 'token {0}'.format(token),
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    payload = json.dumps({
        'title': title,
        'issue_content': body
    })
    try:
        rv = requests.post(
            new_issue_url, headers=headers, data=payload, timeout=60)
    except ConnectionError as error:
        error_msg = ('The connection to Pagure failed while trying to '
                     'create a new issue. The error was: {0}'.format(
                         str(error)))
        raise rpkgError(error_msg)

    base_error_msg = ('The following error occurred while creating a new '
                      'issue in Pagure: {0}')
    if not rv.ok:
        # Lets see if the API returned an error message in JSON that we can
        # show the user
        try:
            rv_error = rv.json().get('error')
        except ValueError:
            rv_error = rv.text
        raise rpkgError(base_error_msg.format(rv_error))

    return '{0}/releng/fedora-scm-requests/issue/{1}'.format(
        url.rstrip('/'), rv.json()['issue']['id'])


def get_release_branches(url):
    """
    Get the active Fedora release branches from PDC
    :param url: a string of the URL to PDC
    :return: a set containing the active Fedora release branches
    """
    branches = set()
    api_url = '{0}/rest_api/v1/product-versions/'.format(url.rstrip('/'))
    query_args = {
        'fields': ['short', 'version'],
        'active': True
    }
    while True:
        try:
            rv = requests.get(api_url, params=query_args, timeout=60)
        except ConnectionError as error:
            error_msg = ('The connection to PDC failed while trying to get '
                         'the active release branches. The error was: {0}'
                         .format(str(error)))
            raise rpkgError(error_msg)

        if not rv.ok:
            base_error_msg = ('The following error occurred while trying to '
                              'get the active release branches in PDC: {0}')
            raise rpkgError(base_error_msg.format(rv.text))

        rv_json = rv.json()
        for product_version in rv_json['results']:
            # If the version is not a digit we can ignore it (e.g. rawhide)
            if not product_version['version'].isdigit():
                continue

            if product_version['short'] == 'epel':
                prefix = 'epel'
                if product_version['version'] == '6':
                    prefix = 'el'
                branches.add('{0}{1}'.format(
                    prefix, product_version['version']))
            elif product_version['short'] == 'fedora':
                branches.add('f{0}'.format(product_version['version']))

        if rv_json['next']:
            # Clear the query_args because they are baked into the "next" URL
            query_args = {}
            api_url = rv_json['next']
        else:
            # We've gone through every page, so we can return the found
            # branches
            return branches


def sl_list_to_dict(sls):
    """
    Takes a list of SLs and returns them in a dictionary format. Any errors in
    the SLs will be raised as an rpkgError.
    :param sls: list of SLs in the format of sl_name:2017-12-25
    :return: dictionary in the format of {'sl_name': '2017-12-25'}
    """
    sl_dict = {}
    # Ensures the SL is in the format "security_fixes:2020-01-01"
    sl_regex = re.compile(r'^(.+)(?:\:)(\d{4}-\d{2}-\d{2})$')
    for sl in sls:
        sl_match = re.match(sl_regex, sl)
        if sl_match:
            sl_name = sl_match.groups()[0]
            sl_date = sl_match.groups()[1]
            sl_dict[sl_name] = sl_date
        else:
            raise rpkgError(
                'The SL "{0}" is in an invalid format'.format(sl))

    return sl_dict


def verify_sls(pdc_url, sl_dict):
    """
    Verifies that the service levels are properly formatted and exist in PDC
    :param pdc_url: a string of the URL to PDC
    :param sl_dict: a dictionary with the SLs of the request
    :return: None or ValidationError
    """
    # Make sure the EOL date is in the format of 2020-12-01
    eol_date_regex = re.compile(r'\d{4}-\d{2}-\d{2}')
    for sl, eol in sl_dict.items():
        if re.match(eol_date_regex, eol):
            eol_date = datetime.strptime(eol, '%Y-%m-%d').date()
            today = datetime.utcnow().date()
            if eol_date < today:
                raise rpkgError(
                    'The SL "{0}" is already expired'.format(eol))
            elif eol_date.month not in [6, 12] or eol_date.day != 1:
                raise rpkgError(
                    'The SL "{0}" must expire on June 1st or December 1st'
                    .format(eol))
        else:
            raise rpkgError(
                'The EOL date "{0}" is in an invalid format'.format(eol))

        sl_obj = get_sl_type(pdc_url, sl)
        if not sl_obj:
            raise rpkgError('The SL "{0}" is not in PDC'.format(sl))


def get_pagure_token(config, cli_name):
    """
    Gets the Pagure token configured in the user's configuration file
    :param config: ConfigParser object
    :param cli_name: string of the CLI's name (e.g. fedpkg)
    :return: string of the Pagure token
    """
    conf_section = '{0}.pagure'.format(cli_name)
    try:
        return config.get(conf_section, 'token')
    except (NoSectionError, NoOptionError):
        raise rpkgError(
            'Missing a Pagure token. Refer to "{0} request-repo -h" to set a'
            'token in your user configuration.'.format(cli_name))


def is_epel(branch):
    """
    Determines if this is or will be an epel branch
    :param branch: a string of the branch name
    :return: a boolean
    """
    return bool(re.match(r'^(?:el|epel)\d+$', branch))


def assert_valid_epel_package(name, branch):
    """
    Determines if the package is allowed to have an EPEL branch. If it can't,
    an rpkgError will be raised.
    :param name: a string of the package name
    :param branch: a string of the EPEL branch name (e.g. epel7)
    :return: None or rpkgError
    """
    # Extract any digits in the branch name to determine the EL version
    version = ''.join([i for i in branch if re.match(r'\d', i)])
    url = ('https://infrastructure.fedoraproject.org/repo/json/pkg_el{0}.json'
           .format(version))
    error_msg = ('The connection to infrastructure.fedoraproject.org failed '
                 'while trying to determine if this is a valid EPEL package.')
    try:
        rv = requests.get(url, timeout=60)
    except ConnectionError as error:
        error_msg += ' The error was: {0}'.format(str(error))
        raise rpkgError(error_msg)

    if not rv.ok:
        raise rpkgError(error_msg + ' The status code was: {0}'.format(
            rv.status_code))

    rv_json = rv.json()
    # Remove noarch from this because noarch is treated specially
    all_arches = set(rv_json['arches']) - set(['noarch'])
    # On EL6, also remove ppc and i386 as many packages will
    # have these arches missing and cause false positives
    if int(version) == 6:
        all_arches = all_arches - set(['ppc', 'i386'])
    # On EL7 and later, also remove ppc and i686 as many packages will
    # have these arches missing and cause false positives
    elif int(version) >= 7:
        all_arches = all_arches - set(['ppc', 'i686'])

    error_msg_two = (
        'This package is already an EL package and is built on all supported '
        'arches, therefore, it cannot be in EPEL. If this is a mistake or you '
        'have an exception, please contact the Release Engineering team.')
    for pkg_name, pkg_info in rv_json['packages'].items():
        # If the EL package is noarch only or is available on all supported
        # arches, then don't allow an EPEL branch
        if pkg_name == name:
            pkg_arches = set(pkg_info['arch'])
            if pkg_arches == set(['noarch']) or not (all_arches - pkg_arches):
                raise rpkgError(error_msg_two)


def assert_new_tests_repo(name, dist_git_url):
    """
    Asserts that the tests repository name is new. Note that the repository name
    can be any arbitrary string, so just check if the repository already exists.

    :param name: a string with the package name
    :return: None or rpkgError
    """

    url = '{0}/tests/{1}'.format(dist_git_url, name)
    error_msg = (
        'The connection to dist-git failed'
        'trying to determine if this is a valid new tests '
        ' repository name.')
    try:
        rv = requests.get(url, timeout=60)
    except ConnectionError as error:
        error_msg += ' The error was: {0}'.format(str(error))
        raise rpkgError(error_msg)

    if rv.ok:
        raise rpkgError("Repository {0} already exists".format(url))


def get_dist_git_url(anongiturl):
    """
    Extracts dist-git url from the anongiturl configuration option.
    :param anongiturl: The `anongiturl` configuration option value. Typically
        takes the argument of `self.cmd.anongiturl`
    :return: dist-git url string or rpkgError
    """
    parsed_url = urlparse(anongiturl)
    return '{0}://{1}'.format(parsed_url.scheme, parsed_url.netloc)
