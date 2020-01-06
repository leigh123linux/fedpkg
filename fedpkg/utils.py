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

import json
import re
from datetime import datetime

import requests
from requests.exceptions import ConnectionError
from six.moves.configparser import NoOptionError, NoSectionError
from six.moves.urllib.parse import urlencode, urlparse

from pyrpkg import rpkgError


def query_pdc(server_url, endpoint, params, timeout=60):
    api_url = '{0}/rest_api/v1/{1}/'.format(
        server_url.rstrip('/'), endpoint.strip('/'))
    query_args = params
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
        for item in rv_json['results']:
            yield item

        if rv_json['next']:
            # Clear the query_args because they are baked into the "next" URL
            query_args = {}
            api_url = rv_json['next']
        else:
            # We've gone through every page, so we can return the found
            # branches
            break


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


def new_pagure_issue(url, token, title, body, cli_name):
    """
    Posts a new Pagure issue
    :param url: a string of the URL to Pagure
    :param token: a string of the Pagure API token that has rights to create
    a ticket
    :param title: a string of the issue's title
    :param body: a string of the issue's body
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
        # show hint for expired token
        if re.search(r"Invalid or expired token", rv_error, re.IGNORECASE):
            base_error_msg += '\nFor invalid or expired token refer to ' \
                '"{0} request-repo -h" to set a token in your user ' \
                'configuration.'.format(cli_name)
        raise rpkgError(base_error_msg.format(rv_error))

    return '{0}/releng/fedora-scm-requests/issue/{1}'.format(
        url.rstrip('/'), rv.json()['issue']['id'])


def get_release_branches(server_url):
    """
    Get the active Fedora release branches from PDC

    :param  str url: a string of the URL to PDC
    :return: a mapping containing the active Fedora releases and EPEL branches.
    :rtype: dict
    """
    query_args = {
        'fields': ['short', 'version'],
        'active': True
    }
    releases = {}

    for product_version in query_pdc(
            server_url, 'product-versions', params=query_args):
        short_name = product_version['short']
        version = product_version['version']

        # If the version is not a digit we can ignore it (e.g. rawhide)
        if not version.isdigit():
            continue

        if short_name == 'epel':
            prefix = 'el' if version == '6' else 'epel'
        elif short_name == 'fedora':
            prefix = 'f'

        release = '{0}{1}'.format(prefix, version)
        releases.setdefault(short_name, []).append(release)

    return releases


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
            'Missing a Pagure token. Refer to "{0} request-repo -h" to set a '
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
        'The connection to dist-git failed '
        'trying to determine if this is a valid new tests '
        'repository name.')
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


def get_stream_branches(server_url, package_name):
    """Get a package's stream branches

    :param str server_url: PDC server URL.
    :param str package_name: package name. Generally for RPM packages, this is
        the repository name without namespace.
    :return: a list of stream branches. Each element in the list is a dict
        containing branch property name and active.
    :rtype: list[dict]
    """
    query_args = {
        'global_component': package_name,
        'fields': ['name', 'active'],
    }
    branches = query_pdc(
        server_url, 'component-branches', params=query_args)
    # When write this method, endpoint component-branches contains not only
    # stream branches, but also regular release branches, e.g. master, f28.
    # Please remember to review the data regularly, there are only stream
    # branches, or some new replacement of PDC fixes the issue as well, it
    # should be ok to remove if from this list.
    stream_branches = []
    for item in branches:
        if item['name'] == 'master':
            continue
        elif re.match(r'^(f|el)\d+$', item['name']):
            continue
        # epel7 is regular release branch
        # epel8 and above should be considered a stream branch to use
        # package.cfg file in the branch.
        elif 'epel7' == item['name']:
            continue
        # epel8-playground and above playground branches should be considered
        # as release branches so that it will use epelX-playground-candidate
        # target to build.
        elif re.match(r'^epel\d+-playground$', item['name']):
            continue
        else:
            stream_branches.append(item)
    return stream_branches


def expand_release(rel, active_releases):
    r"""Expand special release to real release name

    Special releases include fedora and epel. Each of them will be expanded to
    real release name.

    :param str rel: a release name to be expanded. It could be special names
        fedora and epel, or concrete release names, e.g. f28, el6.
    :param dict active_releases: a mapping from release category to concrete
        release names. Fow now, it has two mappings, from name fedora to f\d\+,
        and from epel to el6 and epel7. Value of this parameter should be
        returned from `get_release_branches`.
    :return: list of releases, for example ``[f28]``, or ``[el6, epel7]``.
    """
    if rel == 'master':
        return ['master']
    elif rel == 'fedora':
        return active_releases['fedora']
    elif rel == 'epel':
        return active_releases['epel']
    elif rel in active_releases['fedora'] or rel in active_releases['epel']:
        return [rel]
    # if epelX-playground branch then return the release to use
    # epelX-playground-candidate target
    elif re.match(r'^epel\d+-playground$', rel):
        return [rel]
    else:
        return None


def get_fedora_release_state(config, cli_name, release):
    """
    Queries service page for release state. Query result is returned as json dict.

    :param config: ConfigParser object
    :param cli_name: string of the CLI's name (e.g. fedpkg)
    :param str release: short release name. Example: F29, F30, F29M, F30C, ...
    :return: state of the release or None if there is no such release
    :rtype: str
    """
    try:
        # url of the release service. It needs to be expanded by release name
        releases_service_url = config.get('{0}.bodhi'.format(cli_name),
                                          'releases_service',
                                          vars={'release': release})
    except (ValueError, NoOptionError, NoSectionError) as e:
        raise rpkgError('Could not get release state for Fedora '
                        '({0}): {1}.'.format(release, str(e)))

    try:
        rv = requests.get(releases_service_url, timeout=60)
    except ConnectionError as error:
        error_msg = ('The connection to Bodhi failed while trying to get '
                     'release state. The error was: {0}'.format(str(error)))
        raise rpkgError(error_msg)

    if rv.status_code == 404:
        # release wasn't found
        return None
    elif not rv.ok:
        base_error_msg = ('The following error occurred while trying to '
                          'get the release state in Bodhi: {0}')
        raise rpkgError(base_error_msg.format(rv.text))

    return rv.json().get('state')
