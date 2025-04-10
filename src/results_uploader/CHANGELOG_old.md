# Mobly Results Uploader release history

## 0.7.3 (2025-04-01)

### New
* Enable the option to reset the stored GCP credentials upon upload with
  `--reset_gcp_login`, so the user may change their active GCP project.

### Fixes
* Any extra errors generated in a test's setup/teardown stages are now displayed
  alongside the test case's results in BTX.


## 0.7.2 (2024-12-13)

### New
* Enable the option to directly upload results already in the Resultstore format,
  skipping the conversion step.

### Fixes
* Stream verbose debug logs to a dedicated file.


## 0.7.1 (2024-12-06)

### Fixes
* If a target contains any flaky test nodes, but not failing ones, set the target
  status to FLAKY instead of FAILED.
  * FLAKY targets will appear with a yellow banner in the BTX page.


## 0.7 (2024-10-29)

### New
* Automatically prompt the user for GCP login if missing stored credentials.
  * The user is no longer required to separately run login commands before using
    the uploader for the first time.


## 0.6.1 (2024-08-21)

### Fixes
* The Resultstore service now requires API keys for its Upload API. This must
  be provided by the client.
  * Automatically fetch and use the `resultstore` API key from the user's Google
    Cloud project, if it exists.
  * Otherwise, the tool will show an error message for the missing key.


## 0.6 (2024-07-19)

### New
* Display newly uploaded results in the BTX invocation search page
  (https://btx.cloud.google.com/invocations).
* Support tagging uploaded results with `--label`.
  * Labels will be visible in the invocation search page.
  * Filters can be applied in the search page (`label:...`) to search
    for results with matching labels.
* Support specifying multilevel paths in `--gcs_dir`.
* Remove support for empty string `--gcs_dir`. Uploads to the root directory
  of a GCS bucket are no longer allowed.
* Add the uploader tool version to the result metadata.

### Fixes
* Mobly log files are no longer locally copied to a second temp location prior
  to upload.
* Remove manual GCS upload fallback (introduced in v0.3).


## 0.5.1 (2024-06-28)

### Fixes
* Extend the default timeout for GCS uploads and support custom timeout values.
* Enable automatic retry of GCS uploads following connection errors.


## 0.5 (2024-06-25)

### New
* Use `pathlib` for all file operations.
  * Support specifying relative paths.
  * Support specifying paths with backslash separators in Windows.


## 0.4 (2024-05-16)

### New
* Simplified CLI.
  * Upload directly using `results_uploader /path/to/mobly_dir`.
  * The storage bucket name defaults to the GCP project name.
* Automatically display the suite name in the header if specified by the suite.

### Fixes
* Open certain text-format files without the `.txt` extension directly
  in-browser, instead of opening a download prompt.
* The generated link now points directly to the "Tests" dashboard.
* Additionally show passing/flaky test cases by default, instead of only
  failed/errored ones.


## 0.3 (2024-04-10)

### Fixes
* Fall back to manual GCS upload (via web page) if the automated upload fails.
* Clean up console output.


## 0.2 (2024-03-28)

### Fixes
* Properly URL-encode the target resource name.
* Report targets with all skipped test cases as `skipped`.
* Update Resultstore UI link from source.cloud to BTX.
* Suppress warnings from imported modules.


## 0.1 (2024-01-05)

### New
* Add the `results_uploader` tool for uploading Mobly test results to the
  Resultstore service.
  * Uploads local test logs to a user-provided Google Cloud Storage location.
  * Creates a new test invocation record via Resultstore API.
  * Generates a web link to visualize results.
