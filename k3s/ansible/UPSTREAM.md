# Upstream of this folder

This folder is a vendored fork of `k3s-ansible`.

| Field | Value |
|---|---|
| Upstream | https://github.com/k3s-io/k3s-ansible |
| Tag | `1.2.2` |
| Commit | `165062c410ab8bd194a815d2cbd76f6d83755fd1` |
| License | Apache License 2.0, see [LICENSE](LICENSE) |

The upstream files are unchanged. The folder `.github` of the upstream repository is not copied.

The hoover4 files are additions:

- [hoover4.cfg](hoover4.cfg) is the Ansible configuration that `../deploy-k3s` uses. The upstream `ansible.cfg` stays unchanged and is not used.
- [requirements.yml](requirements.yml) pins the collections that the hoover4 roles use. The operator image installs them.
- [playbooks/hoover4-hosts.yml](playbooks/hoover4-hosts.yml), [playbooks/hoover4-k3s.yml](playbooks/hoover4-k3s.yml), [playbooks/hoover4-service.yml](playbooks/hoover4-service.yml) and [playbooks/hoover4-local.yml](playbooks/hoover4-local.yml).
- The roles `roles/hoover4_*`.

The site playbooks use the hoover4 roles for k3s, not the upstream roles `k3s_server` and `k3s_agent`.
The upstream roles write their own systemd unit with the token in its environment.
They have no token file, no conversion of a SQLite server to etcd and no runtime handlers for Kata Containers and gVisor.
The hoover4 role `hoover4_k3s` uses the k3s install script with these inputs instead.

To update the fork, copy the files of a new upstream tag over the upstream files and keep the hoover4 files.
Then change the tag and the commit above.
