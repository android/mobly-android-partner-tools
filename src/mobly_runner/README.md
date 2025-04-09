# Mobly test runner

The Mobly test runner is a tool that serves as the entry point for executing a
given Mobly test or suite. It is designed with a focus on simplicity and 
flexibility. 

The runner analyzes the contents of a Mobly test package, performs test 
environment setup/teardown, and executes the test.

As a basic usage example:

```bash
mobly_runner my_test_suite
```

executes the installed Mobly test suite `my_test_suite`.

For more details, please refer to the CLI options in `mobly_runner -h`.
