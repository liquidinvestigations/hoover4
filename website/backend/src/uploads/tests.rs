//! Tests of the upload receiver with a fake clock, store, notifier, permission check and
//! free-space reader, on real file systems.
//!
//! A simulated crash is an armed failure point: the operation returns at that point and
//! leaves its files as a killed process leaves them. A new [`Service`] on the same
//! folders then plays the restarted website.

use std::collections::HashMap;
use std::os::fd::BorrowedFd;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use common::uploads::{BeginFile, BeginRequest, UploadLimits};

use super::fsutil::{self, Faults};
use super::journal::{self, batch_state, FileState, Space};
use super::transfer::BodyEnd;
use super::*;
use crate::dataset_mounts::DatasetMount;

const USER: &str = "alice";
const COLLECTION: &str = "press";
const DATASET: &str = "press_inbox";
const HOUR: i64 = 3_600_000;
/// The lock wait of the test receivers.
const TEST_LOCK_WAIT: std::time::Duration = std::time::Duration::from_millis(1500);

struct FakeClock(AtomicI64);

impl Clock for FakeClock {
    fn now_ms(&self) -> i64 {
        self.0.load(Ordering::SeqCst)
    }
}

#[derive(Default)]
struct MemStore {
    batches: Mutex<Vec<BatchRecord>>,
    files: Mutex<Vec<FileRecord>>,
    /// The inserts of each table.
    batch_inserts: AtomicU64,
    file_inserts: AtomicU64,
    claimed: Mutex<HashMap<String, String>>,
    fail: AtomicBool,
    deleted: AtomicBool,
    removal_live: AtomicBool,
    removal_id: Mutex<String>,
}

impl MemStore {
    fn latest_batch(&self, batch_id: &str) -> Option<BatchRecord> {
        let rows = self.batches.lock().unwrap();
        let mut best: Option<BatchRecord> = None;
        for row in rows.iter().filter(|r| r.batch_id == batch_id) {
            if best.as_ref().is_none_or(|b| row.row_version >= b.row_version) {
                best = Some(row.clone());
            }
        }
        best
    }

    fn latest_file(&self, batch_id: &str, file_no: u32) -> Option<FileRecord> {
        let rows = self.files.lock().unwrap();
        let mut best: Option<FileRecord> = None;
        for row in rows.iter().filter(|r| r.batch_id == batch_id && r.file_no == file_no) {
            if best.as_ref().is_none_or(|b| row.row_version >= b.row_version) {
                best = Some(row.clone());
            }
        }
        best
    }

    fn batch_ids(&self) -> Vec<String> {
        let mut ids: Vec<String> = self.batches.lock().unwrap().iter().map(|r| r.batch_id.clone()).collect();
        ids.sort();
        ids.dedup();
        ids
    }
}

impl BatchStore for MemStore {
    fn write_batch(&self, _collection: &str, row: &BatchRecord) -> anyhow::Result<()> {
        if self.fail.load(Ordering::SeqCst) {
            anyhow::bail!("the store is down");
        }
        self.batches.lock().unwrap().push(row.clone());
        self.batch_inserts.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }

    fn write_files(&self, _collection: &str, rows: &[FileRecord]) -> anyhow::Result<()> {
        if self.fail.load(Ordering::SeqCst) {
            anyhow::bail!("the store is down");
        }
        self.files.lock().unwrap().extend(rows.iter().cloned());
        self.file_inserts.fetch_add(1, Ordering::SeqCst);
        Ok(())
    }

    fn batch_state(&self, _collection: &str, _dataset: &str, batch_id: &str) -> anyhow::Result<Option<String>> {
        if let Some(state) = self.claimed.lock().unwrap().get(batch_id) {
            return Ok(Some(state.clone()));
        }
        Ok(self.latest_batch(batch_id).map(|b| b.state))
    }

    fn dataset_live(&self, _dataset: &str) -> anyhow::Result<bool> {
        Ok(!self.deleted.load(Ordering::SeqCst))
    }

    fn latest_dataset_removal(&self, _dataset: &str) -> anyhow::Result<String> {
        Ok(self.removal_id.lock().unwrap().clone())
    }

    fn dataset_removal_live(&self, _dataset: &str) -> anyhow::Result<bool> {
        Ok(self.removal_live.load(Ordering::SeqCst))
    }
}

#[derive(Default)]
struct FakeNotifier {
    calls: Mutex<Vec<(String, String)>>,
}

impl QueueNotifier for FakeNotifier {
    fn notify(&self, _collection: &str, dataset: &str, batch_id: &str) -> anyhow::Result<()> {
        self.calls.lock().unwrap().push((dataset.to_string(), batch_id.to_string()));
        Ok(())
    }
}

struct FakeAccess {
    target: Mutex<TargetLookup>,
}

impl UploadAccess for FakeAccess {
    fn target(&self, username: &str, collection: &str, dataset: &str) -> anyhow::Result<TargetLookup> {
        if username != USER || collection != COLLECTION || dataset != DATASET {
            return Ok(TargetLookup::None);
        }
        Ok(self.target.lock().unwrap().clone())
    }
}

struct FakeFree(AtomicU64);

