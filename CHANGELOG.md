# Mobly Android Partner Tools release history

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
