#!/usr/bin/env python3

#  Copyright 2024 Google LLC
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

"""CLI uploader for Mobly test results to Resultstore."""

import argparse
import collections
import dataclasses
import datetime
from importlib import resources
import logging
import mimetypes
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tempfile
import warnings
from xml.etree import ElementTree

import google.auth
from google.cloud import api_keys_v2
from google.cloud import resourcemanager_v3
from google.cloud import storage
from googleapiclient import discovery

from results_uploader import mobly_result_converter
from results_uploader import resultstore_client

with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    from google.cloud.storage import transfer_manager


_RESULTSTORE_SERVICE_NAME = 'resultstore'
_API_VERSION = 'v2'
_API_KEY_DISPLAY_NAME = 'resultstore'
_DISCOVERY_SERVICE_URL = (
    'https://{api}.googleapis.com/$discovery/rest?version={apiVersion}'
)

_TEST_XML = 'test.xml'
_TEST_LOG = 'test.log'
_UNDECLARED_OUTPUTS = 'undeclared_outputs'

_TEST_SUMMARY_YAML = 'test_summary.yaml'
_TEST_LOG_INFO = 'test_log.INFO'

_SUITE_NAME = 'suite_name'
_RUN_IDENTIFIER = 'run_identifier'

_GCS_BASE_LINK = 'https://console.cloud.google.com/storage/browser'
_GCS_DEFAULT_TIMEOUT_SECS = 300

_ResultstoreTreeTags = mobly_result_converter.ResultstoreTreeTags
_ResultstoreTreeAttributes = mobly_result_converter.ResultstoreTreeAttributes

_Status = resultstore_client.Status


@dataclasses.dataclass()
class _TestResultInfo:
    """Info from the parsed test summary used for the Resultstore invocation."""

    # Aggregate status of the overall test run.
    status: _Status = _Status.UNKNOWN
    # Target ID for the test.
    target_id: str | None = None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parses the command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'mobly_dir',
        help='Directory on host where Mobly results are stored.',
    )
    parser.add_argument(
        '--gcs_bucket',
        help='Bucket in GCS where test artifacts are uploaded. If unspecified, '
             'use the current GCP project name as the bucket name.',
    )
    parser.add_argument(
        '--gcs_dir',
        help=(
            'Directory to save test artifacts in GCS. If unspecified or empty, '
            'use the current timestamp as the GCS directory name.'
        ),
    )
    parser.add_argument(
        '--gcs_upload_timeout',
        type=int,
        default=_GCS_DEFAULT_TIMEOUT_SECS,
        help=(
            'Timeout (in seconds) to upload each file to GCS. '
            f'Default: {_GCS_DEFAULT_TIMEOUT_SECS} seconds.'),
    )
    parser.add_argument(
        '--test_title',
        help='Custom test title to display in the result UI.'
    )
    parser.add_argument(
        '--label',
        action='append',
        help='Label to attach to the uploaded result. Can be repeated for '
             'multiple labels.'
    )
    parser.add_argument(
        '--no_convert_result',
        action='store_true',
        help=(
            'Upload the files as is, without first converting Mobly results to '
            'Resultstore\'s format. The source directory must contain at least '
            'a `test.xml` file, and an `undeclared_outputs` zip or '
            'subdirectory.')
    )
    parser.add_argument(
        '--reset_gcp_login', action='store_true',
        help='Resets the GCP credentials for the result upload, so the user is '
             'prompted for a new login. Use this to change the current project '
             'ID.'
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true', help='Enable debug logs.'
    )
    return parser.parse_args(args=argv or sys.argv[1:])


def _setup_logging(verbose: bool) -> None:
    """Configures the logging for this module."""
    debug_log_path = tempfile.mkstemp('_upload_log.txt')[1]
    file_handler = logging.FileHandler(debug_log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(module)s.%(funcName)s] %(message)s'
    ))
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(
        logging.Formatter('%(levelname)s: %(message)s'))
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=(file_handler, stream_handler)
    )

    logging.getLogger('googleapiclient').setLevel(logging.WARNING)
    logging.getLogger('google.auth').setLevel(logging.ERROR)
    logging.info('Debug logs are saved to %s', debug_log_path)
    print('-' * 50)


def _run_gcloud_command(args: list[str]) -> None:
    """Runs a command with the gcloud CLI."""
    try:
        subprocess.check_call(['gcloud'] + args)
    except FileNotFoundError:
        logging.error(
            'Failed to run `gcloud` commands! Please install the `gcloud` CLI '
            'from https://cloud.google.com/sdk/docs/install\n')
        raise