impl FreeSpace for FakeFree {
    fn free_bytes(&self, _dir: BorrowedFd<'_>) -> anyhow::Result<u64> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

/// The folders and fakes of one test. [`Env::service`] gives a new receiver on them.
struct Env {
    dirs: Vec<PathBuf>,
    space: PathBuf,
    dataset: PathBuf,
    clock: Arc<FakeClock>,
    store: Arc<MemStore>,
    notifier: Arc<FakeNotifier>,
    access: Arc<FakeAccess>,
    free: Arc<FakeFree>,
    limits: UploadLimits,
}

fn scratch(base: &Path, label: &str) -> PathBuf {
    let dir = base.join(format!("hoover4-upload-test-{label}-{}-{}", std::process::id(), random_id()));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

impl Env {
    /// With `cross_device` the upload space is on `/dev/shm` and the dataset is in the
    /// temporary folder, which are different file systems in the website container.
    fn new(cross_device: bool) -> Env {
        let mount_root = scratch(&std::env::temp_dir(), "mount");
        let space_base = if cross_device { PathBuf::from("/dev/shm") } else { mount_root.clone() };
        let space = scratch(&space_base, "space");
        let dataset = mount_root.join("press_inbox");
        std::fs::create_dir(&dataset).unwrap();
        let space_dev = std::fs::metadata(&space).unwrap().dev();
        let dataset_dev = std::fs::metadata(&dataset).unwrap().dev();
        assert_eq!(cross_device, space_dev != dataset_dev, "space dev {space_dev}, dataset dev {dataset_dev}");
        let target = Target {
            collection: COLLECTION.to_string(),
            upload_dataset: DATASET.to_string(),
            dataset_path: dataset.to_str().unwrap().to_string(),
            mount: DatasetMount { name: "up".to_string(), path: mount_root.to_str().unwrap().to_string(), writable: true },
        };
        let mut dirs = vec![mount_root];
        if cross_device {
            dirs.push(space.clone());
        }
        Env {
            dirs,
            space,
            dataset,
            clock: Arc::new(FakeClock(AtomicI64::new(1_790_000_000_000))),
            store: Arc::new(MemStore::default()),
            notifier: Arc::new(FakeNotifier::default()),
            access: Arc::new(FakeAccess { target: Mutex::new(TargetLookup::Target(target)) }),
            free: Arc::new(FakeFree(AtomicU64::new(u64::MAX))),
            limits: UploadLimits { chunk_bytes: 8, abandon_hours: 24, ..Default::default() },
        }
    }

    fn service(&self) -> Arc<Service> {
        let service = Service {
            space: Space { root: self.space.clone() },
            limits: self.limits.clone(),
            clock: self.clock.clone(),
            store: self.store.clone(),
            notifier: self.notifier.clone(),
            access: self.access.clone(),
            free_space: self.free.clone(),
            faults: Faults::default(),
            lock_wait: TEST_LOCK_WAIT,
            rows: RowQueue::default(),
        };
        service.prepare_space().unwrap();
        Arc::new(service)
    }

    fn advance(&self, ms: i64) {
        self.clock.0.fetch_add(ms, Ordering::SeqCst);
    }

    fn revoke(&self) {
        *self.access.target.lock().unwrap() = TargetLookup::None;
    }
}

impl Drop for Env {
    fn drop(&mut self) {
        for dir in &self.dirs {
            let _ = std::fs::remove_dir_all(dir);
        }
    }
}

fn request(id: &str, files: &[(&str, u64)]) -> BeginRequest {
    BeginRequest {
        request_id: id.to_string(),
        collection: COLLECTION.to_string(),
        dataset: DATASET.to_string(),
        folder: "/in".to_string(),
        files: files
            .iter()
            .map(|(p, s)| BeginFile { path: p.to_string(), size: *s, last_modified_ms: Some(1_700_000_000_000) })
            .collect(),
    }
}

/// The content of file `n` of a test batch: `size` bytes that depend on `n`.
fn content(n: u32, size: u64) -> Vec<u8> {
    (0..size).map(|i| (i as u32 * 7 + n * 13) as u8).collect()
}

/// Send the rest of one file from its acknowledged offset, in chunks of the limit.
fn send_file(service: &Arc<Service>, batch_id: &str, file_no: u32, bytes: &[u8]) -> UploadResult<()> {
    let info = service.tus_create(USER, batch_id, file_no, bytes.len() as u64)?;
    let mut offset = info.offset;
    let mut complete = info.complete;
    while offset < bytes.len() as u64 {
        let end = (offset + service.limits.chunk_bytes).min(bytes.len() as u64);
        let mut session = service.tus_patch_open(USER, batch_id, file_no, offset, Some(end - offset))?;
        assert!(session.write(&bytes[offset as usize..end as usize])?);
        let info = session.finish(BodyEnd::Complete)?;
        offset = info.offset;
        complete = info.complete;
    }
    if complete {
        service.place_after_transfer(batch_id, file_no)?;
    }
    Ok(())
}

/// The whole client and server flow of one batch. Every step is safe to repeat.
fn run_flow(service: &Arc<Service>, files: &[(&str, u64)]) -> UploadResult<String> {
    let begun = service.begin(USER, &request("flow-1", files))?;
    for (n, (_, size)) in files.iter().enumerate() {
        match send_file(service, &begun.batch_id, n as u32, &content(n as u32, *size)) {
            Ok(()) => {}
            Err(e) if e.status == 409 && e.message == common::uploads::ENDED_MESSAGE => {}
            Err(e) => return Err(e),
        }
    }
    service.commit(USER, &begun.batch_id)?;
    service.finish(&begun.batch_id)?;
    Ok(begun.batch_id)
}

fn read_dest(env: &Env, path: &str) -> Option<Vec<u8>> {
    std::fs::read(env.dataset.join(path.trim_start_matches('/'))).ok()
}

/// Every entry beneath a folder, as paths relative to it.
fn tree(dir: &Path) -> Vec<String> {
    let mut out = Vec::new();
    fn walk(base: &Path, dir: &Path, out: &mut Vec<String>) {
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                out.push(path.strip_prefix(base).unwrap().to_string_lossy().to_string());
                if entry.file_type().unwrap().is_dir() {
                    walk(base, &path, out);
                }
            }
        }
    }
    walk(dir, dir, &mut out);
    out.sort();
    out
}

#[test]
fn begin_refuses_each_problem_class_with_its_message() {
    let env = Env::new(false);
    let service = env.service();
    let limits = UploadLimits { max_batch_files: 2, max_batch_bytes: 100, max_file_bytes: 60, ..env.limits.clone() };
    let strict = Service { limits, ..Arc::try_unwrap(env.service()).ok().unwrap() };

    let e = strict.begin(USER, &request("r1", &[("a", 1), ("b", 1), ("c", 1)])).unwrap_err();
    assert_eq!(e.status, 400);
    assert_eq!(e.refusal.unwrap().batch_problems, vec!["This upload has 3 files. The limit is 2."]);
    let e = strict.begin(USER, &request("r1", &[("a", 70), ("b", 50)])).unwrap_err();
    let refusal = e.refusal.unwrap();
    assert_eq!(refusal.batch_problems, vec!["This upload has 120 B. The limit is 100 B."]);
    assert_eq!(refusal.problems[0].message, "Larger than 60 B.");

    let e = service.begin(USER, &request("r2", &[("ok", 1), ("bad\u{1}", 1), ("x/../y", 1), ("ok", 1)])).unwrap_err();
    let problems: Vec<String> = e.refusal.unwrap().problems.into_iter().map(|p| p.message).collect();
    assert_eq!(problems, vec!["The name holds a control character.", "A name in the path is . or ..", "Selected twice."]);

    std::fs::create_dir_all(env.dataset.join("in/existing-folder")).unwrap();
    std::fs::write(env.dataset.join("in/existing.txt"), b"x").unwrap();
    std::fs::write(env.dataset.join("in/file-as-folder"), b"x").unwrap();
    let e = service
        .begin(USER, &request("r3", &[("existing.txt", 1), ("existing-folder", 1), ("file-as-folder/sub", 1), ("new", 1)]))
        .unwrap_err();
    assert_eq!(e.status, 409);
    let refusal = e.refusal.unwrap();
    assert_eq!(refusal.message, common::uploads::COLLISIONS_MESSAGE);
    assert_eq!(refusal.collisions, vec!["/in/existing.txt", "/in/existing-folder", "/in/file-as-folder/sub"]);

    // A live batch reserves `a`, so `a/b` conflicts, and the reverse.
    service.begin(USER, &request("r4", &[("a", 1)])).unwrap();
    assert_eq!(service.begin(USER, &request("r5", &[("a/b", 1)])).unwrap_err().refusal.unwrap().collisions, vec!["/in/a/b"]);
    service.begin(USER, &request("r6", &[("c/d", 1)])).unwrap();
    assert_eq!(service.begin(USER, &request("r7", &[("c", 1)])).unwrap_err().refusal.unwrap().collisions, vec!["/in/c"]);

    env.free.0.store(10, Ordering::SeqCst);
    let e = service.begin(USER, &request("r8", &[("big", 2048)])).unwrap_err();
    assert_eq!(e.status, 507);
    assert_eq!(e.message, "The server has 10 B free for uploads. This upload needs 2 KiB.");
    env.free.0.store(u64::MAX, Ordering::SeqCst);

    // Another dataset of the collection is a separate target, and an empty one is refused.
    let other = BeginRequest { dataset: "press_other".to_string(), ..request("r9", &[("z", 1)]) };
    assert_eq!(service.begin(USER, &other).unwrap_err().status, 403);
    let none = BeginRequest { dataset: String::new(), ..request("r9", &[("z", 1)]) };
    let refused = service.begin(USER, &none).unwrap_err();
    assert_eq!((refused.status, refused.message.as_str()), (400, "Select the dataset to upload into."));
    env.revoke();
    assert_eq!(service.begin(USER, &request("r9", &[("z", 1)])).unwrap_err().status, 403);
    assert_eq!(service.begin(USER, &request("bad id!", &[("z", 1)])).unwrap_err().status, 400);
}

#[test]
fn a_repeated_request_id_returns_one_complete_manifest_and_a_change_is_refused() {
    let env = Env::new(false);
    let service = env.service();
    let first = service.begin(USER, &request("same", &[("a", 3), ("b/c", 4)])).unwrap();
    let again = service.begin(USER, &request("same", &[("a", 3), ("b/c", 4)])).unwrap();
    assert_eq!(first, again);
    assert_eq!(env.store.batch_ids(), vec![first.batch_id.clone()]);
    let e = service.begin(USER, &request("same", &[("a", 3), ("b/c", 5)])).unwrap_err();
    assert_eq!((e.status, e.message.as_str()), (409, common::uploads::REQUEST_ID_REUSED_MESSAGE));
    // The begin rows: two file rows of version 1 and one batch row of version 1.
    assert_eq!(env.store.files.lock().unwrap().len(), 2);
    assert_eq!(env.store.latest_batch(&first.batch_id).unwrap().state, batch_state::UPLOADING);
}

#[test]
fn concurrent_begins_leave_one_acceptance() {
    let env = Env::new(false);
    let service = env.service();
    let run = |requests: Vec<BeginRequest>| -> Vec<UploadResult<String>> {
        std::thread::scope(|scope| {
            let handles: Vec<_> = requests
                .into_iter()
                .map(|r| {
                    let service = service.clone();
                    scope.spawn(move || service.begin(USER, &r).map(|b| b.batch_id))
                })
                .collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        })
    };
    let same_paths = run((0..8).map(|i| request(&format!("p{i}"), &[("same.txt", 1)])).collect());
    assert_eq!(same_paths.iter().filter(|r| r.is_ok()).count(), 1);
    assert!(same_paths.iter().filter_map(|r| r.as_ref().err()).all(|e| e.status == 409));

    let ancestors = run(vec![request("q1", &[("x", 1)]), request("q2", &[("x/y", 1)]), request("q3", &[("x/y/z", 1)])]);
    assert_eq!(ancestors.iter().filter(|r| r.is_ok()).count(), 1);

    let same_id = run((0..8).map(|_| request("one-id", &[("other.txt", 1)])).collect());
    let ids: Vec<&String> = same_id.iter().map(|r| r.as_ref().unwrap()).collect();
    assert!(ids.iter().all(|id| *id == ids[0]));
    assert_eq!(journal::list_names(&service.space.batches()).unwrap().len(), 3);
}

#[test]
fn the_tus_operations_follow_the_protocol_rules() {
    let env = Env::new(false);
    let service = env.service();
    let begun = service.begin(USER, &request("tus", &[("a.bin", 20), ("empty", 0), ("c.bin", 5)])).unwrap();
    let id = begun.batch_id.as_str();

    // Creation: a wrong length is refused. A repeat keeps the bytes.
    assert_eq!(service.tus_create(USER, id, 0, 19).unwrap_err().status, 400);
    let info = service.tus_create(USER, id, 0, 20).unwrap();
    assert_eq!((info.offset, info.length, info.complete), (0, 20, false));
    assert_eq!(info.expires_ms, env.clock.now_ms() + 24 * HOUR);
    let mut s = service.tus_patch_open(USER, id, 0, 0, Some(8)).unwrap();
    assert!(s.write(&content(0, 8)).unwrap());
    assert_eq!(s.finish(BodyEnd::Complete).unwrap().offset, 8);
    assert_eq!(service.tus_create(USER, id, 0, 20).unwrap().offset, 8);

    // A zero-byte file is complete at creation.
    assert!(service.tus_create(USER, id, 1, 0).unwrap().complete);

    // A wrong offset is a 409 and appends nothing.
    assert_eq!(service.tus_patch_open(USER, id, 0, 4, Some(4)).err().unwrap().status, 409);
    assert_eq!(std::fs::metadata(service.space.data(id, 0)).unwrap().len(), 8);

    // A declared length above the chunk or the file is refused before a byte is read.
    assert_eq!(service.tus_patch_open(USER, id, 0, 8, Some(9)).err().unwrap().status, 413);
    // A chunked body that passes the limit keeps nothing of the request.
    let mut s = service.tus_patch_open(USER, id, 0, 8, None).unwrap();
    assert!(s.write(&content(0, 20)[8..14]).unwrap());
    assert!(!s.write(&content(0, 20)[14..20]).unwrap());
    assert_eq!(s.finish(BodyEnd::Overflow).unwrap_err().status, 413);
    assert_eq!(service.tus_head(USER, id, 0).unwrap().offset, 8);
    assert_eq!(std::fs::metadata(service.space.data(id, 0)).unwrap().len(), 8);

    // An interrupted body keeps its synchronized prefix.
    let mut s = service.tus_patch_open(USER, id, 0, 8, None).unwrap();
    assert!(s.write(&content(0, 20)[8..11]).unwrap());
    assert_eq!(s.finish(BodyEnd::Interrupted).unwrap().offset, 11);
    // A killed writer leaves unacknowledged bytes, which HEAD removes.
    let mut s = service.tus_patch_open(USER, id, 0, 11, None).unwrap();
    assert!(s.write(&content(0, 20)[11..15]).unwrap());
    drop(s);
    assert_eq!(std::fs::metadata(service.space.data(id, 0)).unwrap().len(), 15);
    assert_eq!(service.tus_head(USER, id, 0).unwrap().offset, 11);
    assert_eq!(std::fs::metadata(service.space.data(id, 0)).unwrap().len(), 11);

    // Another user gets 403 on every operation.
    assert_eq!(service.tus_head("mallory", id, 0).unwrap_err().status, 403);
    assert_eq!(service.tus_patch_open("mallory", id, 0, 11, None).err().unwrap().status, 403);
    assert_eq!(service.tus_terminate("mallory", id, 0).unwrap_err().status, 403);
    assert_eq!(service.prefix_digest("mallory", id, 0).unwrap_err().status, 403);
    assert_eq!(service.commit("mallory", id).unwrap_err().status, 403);

    // The prefix digest is the SHA-256 of the acknowledged bytes.
    let digest = service.prefix_digest(USER, id, 0).unwrap();
    assert_eq!((digest.offset, digest.sha256), (11, sha256_hex(&content(0, 20)[..11])));

    // DELETE waits for an active PATCH, then ends the transfer.
    let s = service.tus_patch_open(USER, id, 2, 0, Some(5)).unwrap();
    let deleter = {
        let service = service.clone();
        let id = id.to_string();
        std::thread::spawn(move || {
            let result = service.tus_terminate(USER, &id, 2);
            (result.is_ok(), std::time::Instant::now())
        })
    };
    std::thread::sleep(std::time::Duration::from_millis(200));
    let mut s = s;
    assert!(s.write(&content(2, 5)[..3]).unwrap());
    let finished_at = std::time::Instant::now();
    assert_eq!(s.finish(BodyEnd::Complete).unwrap().offset, 3);
    let (deleted, deleted_at) = deleter.join().unwrap();
    assert!(deleted && deleted_at >= finished_at);
    assert_eq!(service.tus_create(USER, id, 2, 5).unwrap_err().status, 410);
    assert_eq!(service.tus_head(USER, id, 2).unwrap_err().status, 410);
    assert!(!service.space.data(id, 2).exists());

    // HEAD of a placed file reports the full length.
    service.place_after_transfer(id, 1).unwrap();
    assert_eq!(read_dest(&env, "/in/empty").unwrap(), Vec::<u8>::new());
    let head = service.tus_head(USER, id, 1).unwrap();
    assert_eq!((head.offset, head.length), (0, 0));
}

#[test]
fn expiry_follows_journal_activity_on_a_fake_clock() {
    let env = Env::new(false);
    let service = env.service();
    let begun = service.begin(USER, &request("exp", &[("a", 16), ("b", 16)])).unwrap();
    let id = begun.batch_id.as_str();
    send_file(&service, id, 0, &content(0, 16)).unwrap();
    let mut s = service.tus_patch_open(USER, id, 1, 0, Some(8)).unwrap();
    s.write(&content(1, 8)).unwrap();
    s.finish(BodyEnd::Complete).unwrap();

    // The batch row is 29 hours old, but a chunk arrived one hour ago.
    env.advance(28 * HOUR);
    let mut s = service.tus_patch_open(USER, id, 1, 8, Some(4)).unwrap();
    s.write(&content(1, 16)[8..12]).unwrap();
    let info = s.finish(BodyEnd::Complete).unwrap();
    assert_eq!(info.expires_ms, env.clock.now_ms() + 24 * HOUR);
    env.advance(HOUR);
    assert_eq!(service.sweep(false).unwrap().outcomes, vec![(id.to_string(), commit::SweepOutcome::Uploading)]);
    assert_eq!(env.store.latest_batch(id).unwrap().last_write_ms, env.clock.now_ms() - HOUR);

    // 25 hours without a chunk: the sweep commits the batch as a stop.
    env.advance(24 * HOUR);
    assert_eq!(service.sweep(false).unwrap().outcomes, vec![(id.to_string(), commit::SweepOutcome::Stopped)]);
    assert_eq!(env.store.latest_batch(id).unwrap().state, batch_state::QUEUED);
    assert_eq!(env.store.latest_file(id, 0).unwrap().state, "placed");
    assert_eq!(env.store.latest_file(id, 1).unwrap().state, "not_sent");
    assert!(!service.space.data(id, 1).exists());
    assert_eq!(service.tus_patch_open(USER, id, 1, 12, Some(4)).err().unwrap().status, 409);
    assert_eq!(env.notifier.calls.lock().unwrap().clone(), vec![(DATASET.to_string(), id.to_string())]);
}

fn device_of(path: &Path) -> u64 {
    std::fs::metadata(path).unwrap().dev()
}

#[test]
fn placement_renames_on_one_device_and_copies_across_devices() {
    for cross in [false, true] {
        let env = Env::new(cross);
        let service = env.service();
        let long_name = "n".repeat(255);
        let begun = service.begin(USER, &request("place", &[("deep/a.txt", 12), (&long_name, 3)])).unwrap();
        let id = begun.batch_id.as_str();
        let mut s = service.tus_patch_open(USER, id, 0, 0, Some(8)).unwrap();
        s.write(&content(0, 8)).unwrap();
        s.finish(BodyEnd::Complete).unwrap();
        let data_ino = std::fs::metadata(service.space.data(id, 0)).unwrap().ino();
        send_file(&service, id, 0, &content(0, 12)).unwrap();
        send_file(&service, id, 1, &content(1, 3)).unwrap();
        let dest = env.dataset.join("in/deep/a.txt");
        assert_eq!(std::fs::read(&dest).unwrap(), content(0, 12));
        assert_eq!(read_dest(&env, &format!("/in/{long_name}")).unwrap(), content(1, 3));
        let meta = std::fs::metadata(&dest).unwrap();
        assert_eq!(meta.mtime(), 1_700_000_000);
        eprintln!(
            "placement cross_device={cross}: upload space dev {}, dataset dev {}, data inode {data_ino}, destination inode {}",
            device_of(&env.space),
            device_of(&env.dataset),
            meta.ino()
        );
        assert_eq!(cross, meta.ino() != data_ino);
        let file = journal::read_file(&service.space, &journal::read_manifest(&service.space, id).unwrap().unwrap(), 0).unwrap();
        let method = file.placement.unwrap().method;
        assert_eq!(method, if cross { journal::PlaceMethod::Copy } else { journal::PlaceMethod::Rename });
        assert!(tree(&env.dataset).iter().all(|p| !p.contains(".hoover4-part")), "{:?}", tree(&env.dataset));
        assert!(!service.space.data(id, 0).exists());
    }
}

#[test]
fn placement_never_replaces_a_destination_and_refuses_a_link() {
    for cross in [false, true] {
        let env = Env::new(cross);
        let service = env.service();
        let begun = service.begin(USER, &request("keep", &[("taken.txt", 4), ("sub/linked.txt", 4)])).unwrap();
        let id = begun.batch_id.as_str();
        // Entries that appear after begin, outside the upload routes.
        std::fs::create_dir_all(env.dataset.join("in")).unwrap();
        std::fs::write(env.dataset.join("in/taken.txt"), b"theirs").unwrap();
        let outside = scratch(&std::env::temp_dir(), "outside");
        std::os::unix::fs::symlink(&outside, env.dataset.join("in/sub")).unwrap();

        send_file(&service, id, 0, &content(0, 4)).unwrap();
        send_file(&service, id, 1, &content(1, 4)).unwrap();
        assert_eq!(std::fs::read(env.dataset.join("in/taken.txt")).unwrap(), b"theirs");
        assert!(std::fs::read_dir(&outside).unwrap().next().is_none(), "the link target stays empty");
        let manifest = journal::read_manifest(&service.space, id).unwrap().unwrap();
        for n in 0..2 {
            let file = journal::read_file(&service.space, &manifest, n).unwrap();
            assert_eq!((file.state, file.error.as_str()), (FileState::Rejected, common::uploads::PATH_EXISTS_MESSAGE));
            assert!(!service.space.data(id, n).exists());
        }
        assert!(tree(&env.dataset).iter().all(|p| !p.contains(".hoover4-part")));
        service.commit(USER, id).unwrap();
        service.finish(id).unwrap();
        assert_eq!(env.store.latest_batch(id).unwrap().state, batch_state::CANCELLED);
        let _ = std::fs::remove_dir_all(outside);
    }
}

#[test]
fn permission_removal_stops_new_bytes_and_placement_and_keeps_placed_files() {
    let env = Env::new(false);
    let service = env.service();
    let begun = service.begin(USER, &request("rev", &[("a", 4), ("b", 4), ("c", 8)])).unwrap();
    let id = begun.batch_id.as_str();
    send_file(&service, id, 0, &content(0, 4)).unwrap();
    // File b completes while a placement would fail, so it stays staged.
    let mut s = service.tus_patch_open(USER, id, 1, 0, Some(4)).unwrap();
    s.write(&content(1, 4)).unwrap();
    assert!(s.finish(BodyEnd::Complete).unwrap().complete);
    let mut s = service.tus_patch_open(USER, id, 2, 0, Some(4)).unwrap();
    s.write(&content(2, 4)).unwrap();
    s.finish(BodyEnd::Complete).unwrap();

    env.revoke();
    service.place_after_transfer(id, 1).unwrap();
    assert!(read_dest(&env, "/in/b").is_none());
    assert_eq!(service.tus_patch_open(USER, id, 2, 4, Some(4)).err().unwrap().message, common::uploads::NO_PERMISSION_MESSAGE);
    assert_eq!(service.commit(USER, id).unwrap_err().status, 403);
    // Reads do not need a writable target.
    assert_eq!(service.tus_head(USER, id, 2).unwrap().offset, 4);

    env.advance(25 * HOUR);
    service.sweep(false).unwrap();
    assert_eq!(read_dest(&env, "/in/a").unwrap(), content(0, 4));
    assert!(read_dest(&env, "/in/b").is_none());
    let b = env.store.latest_file(id, 1).unwrap();
    assert_eq!((b.state.as_str(), b.error.as_str()), ("rejected", common::uploads::NO_PERMISSION_MESSAGE));
    assert_eq!(env.store.latest_file(id, 2).unwrap().state, "not_sent");
    assert!(!service.space.data(id, 1).exists() && !service.space.data(id, 2).exists());
    assert_eq!(env.store.latest_batch(id).unwrap().state, batch_state::QUEUED);
}

#[test]
fn the_sweep_skips_an_active_copy_and_removes_only_proven_data() {
    let env = Env::new(true);
    let service = env.service();
    let begun = service.begin(USER, &request("busy", &[("a", 4)])).unwrap();
    let id = begun.batch_id.clone();
    // A placement in progress holds the shared batch lock and the file lock.
    let batch_lock = fsutil::lock(&service.space.batch_lock(&id), false, true).unwrap();
    let file_lock = fsutil::lock(&service.space.file_lock(&id, 0), true, true).unwrap();
    env.advance(100 * HOUR);
    assert_eq!(service.sweep(false).unwrap().outcomes, vec![(id.clone(), commit::SweepOutcome::Busy)]);
    assert!(service.space.batch_journal(&id).exists());
    drop((batch_lock, file_lock));

    // An unanswered begin (no request record) is removed with its marker. A batch folder
    // without a journal is removed.
    let unanswered = env.service();
    unanswered.faults.arm("begin.request.before_rename");
    assert!(unanswered.begin(USER, &request("lost", &[("z", 1)])).is_err());
    std::fs::create_dir_all(service.space.files_dir(&random_id())).unwrap();
    let report = service.sweep(true).unwrap();
    let removed = report.outcomes.iter().filter(|(_, o)| *o == commit::SweepOutcome::Removed).count();
    assert_eq!(removed, 2, "{report}");
    assert_eq!(journal::live_batches(&service.space, DATASET).unwrap(), Vec::<String>::new());
    // The abandoned batch was committed with no file, and the next sweep archives it.
    service.sweep(false).unwrap();
    assert!(service.space.done_record(&id).exists());
    assert_eq!(env.store.latest_batch(&id).unwrap().state, batch_state::CANCELLED);
}

#[test]
fn queued_batches_are_signalled_until_claimed_and_then_archived() {
    let env = Env::new(false);
    let service = env.service();
    let id = run_flow(&service, &[("a", 3)]).unwrap();
    assert_eq!(env.notifier.calls.lock().unwrap().len(), 1);
    service.sweep(false).unwrap();
    assert_eq!(env.notifier.calls.lock().unwrap().len(), 2);
    env.store.claimed.lock().unwrap().insert(id.clone(), "ingesting".to_string());
    assert_eq!(service.sweep(false).unwrap().outcomes, vec![(id.clone(), commit::SweepOutcome::Archived)]);
    assert!(!service.space.batch_dir(&id).exists());
    // A repeated commit after the archive gives the same detail address.
    let again = service.commit(USER, &id).unwrap();
    assert_eq!(again.detail, detail_address(COLLECTION, &id));
    assert_eq!(service.tus_head(USER, &id, 0).unwrap_err().status, 410);
    assert_eq!(service.commit("mallory", &id).unwrap_err().status, 403);
}

/// The failure points of one flow, in order. A `.before_rename` point stops after the
/// temporary file is synchronized and before the rename. A `.before_sync` point stops
/// after the rename and before the folder synchronization.
const CRASH_POINTS: &[&str] = &[
    "begin.manifest.before_rename",
    "begin.manifest.before_sync",
    "begin.batch.before_rename",
    "begin.live_marker",
    "begin.request.before_rename",
    "begin.request.before_sync",
    "begin.files_written",
    "begin.files_recorded.before_rename",
    "db.batch_written",
    "batch.db_version.before_rename",
    "patch.synced",
    "patch.journal.before_rename",
    "patch.journal.before_sync",
    "db.files_written",
    "file.db_version.before_rename",
    "file.db_version.before_sync",
    "place.prepared.before_rename",
    "place.prepared.before_sync",
    "copy.part_created",
    "place.part_recorded.before_rename",
    "copy.part_synced",
    "place.renamed",
    "place.synced",
    "place.placed.before_rename",
    "commit.stop_marker",
    "commit.committing.before_rename",
    "finish.not_sent.before_rename",
    "finish.state.before_rename",
    "finish.notified",
    "finish.notified_ms.before_rename",
];

#[test]
fn abort_removes_the_placed_files_of_the_batch_and_its_upload_space() {
    for cross_device in [false, true] {
        let env = Env::new(cross_device);
        let service = env.service();
        // Entries that existed before the batch stay.
        std::fs::create_dir_all(env.dataset.join("in/a")).unwrap();
        std::fs::write(env.dataset.join("in/keep"), b"keep").unwrap();
        let files = [("a/x", 20), ("a/b/y", 20), ("c/z", 20), ("w", 20)];
        let begun = service.begin(USER, &request("abort-1", &files)).unwrap();
        let id = begun.batch_id.clone();
        send_file(&service, &id, 0, &content(0, 20)).unwrap();
        send_file(&service, &id, 1, &content(1, 20)).unwrap();
        send_file(&service, &id, 3, &content(3, 20)).unwrap();
        // Another writer replaced a placed file. Its identity differs, so it stays.
        std::fs::remove_file(env.dataset.join("in/w")).unwrap();
        std::fs::write(env.dataset.join("in/w"), b"other").unwrap();
        // File 2 has a prefix only.
        service.tus_create(USER, &id, 2, 20).unwrap();
        let mut session = service.tus_patch_open(USER, &id, 2, 0, Some(8)).unwrap();
        assert!(session.write(&content(2, 8)).unwrap());
        session.finish(BodyEnd::Complete).unwrap();
        assert_eq!(read_dest(&env, "/in/a/b/y"), Some(content(1, 20)));

        service.abort(USER, &id).unwrap();
        assert_eq!(tree(&env.dataset), vec!["in", "in/a", "in/keep", "in/w"], "cross device {cross_device}");
        assert_eq!(read_dest(&env, "/in/w"), Some(b"other".to_vec()));
        assert!(!service.space.batch_dir(&id).exists());
        let batch = env.store.latest_batch(&id).unwrap();
        assert_eq!(batch.state, batch_state::CANCELLED);
        assert_eq!(batch.error, common::uploads::ABORTED_MESSAGE);
        assert_eq!(env.store.latest_file(&id, 0).unwrap().state, "rejected");
        assert_eq!(env.store.latest_file(&id, 2).unwrap().state, "not_sent");
        assert!(env.notifier.calls.lock().unwrap().is_empty());
        // A repeated abort succeeds. A transfer request and a commit see the ended batch.
        service.abort(USER, &id).unwrap();
        assert_eq!(service.tus_create(USER, &id, 2, 20).unwrap_err().status, 410);
        assert_eq!(service.commit(USER, &id).unwrap().state, batch_state::CANCELLED);
        // The paths are free for a new upload.
        let again = service.begin(USER, &request("abort-2", &files[..2])).unwrap();
        assert_eq!(again.files.len(), 2);
    }
}

#[test]
fn abort_refuses_another_owner_and_a_committed_batch() {
    let env = Env::new(false);
    let service = env.service();
    let begun = service.begin(USER, &request("abort-3", &[("one", 4)])).unwrap();
    assert_eq!(service.abort("mallory", &begun.batch_id).unwrap_err().status, 403);
    send_file(&service, &begun.batch_id, 0, &content(0, 4)).unwrap();
    service.commit(USER, &begun.batch_id).unwrap();
    assert_eq!(service.abort(USER, &begun.batch_id).unwrap_err().status, 409);
    assert_eq!(read_dest(&env, "/in/one"), Some(content(0, 4)));
}

#[test]
fn a_deleted_or_purged_dataset_stops_its_transfers_and_keeps_placed_files() {
    let env = Env::new(false);
    let service = env.service();
    let a = service.begin(USER, &request("stop-a", &[("one", 4), ("two", 4)])).unwrap();
    send_file(&service, &a.batch_id, 0, &content(0, 4)).unwrap();
    let b = service.begin(USER, &request("stop-b", &[("three", 4)])).unwrap();
    let info = service.tus_create(USER, &b.batch_id, 0, 4).unwrap();
    assert_eq!(info.offset, 0);

    let stopped = service.stop_dataset(DATASET, common::uploads::DATASET_PURGED_MESSAGE).unwrap();
    assert_eq!(stopped, commit::DatasetStop { stopped: 2, busy: 0 });
    // A placed file stays, so its batch waits for the worker. The unsent file is not sent.
    assert_eq!(env.store.latest_batch(&a.batch_id).unwrap().state, batch_state::QUEUED);
    assert_eq!(env.store.latest_file(&a.batch_id, 0).unwrap().state, "placed");
    assert_eq!(env.store.latest_file(&a.batch_id, 1).unwrap().state, "not_sent");
    assert_eq!(read_dest(&env, "/in/one"), Some(content(0, 4)));
    assert!(env.notifier.calls.lock().unwrap().iter().any(|(_, id)| id == &a.batch_id));
    // No placed file: the batch is cancelled with the reason, and no byte stays.
    let cancelled = env.store.latest_batch(&b.batch_id).unwrap();
    assert_eq!(cancelled.state, batch_state::CANCELLED);
    assert_eq!(cancelled.error, common::uploads::DATASET_PURGED_MESSAGE);
    assert!(!service.space.data(&b.batch_id, 0).exists());
    assert_eq!(service.stop_dataset(DATASET, common::uploads::DATASET_PURGED_MESSAGE).unwrap().stopped, 0);

    // The sweep stops a transfer of a dataset that was deleted elsewhere.
    let c = service.begin(USER, &request("stop-c", &[("four", 4)])).unwrap();
    env.store.deleted.store(true, Ordering::SeqCst);
    assert_eq!(service.sweep_batch(&c.batch_id, false).unwrap(), commit::SweepOutcome::Stopped);
    let swept = env.store.latest_batch(&c.batch_id).unwrap();
    assert_eq!(swept.state, batch_state::CANCELLED);
    assert_eq!(swept.error, common::uploads::DATASET_DELETED_MESSAGE);
    assert_eq!(env.store.latest_file(&c.batch_id, 0).unwrap().state, "not_sent");
    assert!(read_dest(&env, "/in/four").is_none());
}

#[test]
fn every_crash_point_converges_to_one_placement_and_one_queued_record() {
    // File 2 is never sent, so commit marks it not_sent.
    let files: &[(&str, u64)] = &[("x/a.txt", 20), ("x/y/b.txt", 5), ("never.txt", 7)];
    let send: &[usize] = &[0, 1];
    for cross in [false, true] {
        for point in CRASH_POINTS {
            let env = Env::new(cross);
            let first = env.service();
            first.faults.arm(point);
            let crashed = (|| -> UploadResult<String> {
                let begun = first.begin(USER, &request("crash", files))?;
                for &n in send {
                    send_file(&first, &begun.batch_id, n as u32, &content(n as u32, files[n].1))?;
                }
                first.commit(USER, &begun.batch_id)?;
                first.finish(&begun.batch_id)?;
                Ok(begun.batch_id)
            })();
            let fired = first.faults.pending().is_none();
            if cross || !point.starts_with("copy.") && *point != "place.part_recorded.before_rename" {
                assert!(fired, "cross={cross}: the point {point} was not reached");
            }
            if let Err(e) = &crashed {
                assert!(e.message.contains(fsutil::SIMULATED_CRASH), "{point}: {}", e.message);
            }
            drop(first);

            // The restarted website recovers, and the client repeats its steps.
            let second = env.service();
            second.sweep(true).unwrap();
            let begun = second.begin(USER, &request("crash", files)).unwrap();
            for &n in send {
                match send_file(&second, &begun.batch_id, n as u32, &content(n as u32, files[n].1)) {
                    Ok(()) => {}
                    Err(e) if e.status == 409 && e.message == common::uploads::ENDED_MESSAGE => {}
                    Err(e) => panic!("{point}: resend of file {n} failed: {} {}", e.status, e.message),
                }
            }
            let committed = second.commit(USER, &begun.batch_id).unwrap();
            assert_eq!(committed.detail, detail_address(COLLECTION, &begun.batch_id));
            second.finish(&begun.batch_id).unwrap();
            second.sweep(true).unwrap();

            let id = begun.batch_id.as_str();
            assert_eq!(env.store.batch_ids(), vec![id.to_string()], "{point}: one batch");
            assert_eq!(env.store.latest_batch(id).unwrap().state, batch_state::QUEUED, "{point}");
            for &n in send {
                assert_eq!(read_dest(&env, &format!("/in/{}", files[n].0)).unwrap(), content(n as u32, files[n].1), "{point}");
                assert_eq!(env.store.latest_file(id, n as u32).unwrap().state, "placed", "{point}");
            }
            assert_eq!(env.store.latest_file(id, 2).unwrap().state, "not_sent", "{point}");
            assert!(read_dest(&env, "/in/never.txt").is_none());
            let entries = tree(&env.dataset);
            assert_eq!(entries, vec!["in", "in/x", "in/x/a.txt", "in/x/y", "in/x/y/b.txt"], "{point}: {entries:?}");
            let calls = env.notifier.calls.lock().unwrap().clone();
            assert!(!calls.is_empty() && calls.iter().all(|c| c == &(DATASET.to_string(), id.to_string())), "{point}");
            assert!(journal::live_batches(&second.space, DATASET).unwrap().is_empty(), "{point}: the reservation ends");
            for n in 0..3 {
                assert!(!second.space.data(id, n).exists(), "{point}: data of file {n} remains");
            }
        }
    }
}

#[test]
fn an_unreachable_store_keeps_the_rows_in_the_journal_until_it_returns() {
    let env = Env::new(false);
    let service = env.service();
    let begun = service.begin(USER, &request("store", &[("a", 4)])).unwrap();
    env.store.fail.store(true, Ordering::SeqCst);
    // No transfer request writes a row, so the transfer and the commit succeed.
    send_file(&service, &begun.batch_id, 0, &content(0, 4)).unwrap();
    service.commit(USER, &begun.batch_id).unwrap();
    let due = service.rows.take_due(std::time::Instant::now()).unwrap();
    assert!(service.flush_queued(&due).is_err());
    assert!(service.finish(&begun.batch_id).is_err());
    assert_eq!(journal::read_batch(&service.space, &begun.batch_id).unwrap().unwrap().state, batch_state::COMMITTING);
    env.store.fail.store(false, Ordering::SeqCst);
    service.sweep(true).unwrap();
    service.sweep(true).unwrap();
    assert_eq!(env.store.latest_file(&begun.batch_id, 0).unwrap().state, "placed");
    assert_eq!(env.store.latest_batch(&begun.batch_id).unwrap().state, batch_state::QUEUED);
}

#[test]
fn transfer_requests_write_no_row_and_the_flusher_writes_one_insert_for_each_table() {
    let env = Env::new(false);
    let service = env.service();
    let files: &[(&str, u64)] = &[("a", 4), ("b", 4), ("c", 0), ("d", 4)];
    let begun = service.begin(USER, &request("rows", files)).unwrap();
    let id = begun.batch_id.as_str();
    // `begin` writes the manifest rows and the batch row, one insert each.
    assert_eq!(env.store.file_inserts.load(Ordering::SeqCst), 1);
    assert_eq!(env.store.batch_inserts.load(Ordering::SeqCst), 1);
    for n in 0..3u32 {
        send_file(&service, id, n, &content(n, files[n as usize].1)).unwrap();
    }
    service.tus_create(USER, id, 3, 4).unwrap();
    service.tus_terminate(USER, id, 3).unwrap();
    assert_eq!(env.store.file_inserts.load(Ordering::SeqCst), 1, "a transfer request wrote a row");

    let start = std::time::Instant::now();
    let due = service.rows.take_due(start).unwrap();
    assert_eq!((due.batch_id.as_str(), due.batch, due.files.iter().copied().collect::<Vec<_>>()), (id, false, vec![0, 1, 2, 3]));
    service.flush_queued(&due).unwrap();
    assert_eq!(env.store.file_inserts.load(Ordering::SeqCst), 2);
    for (n, state) in [(0, "placed"), (1, "placed"), (2, "placed"), (3, "not_sent")] {
        assert_eq!(env.store.latest_file(id, n).unwrap().state, state, "file {n}");
    }
    // The flusher records no db_version, so the commit writes the rows again, and the
    // journal keeps each row until a writer that records its version stored it.
    assert!(journal::read_file(&service.space, &journal::read_manifest(&service.space, id).unwrap().unwrap(), 0).unwrap().db_version < 4);

    // A change within the interval waits for it.
    service.queue_rows(id, None);
    assert_eq!(service.rows.take_due(start + std::time::Duration::from_millis(500)).unwrap_err(), Some(start + ROW_FLUSH_INTERVAL));
    let due = service.rows.take_due(start + ROW_FLUSH_INTERVAL).unwrap();
    assert!(due.batch && due.files.is_empty());
    service.flush_queued(&due).unwrap();
    assert_eq!(env.store.batch_inserts.load(Ordering::SeqCst), 1, "the batch row did not change");

    // The commit request writes no row. The finish writes one insert for each table.
    service.commit(USER, id).unwrap();
    assert_eq!((env.store.file_inserts.load(Ordering::SeqCst), env.store.batch_inserts.load(Ordering::SeqCst)), (2, 1));
    service.finish(id).unwrap();
    assert_eq!((env.store.file_inserts.load(Ordering::SeqCst), env.store.batch_inserts.load(Ordering::SeqCst)), (3, 2));
    assert_eq!(env.store.latest_batch(id).unwrap().state, batch_state::QUEUED);
    let manifest = journal::read_manifest(&service.space, id).unwrap().unwrap();
    for n in 0..4 {
        let file = journal::read_file(&service.space, &manifest, n).unwrap();
        assert_eq!(file.db_version, file.version, "file {n}");
    }
    // A queued batch row that the finish already wrote gives no insert.
    let due = service.rows.take_due(start + ROW_FLUSH_INTERVAL * 2).unwrap();
    service.flush_queued(&due).unwrap();
    assert_eq!(env.store.batch_inserts.load(Ordering::SeqCst), 2);
}

/// Run `work` on another thread and return its result, or `None` when it does not end
/// within `limit`. A request that waits without a limit then fails the test instead of
/// stopping it.
fn within<T: Send + 'static>(limit: std::time::Duration, work: impl FnOnce() -> T + Send + 'static) -> Option<(T, std::time::Duration)> {
    let (sender, receiver) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let started = std::time::Instant::now();
        let value = work();
        let _ = sender.send((value, started.elapsed()));
    });
    receiver.recv_timeout(limit).ok()
}

