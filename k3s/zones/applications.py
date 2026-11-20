"""The supported application profile of a zone: the applications that a zone runs, and the class of each entry, release
and image of the pinned openDesk release.

A zone runs Hoover, Nextcloud with document editing in Collabora, XWiki and Jitsi, with the identity stack, the portal
and the stores that they need. Notes, Element and Matrix chat, OpenProject, CryptPad and the Matrix widgets are retired.
The profile is the same for a new zone, a deploy-k3s up, an upgrade, the operator Apply and a restore. No operator
setting turns a retired application on (../platform/operator/settings.py).

Classes:
  retained  a release or image that a zone of the profile installs or can install.
  retired   a release or image of a retired application. The waves uninstall such a release when a zone still has it
            (zone.py install_entry()), and deploy-k3s reset removes its images from the nodes (../images/reclaim.py).
  off       a release or image that no zone of this site installs, for example mail and the enterprise components.
problems() names each entry, release or image key of the pinned release without a class, so a new openDesk release
stops the render until this file classifies it.
"""
import fnmatch
import hashlib
import json
import re
from pathlib import Path

# The applications of the operator settings app.<name> (../platform/operator/settings.py).
APPLICATIONS = ('nextcloud', 'collabora', 'jitsi', 'xwiki', 'hoover')
RETIRED_APPLICATIONS = ('notes', 'element', 'openproject', 'cryptpad')

# The values apps.<key>.enabled of the openDesk release. A key that this table does not name keeps the release default.
# zones.py writes these values, and it turns seaweedfs and postgresql off for a zone on the shared stores.
OPENDESK_APPS = {
    'nextcloud': True, 'collabora': True, 'jitsi': True, 'xwiki': True, 'nubus': True,
    'notes': False, 'element': False, 'elementAdmin': False, 'elementSupervision': False, 'elementAuditbot': False,
    'neoboard': False, 'openproject': False, 'cryptpad': False,
    'oxAppSuite': False, 'dovecot': False, 'postfix': False, 'clamavSimple': False, 'mariadb': False, 'home': False,
}

# The entries of helmfile-defaults.yaml.gotmpl and the class of each of their releases. The element entry also holds
# releases whose names its template builds (opendesk-element, opendesk-well-known, opendesk-synapse-web and
# opendesk-synapse), which the release marks as not installed.
RELEASES = {
    'opendesk-migrations-pre': {'opendesk-secrets': 'retained', 'opendesk-migrations-pre': 'retained'},
    'opendesk-services': {'opendesk-otterize': 'off', 'opendesk-home': 'off', 'opendesk-certificates': 'off',
                          'opendesk-trust': 'retained', 'opendesk-alerts': 'off', 'opendesk-dashboards': 'off',
                          'opendesk-static-files': 'retained'},
    'services-external': {'redis': 'retained', 'memcached': 'retained', 'postgresql': 'retained', 'mariadb': 'off',
                          'postfix': 'off', 'opendesk-dkimpy-milter': 'off', 'clamav': 'off', 'clamav-simple': 'off',
                          'minio': 'off', 'seaweedfs-config': 'retained', 'seaweedfs': 'retained', 'cassandra': 'off'},
    'nubus': {'nubus': 'off', 'ums': 'retained', 'intercom-service': 'retained', 'opendesk-keycloak-bootstrap': 'retained',
              'opendesk-provisioning-synapse': 'retired'},
    'open-xchange': {'open-xchange': 'off', 'opendesk-open-xchange-bootstrap': 'off', 'dovecot': 'off', 'postfix-ox': 'off',
                     'ox-connector': 'off'},
    'nextcloud': {'opendesk-nextcloud-management': 'retained', 'opendesk-nextcloud': 'retained',
                  'opendesk-nextcloud-notifypush': 'retained'},
    'collabora': {'collabora-controller': 'off', 'collabora-online': 'retained'},
    'cryptpad': {'cryptpad': 'retired'},
    'jitsi': {'jitsi': 'retained'},
    'element': {'opendesk-element-customization': 'retired', 'element': 'retired',
                'opendesk-matrix-user-verification-service-bootstrap': 'retired',
                'opendesk-matrix-user-verification-service': 'retired', 'matrix-neoboard-widget': 'retired',
                'matrix-neochoice-widget': 'retired', 'matrix-neodatefix-widget': 'retired',
                'matrix-neodatefix-bot-bootstrap': 'retired', 'matrix-neodatefix-bot': 'retired',
                'opendesk-element': 'retired', 'opendesk-well-known': 'retired', 'opendesk-synapse-web': 'retired',
                'opendesk-synapse': 'retired'},
    'neoboard': {'matrix-neoboard-standalone': 'retired'},
    'openproject': {'openproject': 'retired'},
    'xwiki': {'xwiki': 'retained'},
    'notes': {'impress': 'retired', 'impress-customization': 'retired'},
    'opendesk-openproject-bootstrap': {'opendesk-openproject-bootstrap': 'retired'},
    'opendesk-migrations-post': {'opendesk-migrations-post': 'retained'},
}

