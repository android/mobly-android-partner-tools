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

"""A converter for Mobly result schema to Resultstore schema.

Each Mobly test class maps to a Resultstore testsuite and each Mobly test method
maps to a Resultstore testcase. For example:

  Mobly schema:

  Test Class: HelloWorldTest
  Test Name: test_hello
  Type: Record
  Result: PASS

  Resultstore schema:

  <testsuite name="HelloWorldTest" tests=1>
    <testcase name="test_hello"/>
  </testsuite>
"""

import dataclasses
import datetime
import enum
import logging
import pathlib
import re
from typing import Any, Dict, Iterator, List, Mapping, Optional
from xml.etree import ElementTree

from mobly import records
import yaml

_MOBLY_RECORD_TYPE_KEY = 'Type'

_MOBLY_TEST_SUITE_NAME = 'MoblyTest'

_TEST_INTERRUPTED_MESSAGE = 'Details: Test was interrupted manually.'

_ILLEGAL_XML_CHARS = re.compile(
    '[\x00-\x08\x0b\x0c\x0e-\x1F\uD800-\uDFFF\uFFFE\uFFFF]'
)

_ILLEGAL_YAML_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')


class MoblyResultstoreProperties(enum.Enum):
    """Resultstore properties defined specifically for all Mobly tests.

    All these properties apply to the testcase level. TEST_CLASS and
    TEST_TYPE apply to both the testcase and testsuite level.
    """

    BEGIN_TIME = 'mobly_begin_time'
    END_TIME = 'mobly_end_time'
    TEST_CLASS = 'mobly_test_class'
    TEST_TYPE = 'test_type'
    UID = 'mobly_uid'
    TEST_OUTPUT = 'test_output'
    TEST_SIGNATURE = 'mobly_signature'
    SKIP_REASON = 'skip_reason'
    ERROR_MESSAGE = 'mobly_error_message'
    ERROR_TYPE = 'mobly_error_type'
    STACK_TRACE = 'mobly_stack_trace'


_MOBLY_PROPERTY_VALUES = frozenset(e.value for e in MoblyResultstoreProperties)


class ResultstoreTreeTags(enum.Enum):
    """Common tags for Resultstore tree nodes."""

    TESTSUITES = 'testsuites'
    TESTSUITE = 'testsuite'
    TESTCASE = 'testcase'
    PROPERTIES = 'properties'
    PROPERTY = 'property'
    FAILURE = 'failure'
    ERROR = 'error'


class ResultstoreTreeAttributes(enum.Enum):
    """Common attributes for Resultstore tree nodes."""

    ERRORS = 'errors'
    FAILURES = 'failures'
    TESTS = 'tests'
    CLASS_NAME = 'classname'
    RESULT = 'result'
    STATUS = 'status'
    TIME = 'time'
    TIMESTAMP = 'timestamp'
    NAME = 'name'
    VALUE = 'value'
    MESSAGE = 'message'
    RETRY_NUMBER = 'retrynumber'
    REPEAT_NUMBER = 'repeatnumber'
    ERROR_TYPE = 'type'
    RERAN_TEST_NAME = 'rerantestname'


@dataclasses.dataclass
class TestSuiteSummary:
    num_tests: int
    num_errors: int
    num_failures: int


@dataclasses.dataclass
class ReranNode:
    reran_test_name: str
    original_test_name: str
    index: int
    node_type: records.TestParentType


def _find_all_elements(
        mobly_root: ElementTree.Element,
        class_name: Optional[str],
        test_name: Optional[str],
) -> Iterator[ElementTree.Element]:
    """Finds all elements in the Resultstore tree with class name and/or
    test_name.

    If class name is absent, it will find all elements with the test name
    across all test classes. If test name is absent it will find all elements
    with class name. If both are absent, it will just return the Mobly root
    tree.

    Args:
      mobly_root: Root element of the Mobly test Resultstore tree.
      class_name: Mobly test class name to get the elements for.
      test_name: Mobly test names to get the elements for.

    Yields:
      Iterator of elements satisfying the class_name and test_name search
      criteria.
    """
    if class_name is None and test_name is None:
        yield mobly_root
        return

    xpath = f'./{ResultstoreTreeTags.TESTSUITE.value}'
    if class_name is not None:
        xpath += f'[@{ResultstoreTreeAttributes.NAME.value}="{class_name}"]'
    if test_name is not None:
        xpath += (
            f'/{ResultstoreTreeTags.TESTCASE.value}'
            f'[@{ResultstoreTreeAttributes.NAME.value}="{test_name}"]'
        )

    yield from mobly_root.iterfind(xpath)


