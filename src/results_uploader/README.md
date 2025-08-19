# Mobly Results Uploader

The Results Uploader is a tool for generating shareable UI links for automated
test results.

It uploads test-generated files to Google Cloud Storage, and presents the
results in an organized way on a dedicated web UI (Resultstore/BTX). The result 
URL can then be shared to anyone who is given access (including both Google and 
non-Google accounts), allowing for easy tracking and debugging.

## First-time setup

To start using the Results Uploader, you need to be able to access the shared
Google Cloud Storage bucket:

1. Confirm/request access to the shared GCP project with your Google contact.
   The Googler will give you a project name to use.
2. Install the gcloud CLI from https://cloud.google.com/sdk/docs/install
    * If installation fails with the above method, try the alternative linked
      [here](https://cloud.google.com/sdk/docs/downloads-versioned-archives#installation_instructions).

## How to upload results

1. At the end of a completed test run, you'll see the final lines on the console
   output as follows. Record the folder path in the line starting with
   "Artifacts are saved in".

    ```
    Total time elapsed 961.7551812920001s
    Artifacts are saved in "/tmp/logs/mobly/Local5GTestbed/10-23-2023_10-30-50-685"
    Test summary saved in "/tmp/logs/mobly/Local5GTestbed/10-23-2023_10-30-50-685/test_summary.yaml"
    Test results: Error 0, Executed 1, Failed 0, Passed 1, Requested 0, Skipped 0
    ```

2. Run the uploader command, setting the `artifacts_folder` as the path recorded
   in the previous step.
    ```bash
    results_uploader <artifacts_folder>
    ```

3. If successful, at the end of the upload process you will get a link beginning
   with http://btx.cloud.google.com. Simply share this link to others who
   wish to view your test results.

### Automatically upload results upon test completion

To automatically upload results upon test completion, use the
[`mobly_runner`](../mobly_runner/README.md) to execute your tests, and 
add the following command-line option:

```bash
mobly_runner my_test_suite --upload_results
```

## Batch uploading
If you run
```bash
results_uploader <folder_containing_multiple_mobly_artifacts>
```

The tool automatically searches recursively for all Mobly artifact folders
contained within this directory, and creates a single BTX link with a sub-entry
for each folder.

You may use this feature to quickly share a set of related Mobly runs.

## Troubleshooting

* If the link is missing, or the contents of the link are empty, check the
  debug logs of the uploader. Its location is shown at the beginning of the
  tool's output indicated by `Debug logs are saved to: ...`.
* Report any tool issues to Google and attach all tool output, including the
  debug logs.

## Additional reference

To see a list of supported options, please consult `results_uploader --help`.