# The image keys of images.yaml.gotmpl of the release, by class.
RETIRED_IMAGES = (
    'cryptpad', 'elementAdmin', 'elementCustomization', 'elementPipe', 'elementWeb', 'matrixAuthenticationService',
    'matrixDex', 'matrixHaproxy', 'matrixHookshot', 'matrixLivekitServer', 'matrixSyn2Mas', 'matrixLkJwtService', 'matrixNeoBoardWidget',
    'matrixNeoChoiceWidget', 'matrixNeoDateFixBot', 'matrixNeoDateFixWidget', 'matrixSbg', 'matrixSygnal',
    'matrixTelemetry', 'matrixTools', 'matrixUserVerificationService', 'neoboard', 'notesBackend', 'notesDocspec',
    'notesFrontend', 'notesYProvider', 'openproject', 'openprojectBootstrap', 'openprojectDbInit', 'openprojectHocuspocus',
    'synapse', 'synapseCreateUser', 'synapseGuestModule', 'synapseProWorker', 'synapseS3StorageProvider',
)
OFF_IMAGES = (
    'cassandra', 'cassandraExporter', 'clamd', 'collaboraController', 'dkimpy', 'dovecot', 'dovecotBootstrap',
    'dovecotCassandra', 'freshclam', 'icap', 'jibri', 'jigasi', 'mariadb', 'milter', 'minio', 'nubusOxExtension',
    'openxchangeBootstrap', 'openxchangeCoreGuidedtours', 'openxchangeCoreMW', 'openxchangeCoreUI',
    'openxchangeCoreUIMiddleware', 'openxchangeCoreUserGuide', 'openxchangeDocumentConverter', 'openxchangeGotenberg',
    'openxchangeGuardUI', 'openxchangeImageConverter', 'openxchangeNextcloudIntegrationUI', 'openxchangePublicSectorUI',
    'oxConnector', 'postfix', 'postfixBootstrap', 'xwikiMariadb',
)
RETAINED_IMAGES = (
    'bitnamiOSShell', 'busybox', 'collabora', 'intercom', 'jicofo', 'jitsi', 'jitsiKeycloakAdapter', 'jitsiPatchJVB', 'jvb',
    'memcached', 'migrations', 'nextcloud', 'nextcloudExporter', 'nubusBlocklistCleanup', 'nubusDataLoader',
    'nubusKeycloak', 'nubusKeycloakBootstrap', 'nubusKeycloakExtensionHandler', 'nubusKeycloakExtensionProxy',
    'nubusLdapNotifier', 'nubusLdapServer', 'nubusLdapServerDhInitContainer', 'nubusLdapServerLeaderElector',
    'nubusLicenseImport', 'nubusNats', 'nubusNatsBox', 'nubusOpendeskExtension', 'nubusOpendeskExtensionA2gMapper', 'nubusPortalAssetLoader',
    'nubusPortalConsumer', 'nubusPortalExtension', 'nubusPortalFrontend', 'nubusPortalServer', 'nubusProvisioningApi',
    'nubusProvisioningDispatcher', 'nubusProvisioningPrefill', 'nubusProvisioningUdmListener',
    'nubusProvisioningUdmTransformer', 'nubusSelfServiceConsumer', 'nubusUdmRestApi', 'nubusUmcGateway', 'nubusUmcServer',
    'nubusUmcServerProxy', 'nubusWaitForDependency', 'opendeskKeycloakBootstrap', 'opendeskStaticFiles', 'opendeskTrust',
    'postgresql', 'prosody', 'provisioningConnector', 'redis', 'seaweedfs', 'xwikiPostgres',
)
# The repositories of retired images of earlier openDesk releases and of the earlier chat calls, which a node can keep
# in its cache without a pod (fnmatch patterns of the repository without tag and digest). A repository of a retained
# image of the pinned release never counts as retired.
RETIRED_REPOSITORIES = (
    '*/supplier/element/images-mirror/*', '*/supplier/openproject/images-mirror/*', '*/images-mirror/matrix-*',
    '*/images-mirror/impress-*', '*/images/opendesk-notes/*', '*/images-mirror/cryptpad', '*/images/synapse-*',
    '*/images/opendesk-openproject-bootstrap', '*/images/opendesk-element-*', '*/images/opendesk-matrix-*',
    'docker.io/livekit/*', 'livekit/*',
)
# The controller names of the retired applications (fnmatch patterns). postrender.py refuses a render that contains
# one, and the restore of an older backup leaves their parts out (../platform/backups/backups.py).
RETIRED_WORKLOADS = ('cryptpad*', 'element-*', 'matrix-*', 'opendesk-matrix-*', 'opendesk-provisioning-synapse*',
                     'opendesk-element-*', 'openproject-*', 'opendesk-openproject-*', 'impress-*', 'synapse-*',
                     'opendesk-synapse*', 'opendesk-well-known*', 'lk-jwt*', 'meetings-bot*', 'neoboard*')
