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

from six.moves.urllib.parse import urlencode
from six.moves.configparser import NoSectionError, NoOptionError
import requests
from requests.exceptions import ConnectionError
from fedora.client.bodhi import Bodhi2Client
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


def get_release_branches(bodhi_url):
    """
    Get the active Fedora release branches from Bodhi
    :param bodhi_url: a string of the URL to Bodhi
    :return: a set containing the active Fedora release branches
    """
    bodhi = Bodhi2Client(bodhi_url)
    branches = set()
    page = 1
    while True:
        rv = bodhi.send_request('releases', auth=False, params={'page': page})
        for release in rv['releases']:
            if release['state'] == 'current':
                branches.add(release['branch'])
        if page < rv['pages']:
            page += 1
        else:
            break

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
        raise rpkgError('The "token" value must be set under the "{0}" '
                        'section in your "{1}" user configuration'
                        .format(conf_section, cli_name))