def _create_or_return_properties_element(
        element: ElementTree.Element,
) -> ElementTree.Element:
    properties_element = element.find(
        f'./{ResultstoreTreeTags.PROPERTIES.value}')
    if properties_element is not None:
        return properties_element
    return ElementTree.SubElement(element, ResultstoreTreeTags.PROPERTIES.value)


def _add_or_update_property_element(
        properties_element: ElementTree.Element, name: str, value: str
):
    """Adds a property element or update the property value."""
    name = _ILLEGAL_XML_CHARS.sub('', name)
    value = _ILLEGAL_XML_CHARS.sub('', value)
    property_element = properties_element.find(
        f'./{ResultstoreTreeTags.PROPERTY.value}'
        f'[@{ResultstoreTreeAttributes.NAME.value}="{name}"]'
    )
    if property_element is None:
        property_element = ElementTree.SubElement(
            properties_element, ResultstoreTreeTags.PROPERTY.value
        )
        property_element.set(ResultstoreTreeAttributes.NAME.value, name)
    property_element.set(ResultstoreTreeAttributes.VALUE.value, value)


def _add_file_annotations(
        entry: Mapping[str, Any],
        properties_element: ElementTree.Element,
        mobly_base_directory: Optional[pathlib.Path],
) -> None:
    """Adds file annotations for a Mobly test case files.

    The mobly_base_directory is used to find the files belonging to a test case.
    The files under "mobly_base_directory/test_class/test_method" belong to the
    test_class#test_method Resultstore node. Additionally, it is used to
    determine the relative path of the files for Resultstore undeclared outputs.
    The file annotation must be written for the relative path.

    Args:
      entry: Mobly summary entry for the test case.
      properties_element: Test case properties element.
      mobly_base_directory: Base directory of the Mobly test.
    """
    # If mobly_base_directory is not provided, the converter will not add the
    # annotations to associate the files with the test cases.
    if (
            mobly_base_directory is None
            or entry.get(records.TestResultEnums.RECORD_SIGNATURE, None) is None
    ):
        return

    test_class = entry[records.TestResultEnums.RECORD_CLASS]
    test_case_directory = mobly_base_directory.joinpath(
        test_class,
        entry[records.TestResultEnums.RECORD_SIGNATURE]
    )

    test_case_files = test_case_directory.rglob('*')
    file_counter = 0
    for file_path in test_case_files:
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(mobly_base_directory)
        _add_or_update_property_element(
            properties_element,
            f'test_output{file_counter}',
            str(relative_path.as_posix()),
        )
        file_counter += 1


def _create_mobly_root_element(
        summary_record: Mapping[str, Any]
) -> ElementTree.Element:
    """Creates a Resultstore XML testsuite node for a Mobly test summary."""
    full_summary = TestSuiteSummary(
        num_tests=summary_record['Requested'],
        num_errors=summary_record['Error'],
        num_failures=summary_record['Failed'],
    )
    # Create the root Resultstore node to wrap the Mobly test.
    main_wrapper = ElementTree.Element(ResultstoreTreeTags.TESTSUITES.value)
    main_wrapper.set(ResultstoreTreeAttributes.NAME.value, '__main__')
    main_wrapper.set(ResultstoreTreeAttributes.TIME.value, '0')
    main_wrapper.set(
        ResultstoreTreeAttributes.ERRORS.value, str(full_summary.num_errors)
    )
    main_wrapper.set(
        ResultstoreTreeAttributes.FAILURES.value, str(full_summary.num_failures)
    )
    main_wrapper.set(
        ResultstoreTreeAttributes.TESTS.value, str(full_summary.num_tests)
    )

    mobly_test_root = ElementTree.SubElement(
        main_wrapper, ResultstoreTreeTags.TESTSUITE.value
    )
    mobly_test_root.set(
        ResultstoreTreeAttributes.NAME.value, _MOBLY_TEST_SUITE_NAME
    )
    mobly_test_root.set(ResultstoreTreeAttributes.TIME.value, '0')
    mobly_test_root.set(
        ResultstoreTreeAttributes.ERRORS.value, str(full_summary.num_errors)
    )
    mobly_test_root.set(
        ResultstoreTreeAttributes.FAILURES.value, str(full_summary.num_failures)
    )
    mobly_test_root.set(
        ResultstoreTreeAttributes.TESTS.value, str(full_summary.num_tests)
    )

    return main_wrapper


