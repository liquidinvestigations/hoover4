# Deployment render tests

[test_render.py](test_render.py) holds the tests. [test_deploy.sh](test_deploy.sh) builds a small Python image and runs them in it.

Each fixture is a complete case for the keys it tests. The test loads [deploy.py](../../deploy.py) from the
repository mount and mocks external commands and file writes.

Add a fixture for each configuration rule. Add its expected values in [test_render.py](test_render.py).
The fixtures in [fixtures/schema/](fixtures/schema) test the configuration schema and `./deploy --check`.
The `--check` tests set `INI_PATH` to a fixture, so they never read the operator `hoover4.ini`.
They replace each command, file write, folder creation and network call with a mock that fails the test.

The tests that read `hoover4.ini.release` or `hoover4.ini.development` read a copy without inline `;` comments.
The copy also omits each section and key of `REMOVED_SETTINGS` in [deploy.py](../../deploy.py).
A copy without a `[dataset_mount.<name>]` section receives `[dataset_mount.testdata]`, because deploy.py requires a mount section.

[fixtures/schema/removed-model-settings.ini](fixtures/schema/removed-model-settings.ini) sets every removed model setting.
[fixtures/schema/retired-cloud-provider.ini](fixtures/schema/retired-cloud-provider.ini) is an earlier cloud-provider file.
[fixtures/schema/removed-service-settings.ini](fixtures/schema/removed-service-settings.ini) sets every removed service version, GPU model, provider, dataset and registry setting.
The tests check that each removed setting is refused with its replacement text.
The weight download tests write the download metadata of huggingface_hub into a temporary folder.
They cover a folder at the pinned commit, a folder at another commit, and an interrupted download.
