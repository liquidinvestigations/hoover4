# Deployment render tests

[test_render.py](test_render.py) holds the tests. [test_deploy.sh](test_deploy.sh) builds a small Python image and runs them in it.

Each fixture is a complete case for the keys it tests. The test loads [deploy.py](../../deploy.py) from the
repository mount and mocks external commands and file writes.

Add a fixture for each configuration rule. Add its expected values in [test_render.py](test_render.py).
The fixtures in [fixtures/schema/](fixtures/schema) test the configuration schema and `./deploy --check`.
The `--check` tests set `INI_PATH` to a fixture, so they never read the operator `hoover4.ini`.
They replace each command, file write, folder creation and network call with a mock that fails the test.

The tests that read `hoover4.ini.release` or `hoover4.ini.development` read a copy without inline `;` comments.