def _create_class_element(
        class_name: str, class_summary: TestSuiteSummary
) -> ElementTree.Element:
    """Creates a Resultstore XML testsuite node for a Mobly test class summary.

    Args:
      class_name: Mobly test class name.
      class_summary: Mobly test class summary.

    Returns:
      A Resultstore testsuite node representing one Mobly test class.
    """
    class_element = ElementTree.Element(ResultstoreTreeTags.TESTSUITE.value)
    class_element.set(ResultstoreTreeAttributes.NAME.value, class_name)
    class_element.set(ResultstoreTreeAttributes.TIME.value, '0')
    class_element.set(
        ResultstoreTreeAttributes.TESTS.value, str(class_summary.num_tests)
    )
    class_element.set(
        ResultstoreTreeAttributes.ERRORS.value, str(class_summary.num_errors)
    )
    class_element.set(
        ResultstoreTreeAttributes.FAILURES.value,
        str(class_summary.num_failures)
    )

    properties_element = _create_or_return_properties_element(class_element)
    _add_or_update_property_element(
        properties_element,
        MoblyResultstoreProperties.TEST_CLASS.value,
        class_name,
    )
    _add_or_update_property_element(
        properties_element,
        MoblyResultstoreProperties.TEST_TYPE.value,
        'mobly_class',
    )

    return class_element


def _set_rerun_node(
        signature: str,
        child_parent_map: Mapping[str, str],
        parent_type_map: Mapping[str, records.TestParentType],
        signature_test_name_map: Mapping[str, str],
        rerun_node_map: Dict[str, ReranNode],
) -> None:
    """Sets the rerun node in the rerun node map for the current test signature.

    This function traverses the child parent map recursively until it finds the
    root test run for the rerun chain. Then it uses the original test name from
    there and builds the indices.

    Args:
      signature: Current test signature.
      child_parent_map: Map of test signature to the parent test signature.
      parent_type_map: Map of parent test signature to the parent type.
      signature_test_name_map: Map of test signature to test name.
      rerun_node_map: Map of test signature to rerun information.
    """
    if signature in rerun_node_map:
        return

    # If there is no parent, then this is the root test in the retry chain.
    if signature not in child_parent_map:
        if parent_type_map[signature] == records.TestParentType.REPEAT:
            # If repeat, remove the '_#' suffix to get the original test name.
            original_test_name = \
              signature_test_name_map[signature].rsplit('_', 1)[0]
        else:
            original_test_name = signature_test_name_map[signature]
        rerun_node_map[signature] = ReranNode(
            signature_test_name_map[signature],
            original_test_name,
            0,
            parent_type_map[signature],
        )
        return

    parent_signature = child_parent_map[signature]
    _set_rerun_node(
        parent_signature,
        child_parent_map,
        parent_type_map,
        signature_test_name_map,
        rerun_node_map,
    )

    parent_node = rerun_node_map[parent_signature]
    rerun_node_map[signature] = ReranNode(
        signature_test_name_map[signature],
        parent_node.original_test_name,
        parent_node.index + 1,
        parent_node.node_type,
    )


def _get_reran_nodes(
        entries: List[Mapping[str, Any]]
) -> Mapping[str, ReranNode]:
    """Gets the nodes for any test case reruns.

    Args:
      entries: Summary entries for the Mobly test runs.

    Returns:
      A map of test signature to node information.
    """
    child_parent_map = {}
    parent_type_map = {}
    signature_test_name_map = {}
    for entry in entries:
        if records.TestResultEnums.RECORD_SIGNATURE not in entry:
            continue
        current_signature = entry[records.TestResultEnums.RECORD_SIGNATURE]
        signature_test_name_map[current_signature] = entry[
            records.TestResultEnums.RECORD_NAME
        ]
        # This is a dictionary with parent and type.
        rerun_parent = entry.get(records.TestResultEnums.RECORD_PARENT, None)
        if rerun_parent is not None:
            parent_signature = rerun_parent['parent']
            parent_type = (
                records.TestParentType.RETRY
                if rerun_parent['type'] == 'retry'
                else records.TestParentType.REPEAT
            )
            child_parent_map[current_signature] = parent_signature
            parent_type_map[parent_signature] = parent_type

    rerun_node_map = {}
    for signature in child_parent_map:
        # Populates the rerun node map.
        _set_rerun_node(
            signature,
            child_parent_map,
            parent_type_map,
            signature_test_name_map,
            rerun_node_map,
        )

    return rerun_node_map