#[test]
fn a_stalled_patch_delays_the_other_requests_only_for_the_lock_wait() {
    let env = Env::new(false);
    let service = env.service();
    let begun = service.begin(USER, &request("stall", &[("a", 16), ("b", 4)])).unwrap();
    let id = begun.batch_id.clone();
    send_file(&service, &id, 1, &content(1, 4)).unwrap();
    // A PATCH whose client stopped sending: it holds the shared batch lock and the file lock.
    let mut stalled = service.tus_patch_open(USER, &id, 0, 0, Some(8)).unwrap();
    assert!(stalled.write(&content(0, 8)[..3]).unwrap());

    let limit = TEST_LOCK_WAIT * 4;
    for (name, status) in [
        ("HEAD", { let (s, i) = (service.clone(), id.clone()); within(limit, move || s.tus_head(USER, &i, 0).map(|_| ()).unwrap_err().status) }),
        ("prefix", { let (s, i) = (service.clone(), id.clone()); within(limit, move || s.prefix_digest(USER, &i, 0).map(|_| ()).unwrap_err().status) }),
        ("commit", { let (s, i) = (service.clone(), id.clone()); within(limit, move || s.commit(USER, &i).map(|_| ()).unwrap_err().status) }),
    ] {
        let (status, waited) = status.unwrap_or_else(|| panic!("{name} waited longer than {limit:?}"));
        assert_eq!(status, 423, "{name}");
        assert!(waited >= TEST_LOCK_WAIT, "{name} answered after {waited:?}");
    }
    let stop = {
        let s = service.clone();
        within(limit, move || s.stop_dataset(DATASET, common::uploads::DATASET_DELETED_MESSAGE).unwrap())
    };
    assert_eq!(stop.expect("the stop waits at most the lock wait").0, commit::DatasetStop { stopped: 0, busy: 1 });
    assert_eq!(service.sweep_batch(&id, false).unwrap(), commit::SweepOutcome::Busy);
    // The refused commit left its stop marker, and the batch still accepts no new PATCH.
    assert!(service.space.stopping(&id).exists());
    assert_eq!(env.store.latest_batch(&id).unwrap().state, batch_state::UPLOADING);

    // The idle limit of the route ends the PATCH as interrupted, and its prefix stays.
    assert_eq!(stalled.finish(BodyEnd::Interrupted).unwrap().offset, 3);
    assert_eq!(service.tus_head(USER, &id, 0).unwrap().offset, 3);
    // The sweep commits a batch whose owner asked for the commit.
    assert_eq!(service.sweep_batch(&id, false).unwrap(), commit::SweepOutcome::Committed);
    assert_eq!(env.store.latest_batch(&id).unwrap().state, batch_state::QUEUED);
    assert_eq!(env.store.latest_file(&id, 0).unwrap().state, "not_sent");
    assert_eq!(read_dest(&env, "/in/b"), Some(content(1, 4)));
}

