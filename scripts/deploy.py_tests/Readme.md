# Deployment render tests

`test_deploy.sh` builds a small Python image and runs the render tests in it.

Each fixture is a complete case for the keys it tests. The test loads `deploy.py` from the
repository mount and mocks external commands and file writes.

Add a fixture for each configuration rule. Add its expected values in `test_render.py`.