def _gcloud_login_and_set_project() -> None:
    """Get gcloud application default creds and set the desired GCP project."""
    logging.info('No credentials found. Performing initial setup.')
    project_id = ''
    while not project_id:
        project_id = input('Enter your GCP project ID: ')
    os.environ[google.auth.environment_vars.PROJECT] = project_id
    _run_gcloud_command(
        ['config', 'set', 'project', project_id]
    )
    _run_gcloud_command(
        ['auth', 'application-default', 'login', '--no-launch-browser']
    )
    _run_gcloud_command(
        ['auth', 'application-default', 'set-quota-project', project_id]
    )
    logging.info('Initial setup complete!')
    print('-' * 50)


def _get_project_number(project_id: str) -> str:
    """Get the project number associated with a GCP project ID."""
    client = resourcemanager_v3.ProjectsClient()
    response = client.get_project(name=f'projects/{project_id}')
    return response.name.split('/', 1)[1]


def _retrieve_api_key(project_id: str) -> str | None:
    """Downloads the Resultstore API key for the given Google Cloud project."""
    project_number = _get_project_number(project_id)
    client = api_keys_v2.ApiKeysClient()
    keys = client.list_keys(
        parent=f'projects/{project_number}/locations/global'
    ).keys
    for key in keys:
        if key.display_name == _API_KEY_DISPLAY_NAME:
            return client.get_key_string(name=key.name).key_string
    return None


def _convert_results(
        mobly_dir: pathlib.Path, dest_dir: pathlib.Path) -> _TestResultInfo:
    """Converts Mobly test results into Resultstore test.xml and test.log."""
    test_result_info = _TestResultInfo()
    logging.info('Converting raw Mobly logs into Resultstore artifacts...')
    # Generate the test.xml
    mobly_yaml_path = mobly_dir.joinpath(_TEST_SUMMARY_YAML)
    if mobly_yaml_path.is_file():
        test_xml = mobly_result_converter.convert(mobly_yaml_path, mobly_dir)
        ElementTree.indent(test_xml)
        test_xml.write(
            str(dest_dir.joinpath(_TEST_XML)),
            encoding='utf-8',
            xml_declaration=True,
        )
        test_result_info = _get_test_result_info_from_test_xml(test_xml)

    # Copy test_log.INFO to test.log
    test_log_info = mobly_dir.joinpath(_TEST_LOG_INFO)
    if test_log_info.is_file():
        shutil.copyfile(test_log_info, dest_dir.joinpath(_TEST_LOG))

    return test_result_info


def _aggregate_testcase_iteration_results(
        iteration_results: list[str]):
    """Determines the aggregate result from a list of test case iterations.

    This is only applicable to test cases with repeat/retry.
    """
    iterations_failed = [
        result == _Status.FAILED for result in iteration_results
        if result != _Status.SKIPPED
    ]
    # Skip if all iterations skipped
    if not iterations_failed:
        return _Status.SKIPPED
    # Fail if all iterations failed
    if all(iterations_failed):
        return _Status.FAILED
    # Flaky if some iterations failed
    if any(iterations_failed):
        return _Status.FLAKY
    # Pass otherwise
    return _Status.PASSED


def _aggregate_subtest_results(subtest_results: list[str]):
    """Determines the aggregate result from a list of subtest nodes.

    This is used to provide a test class result based on the test cases, or
    a test suite result based on the test classes.
    """
    # Skip if all subtests skipped
    if all([result == _Status.SKIPPED for result in subtest_results]):
        return _Status.SKIPPED

    any_flaky = False
    for result in subtest_results:
        # Fail if any subtest failed
        if result == _Status.FAILED:
            return _Status.FAILED
        # Record flaky subtest
        if result == _Status.FLAKY:
            any_flaky = True
    # Flaky if any subtest is flaky, pass otherwise
    return _Status.FLAKY if any_flaky else _Status.PASSED