/// The part files in the dataset folder of a test.
fn parts(env: &Env) -> Vec<String> {
    tree(&env.dataset).into_iter().filter(|p| p.contains(".hoover4-part")).collect()
}

#[test]
fn a_rejection_without_a_target_removes_the_owned_part_of_a_copy() {
    let env = Env::new(true);
    let first = env.service();
    let begun = first.begin(USER, &request("part", &[("a", 4)])).unwrap();
    let id = begun.batch_id.clone();
    first.faults.arm("copy.part_created");
    assert!(send_file(&first, &id, 0, &content(0, 4)).unwrap_err().message.contains(fsutil::SIMULATED_CRASH));
    assert_eq!(parts(&env).len(), 1, "the crash leaves the part");
    drop(first);

    // The dataset is deleted before any sweep places the file again.
    let service = env.service();
    env.store.deleted.store(true, Ordering::SeqCst);
    assert_eq!(service.sweep_batch(&id, false).unwrap(), commit::SweepOutcome::Stopped);
    assert_eq!(parts(&env), Vec::<String>::new());
    let file = env.store.latest_file(&id, 0).unwrap();
    assert_eq!((file.state.as_str(), file.error.as_str()), ("rejected", common::uploads::DATASET_DELETED_MESSAGE));
    assert_eq!(env.store.latest_batch(&id).unwrap().state, batch_state::CANCELLED);
}

