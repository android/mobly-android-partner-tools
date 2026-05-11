#!/usr/bin/env python3
#  Copyright 2025 Google LLC
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

"""Sets up the local on-host credentials for result upload using gcloud.

This can be executed as a standalone login script (i.e. outside of a venv, with
no package dependencies).
"""

import logging
import os
import subprocess


def _run_gcloud_command(args: list[str]) -> None:
    """Runs a command with the gcloud CLI."""
    try:
        subprocess.check_call(['gcloud'] + args)
    except FileNotFoundError:
        logging.error(
            'Failed to run `gcloud` commands! Please install the `gcloud` CLI '
            'from https://docs.cloud.google.com/sdk/docs/install-sdk#latest-version '
            '(Skip the "Before you begin" steps.)')
        raise


def gcloud_login_and_set_project() -> None:
    """Get gcloud application default creds and set the desired GCP project."""
    logging.info('Performing initial credential setup.')
    project_id = ''
    while not project_id:
        project_id = input('Enter your GCP project ID: ')
    os.environ['GOOGLE_CLOUD_PROJECT'] = project_id
    os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
    _run_gcloud_command(
        ['config', 'set', 'project', project_id]
    )
    _run_gcloud_command(
        [
            'auth', 'application-default', 'login', '--no-launch-browser',
            '--scopes=https://www.googleapis.com/auth/cloud-platform',
        ]
    )
    _run_gcloud_command(
        ['auth', 'application-default', 'set-quota-project', project_id]
    )
    logging.info('Initial setup complete!')
    print('-' * 50)


def revoke_local_credentials() -> None:
    """Revokes existing local credentials."""
    _run_gcloud_command(['auth', 'application-default', 'revoke', '-q'])
    if os.getenv('GOOGLE_APPLICATION_CREDENTIALS'):
        del os.environ['GOOGLE_APPLICATION_CREDENTIALS']


# If executed as a script, perform the login flow.
if __name__ == '__main__':
    gcloud_login_and_set_project()