def _get_test_status_from_xml(mobly_suite_element: ElementTree.Element):
    """Gets the overall status from the test XML."""
    test_class_elements = mobly_suite_element.findall(
        f'./{_ResultstoreTreeTags.TESTSUITE.value}')
    test_class_results = []
    for test_class_element in test_class_elements:
        test_case_results = []
        test_case_iteration_results = collections.defaultdict(list)
        test_case_elements = test_class_element.findall(
            f'./{_ResultstoreTreeTags.TESTCASE.value}')
        for test_case_element in test_case_elements:
            result = _Status.PASSED
            if test_case_element.get(
                    _ResultstoreTreeAttributes.RESULT.value) == 'skipped':
                result = _Status.SKIPPED
            if (
                    test_case_element.find(
                        f'./{_ResultstoreTreeTags.FAILURE.value}') is not None
                    or test_case_element.find(
                        f'./{_ResultstoreTreeTags.ERROR.value}') is not None
            ):
                result = _Status.FAILED
            # Add to iteration results if run as part of a repeat/retry
            # Otherwise, add to test case results directly
            if (
                    test_case_element.get(
                        _ResultstoreTreeAttributes.RETRY_NUMBER.value) or
                    test_case_element.get(
                        _ResultstoreTreeAttributes.REPEAT_NUMBER.value)
            ):
                test_case_iteration_results[
                    test_case_element.get(_ResultstoreTreeAttributes.NAME.value)
                ].append(result)
            else:
                test_case_results.append(result)

        for iteration_result_list in test_case_iteration_results.values():
            test_case_results.append(
                _aggregate_testcase_iteration_results(iteration_result_list)
            )
        test_class_results.append(
            _aggregate_subtest_results(test_case_results)
        )
    return _aggregate_subtest_results(test_class_results)


def _get_test_result_info_from_test_xml(
        test_xml: ElementTree.ElementTree,
) -> _TestResultInfo:
    """Parses a test_xml element into a _TestResultInfo."""
    test_result_info = _TestResultInfo()
    mobly_suite_element = test_xml.getroot().find(
        f'./{_ResultstoreTreeTags.TESTSUITE.value}'
    )
    if mobly_suite_element is None:
        return test_result_info
    # Set aggregate test status
    test_result_info.status = _get_test_status_from_xml(mobly_suite_element)

    # Set target ID based on test class names, suite name, and custom run
    # identifier.
    suite_name_value = None
    run_identifier_value = None
    properties_element = mobly_suite_element.find(
        f'./{_ResultstoreTreeTags.PROPERTIES.value}'
    )
    if properties_element is not None:
        suite_name = properties_element.find(
            f'./{_ResultstoreTreeTags.PROPERTY.value}'
            f'[@{_ResultstoreTreeAttributes.NAME.value}="{_SUITE_NAME}"]'
        )
        if suite_name is not None:
            suite_name_value = suite_name.get(
                _ResultstoreTreeAttributes.VALUE.value
            )
        run_identifier = properties_element.find(
            f'./{_ResultstoreTreeTags.PROPERTY.value}'
            f'[@{_ResultstoreTreeAttributes.NAME.value}="{_RUN_IDENTIFIER}"]'
        )
        if run_identifier is not None:
            run_identifier_value = run_identifier.get(
                _ResultstoreTreeAttributes.VALUE.value
            )
    if suite_name_value:
        target_id = suite_name_value
    else:
        test_class_elements = mobly_suite_element.findall(
            f'./{_ResultstoreTreeTags.TESTSUITE.value}')
        test_class_names = [
            test_class_element.get(_ResultstoreTreeAttributes.NAME.value)
            for test_class_element in test_class_elements
        ]
        target_id = '+'.join(test_class_names)
    if run_identifier_value:
        target_id = f'{target_id} {run_identifier_value}'

    test_result_info.target_id = target_id
    return test_result_info


def _upload_dir_to_gcs(
        src_dir: pathlib.Path, gcs_bucket: str, gcs_dir: str, timeout: int
) -> list[str]:
    """Uploads the given directory to a GCS bucket."""
    # Set correct MIME types for certain text-format files.
    with resources.as_file(
            resources.files('results_uploader').joinpath(
                'data/mime.types')) as path:
        mimetypes.init([path])

    bucket_obj = storage.Client().bucket(gcs_bucket)

    glob = src_dir.rglob('*')
    file_paths = [
        str(path.relative_to(src_dir).as_posix())
        for path in glob
        if path.is_file()
    ]

    logging.info(
        'Uploading %s files from %s to Cloud Storage directory %s/%s...',
        len(file_paths),
        str(src_dir),
        gcs_bucket,
        gcs_dir,
    )
    # Ensure that the destination directory has a trailing '/'.
    blob_name_prefix = gcs_dir
    if blob_name_prefix and not blob_name_prefix.endswith('/'):
        blob_name_prefix += '/'

    # If running on Windows, disable multiprocessing for upload.
    worker_type = (
        transfer_manager.THREAD
        if platform.system() == 'Windows'
        else transfer_manager.PROCESS
    )
    results = transfer_manager.upload_many_from_filenames(
        bucket_obj,
        file_paths,
        source_directory=str(src_dir),
        blob_name_prefix=blob_name_prefix,
        skip_if_exists=True,
        worker_type=worker_type,
        upload_kwargs={'timeout': timeout},
    )

    success_paths = []
    for file_path, result in zip(file_paths, results):
        if isinstance(result, Exception):
            logging.warning('Failed to upload %s. Error: %s', file_path, result)
        else:
            logging.debug('Uploaded %s.', file_path)
            success_paths.append(file_path)

    return [f'{gcs_dir}/{path}' for path in success_paths]