#[test]
fn a_part_whose_folder_does_not_open_stays_recorded_until_the_sweep_removes_it() {
    let env = Env::new(true);
    let first = env.service();
    let begun = first.begin(USER, &request("part-later", &[("a", 4)])).unwrap();
    let id = begun.batch_id.clone();
    first.faults.arm("copy.part_created");
    assert!(send_file(&first, &id, 0, &content(0, 4)).is_err());
    drop(first);
    let service = env.service();

    // The mount root is not available while the deleted dataset stops its transfer.
    let mount_root = env.dirs[0].clone();
    let moved = mount_root.with_extension("away");
    std::fs::rename(&mount_root, &moved).unwrap();
    env.store.deleted.store(true, Ordering::SeqCst);
    assert!(service.sweep_batch(&id, false).is_err());
    let manifest = journal::read_manifest(&service.space, &id).unwrap().unwrap();
    assert_eq!(journal::read_file(&service.space, &manifest, 0).unwrap().state, FileState::Placing);
    std::fs::rename(&moved, &mount_root).unwrap();
    assert_eq!(parts(&env).len(), 1);

    assert_eq!(service.sweep_batch(&id, false).unwrap(), commit::SweepOutcome::Stopped);
    assert_eq!(parts(&env), Vec::<String>::new());
    assert_eq!(env.store.latest_file(&id, 0).unwrap().state, "rejected");
}

