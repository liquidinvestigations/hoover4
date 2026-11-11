# Deployment render tests

[test_render.py](test_render.py) holds the tests. [test_deploy.sh](test_deploy.sh) builds a small Python image and runs them in it.

Each fixture is a complete case for the keys it tests. The test loads [deploy.py](../../deploy.py) from the
repository mount and mocks external commands and file writes.

Add a fixture for each configuration rule. Add its expected values in [test_render.py](test_render.py).
The fixtures in [fixtures/schema/](fixtures/schema) test the configuration schema and `./deploy --check`.
The `--check` tests set `INI_PATH` to a fixture, so they never read the operator `hoover4.ini`.
They replace each command, file write, folder creation and network call with a mock that fails the test.

The tests read `hoover4.ini.release` and `hoover4.ini.development` directly.
The sample tests check that each section and key is in the schema of [deploy.py](../../deploy.py) and that no removed setting remains.
They check that each sample sets every key at its default or at a listed sample value.
They check that the samples differ only in the two development keys.
They also check the comment layout: full-line `#` comments, no `;` character, and at most one comment line above a key.
The `--check` tests copy each sample with `volumes_path` set.

[fixtures/schema/removed-model-settings.ini](fixtures/schema/removed-model-settings.ini) sets every removed model setting.
[fixtures/schema/retired-cloud-provider.ini](fixtures/schema/retired-cloud-provider.ini) is an earlier cloud-provider file.
[fixtures/schema/removed-service-settings.ini](fixtures/schema/removed-service-settings.ini) sets every removed service version, GPU model, provider, dataset and registry setting.
The tests check that each removed setting is refused with its replacement text.
[fixtures/source-ini/compose-with-serena.ini](fixtures/source-ini/compose-with-serena.ini) is a Compose source file with the removed Serena settings.
The tests check that the strict schema refuses it, and that the file without those keys keeps its storage, ports and dataset mounts.
The migration reader of the cluster port reads this source schema.
Another test checks that the MCP ports of `.agents/harnesses/mcp-servers.json` are the `deploy.py` port defaults.
The weight download tests write the download metadata of huggingface_hub into a temporary folder.
They cover a folder at the pinned commit, a folder at another commit, and an interrupted download.