# The operator settings of the retired applications. A saved value of one has no effect.
RETIRED_SETTINGS = tuple(f'app.{name}' for name in RETIRED_APPLICATIONS)
# The openDesk databases of the retired applications ({value key: database name}, postgresql.py DATABASES) and their
# buckets (objectstore.py BUCKETS).
RETIRED_DATABASES = {'matrixAuthenticationService': 'matrix_authentication', 'notes': 'notes', 'openproject': 'openproject',
                     'synapse': 'matrix'}
RETIRED_BUCKETS = ('notes', 'openproject', 'synapse')

ENTRY = re.compile(r'^\s*-\s*path:\s*"helmfile/apps/([^/"]+)/helmfile-defaults\.yaml\.gotmpl"', re.M)
IMAGE_KEY = re.compile(r'^  ([A-Za-z0-9]+):\s*$', re.M)
IMAGE_FIELD = re.compile(r'^    (registry|repository|tag):\s*"?([^"\n]*)"?\s*$', re.M)


def release_class(release):
    for releases in RELEASES.values():
        if release in releases:
            return releases[release]
    return None


def entry_class(entry):
    """retained when the entry has a retained release, else retired or off."""
    classes = set(RELEASES.get(entry, {}).values())
    if 'retained' in classes:
        return 'retained'
    return 'retired' if 'retired' in classes else 'off'


def retired_workload(name):
    return any(fnmatch.fnmatchcase(name, p) for p in RETIRED_WORKLOADS)


def retired_part(name):
    """True for a Secret, claim or workload of a retired application: the name, or a part of the name after a hyphen,
    matches RETIRED_WORKLOADS. A claim name holds its template name first, for example data-element-synapse-main-0."""
    return any(retired_workload(name[i:]) for i in range(len(name)) if i == 0 or name[i - 1] == '-')


def image_class(key):
    for name, keys in (('retained', RETAINED_IMAGES), ('retired', RETIRED_IMAGES), ('off', OFF_IMAGES)):
        if key in keys:
            return name
    return None


def release_images(opendesk):
    """{image key: 'registry/repository'} of images.yaml.gotmpl of an openDesk source folder."""
    text = (Path(opendesk) / 'helmfile/environments/default/images.yaml.gotmpl').read_text()
    body = re.split(r'(?m)^images:', text, maxsplit=1)[1]
    out = {}
    for block in re.split(r'(?m)^(?=  [A-Za-z0-9]+:\s*$)', body):
        key = IMAGE_KEY.match(block)
        if not key:
            continue
        fields = dict(IMAGE_FIELD.findall(block))
        out[key.group(1)] = f"{fields.get('registry', '')}/{fields.get('repository', '')}".strip('/')
    return out


def retired_repository(repository, retained_repositories=()):
    """True for the repository of a retired image. repository has no tag and no digest."""
    if repository in retained_repositories:
        return False
    return any(fnmatch.fnmatchcase(repository, p) for p in RETIRED_REPOSITORIES)


def repositories(opendesk):
    """{'retained': set, 'retired': set, 'off': set} of the repositories of the pinned release."""
    out = {'retained': set(), 'retired': set(), 'off': set()}
    for key, repository in release_images(opendesk).items():
        out[image_class(key) or 'off'].add(repository)
    return out


def problems(opendesk, entry_releases):
    """The entries, releases and image keys of an openDesk source folder that the profile does not classify.
    entry_releases(entry) gives the release names of one entry (zone.py entry_releases())."""
    out = []
    entries = ENTRY.findall((Path(opendesk) / 'helmfile-defaults.yaml.gotmpl').read_text())
    for entry in entries:
        if entry not in RELEASES:
            out.append(f'the openDesk entry {entry} has no class in zones/applications.py RELEASES')
            continue
        for release in entry_releases(entry):
            if release not in RELEASES[entry]:
                out.append(f'the openDesk release {release} of {entry} has no class in zones/applications.py RELEASES')
    for key in release_images(opendesk):
        if image_class(key) is None:
            out.append(f'the openDesk image {key} has no class in zones/applications.py')
    return out


def digest():
    """The SHA-256 of the profile. The zone inputs (zone.py) and the image pre-pull (../driver/deploy.py) include it."""
    data = {'applications': APPLICATIONS, 'retired': RETIRED_APPLICATIONS, 'apps': OPENDESK_APPS, 'releases': RELEASES,
            'images': [RETAINED_IMAGES, RETIRED_IMAGES, OFF_IMAGES], 'repositories': RETIRED_REPOSITORIES,
            'workloads': RETIRED_WORKLOADS}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