#[test]
fn a_folder_that_does_not_open_keeps_complete_files_for_a_later_placement() {
    let env = Env::new(false);
    let service = env.service();
    let begun = service.begin(USER, &request("away", &[("a", 4), ("b", 4)])).unwrap();
    let id = begun.batch_id.clone();
    let mut s = service.tus_patch_open(USER, &id, 0, 0, Some(4)).unwrap();
    s.write(&content(0, 4)).unwrap();
    assert!(s.finish(BodyEnd::Complete).unwrap().complete);
    service.commit(USER, &id).unwrap();

    let target = env.access.target.lock().unwrap().clone();
    *env.access.target.lock().unwrap() =
        TargetLookup::Unavailable { upload_dataset: DATASET.to_string(), reason: "the mount is not available".to_string() };
    assert!(service.finish(&id).is_err());
    let manifest = journal::read_manifest(&service.space, &id).unwrap().unwrap();
    assert_eq!(journal::read_file(&service.space, &manifest, 0).unwrap().state, FileState::Complete);
    assert!(service.space.data(&id, 0).exists());
    // The flusher writes the `committing` row that the commit queued.
    service.flush_queued(&service.rows.take_due(std::time::Instant::now()).unwrap()).unwrap();
    assert_eq!(env.store.latest_batch(&id).unwrap().state, batch_state::COMMITTING);
    // A transfer request gets a retryable answer, not the permission text.
    let other = service.begin(USER, &request("away-2", &[("c", 4)]));
    assert_eq!(other.unwrap_err().status, 503);
    // The sweep keeps the batch while the folder stays unavailable.
    env.advance(COMMIT_RETRY_MS + 1);
    assert!(service.sweep_batch(&id, false).is_err());
    assert!(service.space.data(&id, 0).exists());

    *env.access.target.lock().unwrap() = target;
    assert_eq!(service.sweep_batch(&id, false).unwrap(), commit::SweepOutcome::Committed);
    assert_eq!(read_dest(&env, "/in/a"), Some(content(0, 4)));
    assert_eq!(env.store.latest_file(&id, 1).unwrap().state, "not_sent");
    assert_eq!(env.store.latest_batch(&id).unwrap().state, batch_state::QUEUED);
}

