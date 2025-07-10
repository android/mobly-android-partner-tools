# Mobly Android Partner Tools release history

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