def _upload_to_resultstore(
        creds: google.auth.credentials.Credentials,
        project_id: str,
        api_key: str,
        gcs_bucket: str,
        gcs_base_dir: str,
        file_paths: list[str],
        status: _Status,
        target_id: str | None,
        labels: list[str],
) -> None:
    """Calls the Resultstore Upload API to generate a new invocation."""
    logging.info('Generating Resultstore link...')
    service = discovery.build(
        _RESULTSTORE_SERVICE_NAME,
        _API_VERSION,
        discoveryServiceUrl=_DISCOVERY_SERVICE_URL,
        developerKey=api_key,
    )
    client = resultstore_client.ResultstoreClient(service, creds, project_id)
    client.create_invocation(labels)
    client.create_default_configuration()
    client.create_target(target_id)
    client.create_configured_target()
    client.create_action(gcs_bucket, gcs_base_dir, file_paths)
    client.set_status(status)
    client.merge_configured_target()
    client.finalize_configured_target()
    client.merge_target()
    client.finalize_target()
    client.merge_invocation()
    client.finalize_invocation()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    _setup_logging(args.verbose)

    mobly_dir = pathlib.Path(args.mobly_dir).absolute().expanduser()
    if not mobly_dir.is_dir():
        logging.error(
            'The specified log directory %s does not exist, aborting.',
            mobly_dir
        )
        return

    # Configure local GCP parameters
    if args.reset_gcp_login:
        _run_gcloud_command(['auth', 'application-default', 'revoke', '-q'])
        if os.getenv(google.auth.environment_vars.CREDENTIALS):
            del os.environ[google.auth.environment_vars.CREDENTIALS]
        _gcloud_login_and_set_project()
    try:
        creds, project_id = google.auth.default()
    except google.auth.exceptions.DefaultCredentialsError:
        _gcloud_login_and_set_project()
        creds, project_id = google.auth.default()
    logging.info('Current GCP project ID: %s', project_id)
    api_key = _retrieve_api_key(project_id)
    if api_key is None:
        logging.error(
            'No API key with name [%s] found for project [%s]. Contact the '
            'project owner to create the required key.',
            _API_KEY_DISPLAY_NAME, project_id
        )
        return
    gcs_bucket = project_id if args.gcs_bucket is None else args.gcs_bucket
    gcs_base_dir = pathlib.PurePath(
        datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        if not args.gcs_dir
        else args.gcs_dir
    )

    if args.no_convert_result:
        # Determine the final status based on the test.xml
        test_xml = ElementTree.parse(mobly_dir.joinpath(_TEST_XML))
        test_result_info = _get_test_result_info_from_test_xml(test_xml)
        # Upload the contents of mobly_dir directly
        gcs_files = _upload_dir_to_gcs(
            mobly_dir, gcs_bucket, gcs_base_dir.as_posix(),
            args.gcs_upload_timeout
        )
    else:
        # Generate and upload test.xml and test.log
        with tempfile.TemporaryDirectory() as tmp:
            converted_dir = pathlib.Path(tmp).joinpath(gcs_base_dir)
            converted_dir.mkdir(parents=True)
            test_result_info = _convert_results(mobly_dir, converted_dir)
            gcs_files = _upload_dir_to_gcs(
                converted_dir, gcs_bucket, gcs_base_dir.as_posix(),
                args.gcs_upload_timeout
            )
        # Upload raw Mobly logs to undeclared_outputs/ subdirectory
        gcs_files += _upload_dir_to_gcs(
            mobly_dir, gcs_bucket,
            gcs_base_dir.joinpath(_UNDECLARED_OUTPUTS).as_posix(),
            args.gcs_upload_timeout
        )
    _upload_to_resultstore(
        creds,
        project_id,
        api_key,
        gcs_bucket,
        gcs_base_dir.as_posix(),
        gcs_files,
        test_result_info.status,
        args.test_title or test_result_info.target_id,
        args.label
    )


if __name__ == '__main__':
    main()