#[test]
fn begin_refuses_while_a_deletion_or_purge_of_the_dataset_is_live() {
    let env = Env::new(false);
    let service = env.service();
    env.store.removal_live.store(true, Ordering::SeqCst);
    let e = service.begin(USER, &request("during-delete", &[("a", 1)])).unwrap_err();
    assert_eq!((e.status, e.message.as_str()), (409, begin::REMOVAL_MESSAGE));
    assert!(env.store.batch_ids().is_empty());
    env.store.removal_live.store(false, Ordering::SeqCst);
    service.begin(USER, &request("during-delete", &[("a", 1)])).unwrap();
}

/// Measure `RENAME_NOREPLACE` and folder synchronization on the folders that
/// `HOOVER4_FS_PROBE_DIRS` names, separated by `:`. Run it in the website container with
/// `--ignored --nocapture` on the upload space and on each writable mount.
#[test]
#[ignore]
fn probe_filesystem_support() {
    let dirs = std::env::var("HOOVER4_FS_PROBE_DIRS").expect("HOOVER4_FS_PROBE_DIRS names the folders");
    for dir in dirs.split(':').filter(|d| !d.is_empty()) {
        let probe = PathBuf::from(dir).join(format!(".hoover4-fs-probe-{}", random_id()));
        std::fs::create_dir(&probe).unwrap();
        let fd = fsutil::open_space_dir(&probe).unwrap();
        std::fs::write(probe.join("a"), b"a").unwrap();
        std::fs::write(probe.join("b"), b"b").unwrap();
        let replace = rustix::fs::renameat_with(&fd, "a", &fd, "b", rustix::fs::RenameFlags::NOREPLACE);
        let fresh = rustix::fs::renameat_with(&fd, "a", &fd, "c", rustix::fs::RenameFlags::NOREPLACE);
        let sync = rustix::fs::fsync(&fd);
        let st = rustix::fs::fstatvfs(&fd).unwrap();
        eprintln!(
            "probe {dir}: dev {} fs_type_magic {:#x} rename_noreplace onto existing = {:?}, onto new = {:?}, b kept = {}, dir fsync = {:?}, f_bsize {}",
            std::fs::metadata(&probe).unwrap().dev(),
            rustix::fs::fstatfs(&fd).map(|s| s.f_type as u64).unwrap_or(0),
            replace,
            fresh,
            std::fs::read(probe.join("b")).unwrap() == b"b",
            sync,
            st.f_bsize,
        );
        std::fs::remove_dir_all(&probe).unwrap();
    }
}

#[test]
fn a_completed_cli_purge_stops_an_existing_transfer() {
    let env = Env::new(false);
    let service = env.service();
    let batch = service.begin(USER, &request("before-purge", &[("pending", 4)])).unwrap();
    service.tus_create(USER, &batch.batch_id, 0, 4).unwrap();
    // The CLI left a terminal operation row without calling the website stop hook.
    *env.store.removal_id.lock().unwrap() = "purge-1".into();
    assert!(!env.store.removal_live.load(Ordering::SeqCst));
    assert_eq!(service.tus_create(USER, &batch.batch_id, 0, 4).unwrap_err().status, 403);
    service.sweep(false).unwrap();
    assert_eq!(env.store.latest_batch(&batch.batch_id).unwrap().state, batch_state::CANCELLED);
    assert!(!service.space.data(&batch.batch_id, 0).exists());
    let next = service.begin(USER, &request("after-purge", &[("next", 4)])).unwrap();
    assert!(service.tus_create(USER, &next.batch_id, 0, 4).is_ok());
}