def _process_record(
        entry: Mapping[str, Any],
        reran_node: Optional[ReranNode],
        mobly_base_directory: Optional[pathlib.Path],
) -> ElementTree.Element:
    """Processes a single Mobly test record entry to a Resultstore test case
    node.

    Args:
      entry: Summary of a single Mobly test case.
      reran_node: Rerun information if this test case is a rerun. Only present
        if this test is part of a rerun chain.
      mobly_base_directory: Base directory for the Mobly test. Artifacts from
        the Mobly test will be saved here.

    Returns:
      A Resultstore XML node representing a single test case.
    """
    begin_time = entry[records.TestResultEnums.RECORD_BEGIN_TIME]
    end_time = entry[records.TestResultEnums.RECORD_END_TIME]
    testcase_element = ElementTree.Element(ResultstoreTreeTags.TESTCASE.value)
    result = entry[records.TestResultEnums.RECORD_RESULT]

    if reran_node is not None:
        if reran_node.node_type == records.TestParentType.RETRY:
            testcase_element.set(
                ResultstoreTreeAttributes.RETRY_NUMBER.value,
                str(reran_node.index)
            )
        elif reran_node.node_type == records.TestParentType.REPEAT:
            testcase_element.set(
                ResultstoreTreeAttributes.REPEAT_NUMBER.value,
                str(reran_node.index)
            )
        testcase_element.set(
            ResultstoreTreeAttributes.NAME.value, reran_node.original_test_name
        )
        testcase_element.set(
            ResultstoreTreeAttributes.RERAN_TEST_NAME.value,
            reran_node.reran_test_name,
        )
    else:
        testcase_element.set(
            ResultstoreTreeAttributes.NAME.value,
            entry[records.TestResultEnums.RECORD_NAME],
        )
        testcase_element.set(
            ResultstoreTreeAttributes.RERAN_TEST_NAME.value,
            entry[records.TestResultEnums.RECORD_NAME],
        )
    testcase_element.set(
        ResultstoreTreeAttributes.CLASS_NAME.value,
        entry[records.TestResultEnums.RECORD_CLASS],
    )
    if result == records.TestResultEnums.TEST_RESULT_SKIP:
        testcase_element.set(ResultstoreTreeAttributes.RESULT.value, 'skipped')
        testcase_element.set(ResultstoreTreeAttributes.STATUS.value, 'notrun')
        testcase_element.set(ResultstoreTreeAttributes.TIME.value, '0')
    elif result is None:
        testcase_element.set(ResultstoreTreeAttributes.RESULT.value,
                             'completed')
        testcase_element.set(ResultstoreTreeAttributes.STATUS.value, 'run')
        testcase_element.set(ResultstoreTreeAttributes.TIME.value, '0')
        testcase_element.set(
            ResultstoreTreeAttributes.TIMESTAMP.value,
            datetime.datetime.fromtimestamp(
                begin_time / 1000, tz=datetime.timezone.utc
            ).strftime('%Y-%m-%dT%H:%M:%SZ'),
        )
    else:
        testcase_element.set(ResultstoreTreeAttributes.RESULT.value,
                             'completed')
        testcase_element.set(ResultstoreTreeAttributes.STATUS.value, 'run')
        testcase_element.set(
            ResultstoreTreeAttributes.TIME.value, str(end_time - begin_time)
        )
        testcase_element.set(
            ResultstoreTreeAttributes.TIMESTAMP.value,
            datetime.datetime.fromtimestamp(
                begin_time / 1000, tz=datetime.timezone.utc
            ).strftime('%Y-%m-%dT%H:%M:%SZ'),
        )

    # Add Mobly specific test case properties.
    properties_element = _create_or_return_properties_element(testcase_element)
    if result == records.TestResultEnums.TEST_RESULT_SKIP:
        _add_or_update_property_element(
            properties_element,
            MoblyResultstoreProperties.SKIP_REASON.value,
            f'Details: {entry[records.TestResultEnums.RECORD_DETAILS]}',
        )
    elif result is None:
        _add_or_update_property_element(
            properties_element,
            MoblyResultstoreProperties.BEGIN_TIME.value,
            str(begin_time),
        )
    else:
        _add_or_update_property_element(
            properties_element,
            MoblyResultstoreProperties.BEGIN_TIME.value,
            str(begin_time),
        )
        _add_or_update_property_element(
            properties_element,
            MoblyResultstoreProperties.END_TIME.value,
            str(end_time),
        )
    _add_or_update_property_element(
        properties_element,
        MoblyResultstoreProperties.TEST_CLASS.value,
        entry[records.TestResultEnums.RECORD_CLASS],
    )
    _add_or_update_property_element(
        properties_element,
        MoblyResultstoreProperties.TEST_TYPE.value,
        'mobly_test',
    )

    if entry.get(records.TestResultEnums.RECORD_SIGNATURE, None) is not None:
        _add_or_update_property_element(
            properties_element,
            MoblyResultstoreProperties.TEST_SIGNATURE.value,
            entry[records.TestResultEnums.RECORD_SIGNATURE],
        )

    _add_file_annotations(
        entry,
        properties_element,
        mobly_base_directory,
    )

    if entry[records.TestResultEnums.RECORD_UID] is not None:
        _add_or_update_property_element(
            properties_element,
            MoblyResultstoreProperties.UID.value,
            entry[records.TestResultEnums.RECORD_UID],
        )

    if result is None:
        error_element = ElementTree.SubElement(
            testcase_element, ResultstoreTreeTags.ERROR.value
        )
        error_element.set(
            ResultstoreTreeAttributes.MESSAGE.value, _TEST_INTERRUPTED_MESSAGE
        )
        error_element.text = _TEST_INTERRUPTED_MESSAGE
    elif (
            result == records.TestResultEnums.TEST_RESULT_FAIL
            or result == records.TestResultEnums.TEST_RESULT_ERROR
    ):
        error_message = (
            f'Details: {entry[records.TestResultEnums.RECORD_DETAILS]}')
        tag = (
            ResultstoreTreeTags.FAILURE.value
            if result == records.TestResultEnums.TEST_RESULT_FAIL
            else ResultstoreTreeTags.ERROR.value
        )
        failure_or_error_element = ElementTree.SubElement(testcase_element, tag)
        failure_or_error_element.set(
            ResultstoreTreeAttributes.MESSAGE.value, error_message
        )
        _add_or_update_property_element(
            properties_element,
            MoblyResultstoreProperties.ERROR_MESSAGE.value,
            error_message,
        )

        # Add termination signal type and stack trace to the failure XML element
        # and the test case properties.
        termination_signal_type = entry[
            records.TestResultEnums.RECORD_TERMINATION_SIGNAL_TYPE
        ]
        if termination_signal_type is None:
            logging.warning(
                'Test %s has %s result without a termination signal type.',
                entry[records.TestResultEnums.RECORD_NAME],
                result,
            )
        else:
            failure_or_error_element.set(
                ResultstoreTreeAttributes.ERROR_TYPE.value,
                termination_signal_type
            )
            _add_or_update_property_element(
                properties_element,
                MoblyResultstoreProperties.ERROR_TYPE.value,
                termination_signal_type,
            )
        stack_trace = entry[records.TestResultEnums.RECORD_STACKTRACE]
        if stack_trace is None:
            logging.warning(
                'Test %s has %s result without a stack trace.',
                entry[records.TestResultEnums.RECORD_NAME],
                result,
            )
        else:
            failure_or_error_element.text = stack_trace
            _add_or_update_property_element(
                properties_element,
                MoblyResultstoreProperties.STACK_TRACE.value,
                stack_trace,
            )

    extra_errors = entry[records.TestResultEnums.RECORD_EXTRA_ERRORS]
    if extra_errors is not None:
        for _, error_details in extra_errors.items():
            extra_error_element = ElementTree.SubElement(
                testcase_element, ResultstoreTreeTags.ERROR.value
            )
            error_position = error_details[
                records.TestResultEnums.RECORD_POSITION]
            extra_error_element.set(
                ResultstoreTreeAttributes.MESSAGE.value,
                f'Error occurred at {error_position}.\nDetails: '
                f'{error_details[records.TestResultEnums.RECORD_DETAILS]}',
            )
            stack_trace = error_details[
                records.TestResultEnums.RECORD_STACKTRACE]
            if stack_trace is not None:
                extra_error_element.text = stack_trace
    return testcase_element


