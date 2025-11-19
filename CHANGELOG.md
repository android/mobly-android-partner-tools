# Mobly Android Partner Tools release history

## 1.5.0 (2025-11-18)

### New
* [mobly_runner] When uploading test results with the `--upload_results` option,
  the runner captures the true start time and duration, and adds them to the BTX
  invocation details.
* [results_uploader] Add a `gcloud_setup.py` script that enables users to
  perform the first-time Google Cloud login as a standalone command.


## 1.4.2 (2025-09-15)

### Fixes
* [results_uploader] Fix typo for `testCase` in the Inspector URL.
* [results_uploader] Set `OAUTHLIB_RELAX_TOKEN_SCOPE` env variable to resolve
  gcloud login error.


## 1.4.1 (2025-09-09)

### Fixes
* [results_uploader] Exit early if there is nothing to upload, preventing an
  empty invocation from being created.


## 1.4.0 (2025-08-19)

### New
* [results_uploader] Enable batch uploading of multiple Mobly results.
  * Upload any directory containing one or more independent Mobly run logs, and
    the tool will generate a single link containing all of the results.
  * If the test was executed as part of Android CTS, use `--cts` mode to attach 
    CTS-specific data to the upload.


## 1.3.0 (2025-07-29)

### New
* [results_uploader] Add `inspector_link` property for each test case.
  * Users can now view the BTX Inspector page for uploaded results, where
    applicable.


## 1.2.0 (2025-07-09)

### New
* [mobly_runner] When uploading test results with the `-u` option, 
  use `--label_on_pass` to specify a label to automatically append to the upload
  only if the test result is passing.
  * Labels can be used to classify test results for debugging/review.


## 1.1.2 (2025-06-01)

### Fixes
* [results_uploader] Ensure new user or `--reset_gcp_login` prompt sets the 
  correct local project ID


## 1.1.1 (2025-05-07)

### Fixes
* [mobly_runner] Remove hardcoded BeToCQ APK resource file path when installing
  test APKs with `-i`


## 1.1.0 (2025-04-28)

### New
* [mobly_runner] Enable direct execution of test classes/suites as python files


## 1.0.0 (2025-04-16)

### New
* Initial version. 
  * Combine the existing Mobly runner and results uploader tools into a single
    unified library.
  * The runner can now automatically upload results upon completion, without
    separately invoking the uploader.
  * Enable automatic creation of test reports for submission to Android Partner
    Approvals (experimental).
