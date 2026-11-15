# Operate the zones of a cluster site

The k3s installation is experimental.

A zone is one tenant of the site. It has its own openDesk, its own Hoover installation and its own sign-in service.
Two roles work with a zone.

| Role | Signs in to | Tasks |
|---|---|---|
| Platform operator | The operator portal `https://operator.<domain>/` | Create, upgrade, back up, restore and delete zones. Change the settings of the site and the zones. |
| Zone administrator | The portal of the zone `https://<zone>-portal.<domain>/` | Manage the users and groups of the zone. |

The operator login and the zone logins are separate. An operator login gives no access to the data of a zone.

## Contents

- [Sign in to the operator portal](#sign-in-to-the-operator-portal)
- [Create a zone](#create-a-zone)
- [Give the zone to its administrator](#give-the-zone-to-its-administrator)
- [Change the applications and settings of a zone](#change-the-applications-and-settings-of-a-zone)
- [Recover from a failed operation](#recover-from-a-failed-operation)
- [Upgrade a zone](#upgrade-a-zone)
- [Back up and restore a zone](#back-up-and-restore-a-zone)
- [Delete a zone](#delete-a-zone)
- [Manage the users and groups of a zone](#manage-the-users-and-groups-of-a-zone)

## Sign in to the operator portal

1. Open `https://operator.<domain>/`.
2. Sign in with the operator account.
3. The start page shows the cluster resources, the links to Headlamp, Grafana, Prometheus and the settings, the zones, the operations and the recent warning events.

<a href="img/operator-home.png"><img src="img/operator-home.png" alt="The start page of the operator portal with the cluster use and the links to the tools" width="100%"></a>

Select **Sign out** at the end of the page to end the session.

## Create a zone

1. In **Create a zone**, type the zone name. A zone name is `zone-` followed by 1 to 12 lower-case letters or digits.
2. Select **Create the zone**.
3. Follow the operation in **Operations**. The table shows the steps and the last output lines. A create takes about 30 minutes.

<a href="img/operator-zones.png"><img src="img/operator-zones.png" alt="The zone list with its actions and the form to create a zone" width="100%"></a>

The cluster places each pod of the zone on the node with the lowest requested CPU per thread.
A pod with a volume stays on the node of its volume.

A create, upgrade or delete restarts the shared call services. Calls that run at that time end.

Each host of a zone is `<zone>-<app>.<domain>`, and the HTTPS frontend serves all of them.
A create stops at the step `frontend` with an error when the frontend does not answer for the zone portal. For example, the frontend is not installed.

1. Run `k3s/deploy-k3s up --site <file> --target <public node> --steps frontend` on the operator workstation.
2. Select **Run again**. The operation continues with the install.

The zone state in the cluster holds the zone. The site file names no zone. The storage names of the Hoover installation come from the zone name.
The operator workstation can create a zone with `python3 k3s/zones/zone.py apply <zone>`. [The cluster deployment reference](../../../k3s/Readme.md#create-and-delete-zones) gives the options.

## Give the zone to its administrator

1. In the zone list, select **Show the onboarding login** of the zone.
2. Give the portal address, the user name and the password to the administrator of the zone through a private channel.
3. Ask the administrator to change the password at the first sign-in.

## Change the applications and settings of a zone

1. Open **Settings**.
2. Select the scope of the zone. The settings `app.<name>` turn openDesk applications and Hoover off and on.
   An application that is off has no running pods and keeps its data.
3. Change the values and select **Save**. The page lists the saved changes that wait for Apply, and the services that each change restarts.
4. Select **Apply**. The page shows the steps of the operation.

<a href="img/settings-zone-apps.png"><img src="img/settings-zone-apps.png" alt="The application switches of a zone on the settings page" width="100%"></a>

A value that you save during a running operation waits for the next Apply.

## Recover from a failed operation

A zone operation or an Apply that fails keeps its finished steps.

1. Read the error and the last output lines of the operation.
2. Correct the cause. The private infrastructure log and [the troubleshooting guide](../Troubleshooting.md) help with known causes.
3. Select **Run again** for a zone operation, or **Retry** for an Apply. The operation continues at its first unfinished step.
4. Select **Abandon** to stop a failed Apply. Its unfinished scopes keep their earlier applied values.

The step `calls` stops when the cluster has no checked record of the host rule of the media node. The error names the record `coturn_peers`.
Run `k3s/deploy-k3s up --site <file> --target <control plane> --steps operator` on the operator workstation, then select **Run again**.

<a href="img/operator-operations.png"><img src="img/operator-operations.png" alt="The operations table with a failed zone upgrade and its Run again button" width="100%"></a>

## Upgrade a zone

Select **Upgrade the zone** in the zone list. The runner installs the revision of the last `deploy-k3s up --steps operator` on the zone.
A site upgrade with `k3s/deploy-k3s up` also upgrades every zone. [The operations manual](Cluster_Operations.md#upgrade-the-site) describes it.

## Back up and restore a zone

A zone copy holds the openDesk databases and volumes of the zone and the volumes of its Hoover installation.
The ClickHouse databases, Manticore tables and Garage buckets of a zone are in the shared stores of the site, so the zone copy does not hold them. The collection copies of the backup settings hold the ClickHouse and Garage data. `main.py reindex-collection` builds the Manticore tables of a collection again from ClickHouse. The workflow history of the zone is in the Temporal of the site, and no copy holds it.

1. Turn on `backup.opendesk.enabled` and set `backup.opendesk.copies` in the settings of the zone, and Apply.
2. The runner makes one copy each week. The zone closes during the copy and opens again with its earlier replicas.
3. Restore a copy from the operator host with `backups.py restore-zone`. [The operations manual](Cluster_Operations.md#restore-a-zone) describes the steps.

<a href="img/settings-zone-backup.png"><img src="img/settings-zone-backup.png" alt="The backup destination and the backup settings of a zone" width="100%"></a>

## Delete a zone

A delete removes the ClickHouse databases, users, Garage buckets and keys of the zone from the shared stores of the site, and the Temporal namespace of the zone from the Temporal of the site. It then removes the zone namespaces with all their volumes. No copy remains in the cluster.
The Hoover operations pod of the zone empties the Garage buckets. A disabled zone has no such pod, so its non-empty buckets and its Garage keys stay, and the operation log names them. Turn the zone on before the delete to remove them.

1. Make a zone copy first when the data must stay available.
2. Select **Delete the zone** in the zone list.
3. Type the zone name to confirm. The portal refuses another name.

## Manage the users and groups of a zone

The zone administrator does these tasks in the portal of the zone.

1. Sign in to `https://<zone>-portal.<domain>/` with the administrator account.
2. Open the user administration of the portal.
3. Add a user with a user name, a name and an email address, or change an existing user.
4. Add the user to groups. The group of the zone administrators gives the administrator rights in the applications.
5. The applications receive a changed user or group within a few minutes.
