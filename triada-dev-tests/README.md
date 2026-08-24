# TRIADA development-run sandbox

This folder is intentionally isolated from the TRIADA runtime. Live development
tasks may create or modify files here only.

The test ladder is:

1. `easy`: add a pure function and a focused test;
2. `medium`: add a small module with validation, error handling, and tests;
3. `hard`: add a multi-file feature with an integration test and documentation.

The folder is disposable. Its files are evidence of TRIADA runs, not runtime
configuration.