def convert(
        mobly_results_path: pathlib.Path,
        mobly_base_directory: Optional[pathlib.Path] = None,
) -> ElementTree.ElementTree:
    """Converts a Mobly results summary file to Resultstore XML schema.

    The mobly_base_directory will be used to compute the file links for each
    Resultstore tree element. If it is absent then the file links will be
    omitted.

    Args:
      mobly_results_path: Path to the Mobly summary YAML file.
      mobly_base_directory: Base directory of the Mobly test.

    Returns:
      A Resultstore XML tree for the Mobly test.
    """
    logging.info('Generating Resultstore tree...')

    with mobly_results_path.open('r', encoding='utf-8') as f:
        summary_entries = list(
            yaml.safe_load_all(_ILLEGAL_YAML_CHARS.sub('', f.read()))
        )

    summary_record = next(
        entry
        for entry in summary_entries
        if entry[_MOBLY_RECORD_TYPE_KEY]
        == records.TestSummaryEntryType.SUMMARY.value
    )

    main_root = _create_mobly_root_element(summary_record)

    mobly_test_root = main_root[0]
    mobly_root_properties = _create_or_return_properties_element(
        mobly_test_root)
    # Add files under the Mobly root directory to the Mobly test suite node.
    if mobly_base_directory is not None:
        file_counter = 0
        for file_path in mobly_base_directory.iterdir():
            if not file_path.is_file():
                continue
            relative_path = file_path.relative_to(mobly_base_directory)
            _add_or_update_property_element(
                mobly_root_properties,
                f'test_output{file_counter}',
                str(relative_path.as_posix()),
            )
            file_counter += 1

    test_case_entries = [
        entry
        for entry in summary_entries
        if (entry[_MOBLY_RECORD_TYPE_KEY]
            == records.TestSummaryEntryType.RECORD.value)
    ]
    # Populate the class summaries.
    class_summaries = {}
    for entry in test_case_entries:
        class_name = entry[records.TestResultEnums.RECORD_CLASS]

        if class_name not in class_summaries:
            class_summaries[class_name] = TestSuiteSummary(
                num_tests=0, num_errors=0, num_failures=0
            )

        class_summaries[class_name].num_tests += 1
        if (
                entry[records.TestResultEnums.RECORD_RESULT]
                == records.TestResultEnums.TEST_RESULT_ERROR
        ):
            class_summaries[class_name].num_errors += 1
        elif (
                entry[records.TestResultEnums.RECORD_RESULT]
                == records.TestResultEnums.TEST_RESULT_FAIL
        ):
            class_summaries[class_name].num_failures += 1

    # Create class nodes.
    class_elements = {}
    for class_name, summary in class_summaries.items():
        class_elements[class_name] = _create_class_element(class_name, summary)
        mobly_test_root.append(class_elements[class_name])

    # Append test case nodes to test class nodes.
    reran_nodes = _get_reran_nodes(test_case_entries)
    for entry in test_case_entries:
        class_name = entry[records.TestResultEnums.RECORD_CLASS]
        if (
                records.TestResultEnums.RECORD_SIGNATURE in entry
                and
                entry[records.TestResultEnums.RECORD_SIGNATURE] in reran_nodes
        ):
            reran_node = reran_nodes[
                entry[records.TestResultEnums.RECORD_SIGNATURE]]
        else:
            reran_node = None
        class_elements[class_name].append(
            _process_record(entry, reran_node, mobly_base_directory)
        )

    user_data_entries = [
        entry
        for entry in summary_entries
        if (entry[_MOBLY_RECORD_TYPE_KEY]
            == records.TestSummaryEntryType.USER_DATA.value)
    ]

    for user_data_entry in user_data_entries:
        class_name = user_data_entry.get(records.TestResultEnums.RECORD_CLASS,
                                         None)
        test_name = user_data_entry.get(records.TestResultEnums.RECORD_NAME,
                                        None)

        properties = user_data_entry.get('properties', None)
        if not isinstance(properties, dict):
            continue
        for element in _find_all_elements(mobly_test_root, class_name,
                                          test_name):
            properties_element = _create_or_return_properties_element(element)
            for name, value in properties.items():
                if name in _MOBLY_PROPERTY_VALUES:
                    # Do not override Mobly properties.
                    continue
                _add_or_update_property_element(
                    properties_element, str(name), str(value)
                )

    return ElementTree.ElementTree(main_root)
