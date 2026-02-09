"""CLI entry point for processing services, including migrations and workers."""

import click
import asyncio

import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

@click.group()
def cli():
    pass

@cli.command()
def version():
    print("0.0.0")


@cli.command()
def migrate():
    """Run all database migrations."""
    from database.clickhouse import clickhouse_migrate
    from database.minio import BUCKET_NAME
    clickhouse_migrate()
    from database.minio import ensure_bucket
    ensure_bucket(BUCKET_NAME)
    from database.manticore import manticore_migrate
    manticore_migrate()


@cli.command()
def test_extract_ner_from_text():
    from tasks.P4_index_data.extract_ner_from_text import extract_ner_from_texts
    with open('/etc/dictionaries-common/words') as f:
        words = f.readlines()
    import random
    random.shuffle(words)
    words = " ".join(words)
    entities = extract_ner_from_texts([words])
    print(entities)


@cli.command()
@click.argument("dataset_name", type=str)
@click.argument("path", type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=str))
def add_disk_dataset(dataset_name: str, path: str):
    """Create dataset row and start disk ingestion workflow."""
    from tasks.P0_scan_disk.submit_job import add_disk_dataset
    add_disk_dataset(dataset_name, path)

    from tasks.P1_compute_plans.submit_job import submit_compute_plans
    asyncio.run(submit_compute_plans(dataset_name))

    from tasks.P2_execute_plan.submit_job import submit_execute_plans
    asyncio.run(submit_execute_plans(dataset_name))

@cli.command()
@click.argument("worker_type", required=False, type=click.Choice(["common", "tika", "easyocr", "indexing"]))
def worker(worker_type: str | None = None):
    """Run worker(s). If worker_type provided, runs that worker; else spawns all."""
    import sys
    import subprocess

    # Map to function names in tasks.run_worker
    if worker_type:
        # Run single worker in current process
        if worker_type == "common":
            from tasks.run_worker import run_common_worker
            asyncio.run(run_common_worker())
        elif worker_type == "tika":
            from tasks.run_worker import run_tika_worker
            asyncio.run(run_tika_worker())
        elif worker_type == "easyocr":
            from tasks.run_worker import run_easyocr_worker
            asyncio.run(run_easyocr_worker())
        elif worker_type == "indexing":
            from tasks.run_worker import run_indexing_worker
            asyncio.run(run_indexing_worker())
        else:
            raise click.ClickException(f"Unknown worker type: {worker_type}")
        return

    # No type: spawn subprocesses for each worker and monitor/restart
    import time
    this = sys.argv[0]
    workers = []  # [{ 'type': str, 'cmd': List[str], 'proc': Popen|None, 'restart_at': float|None }]
    shutting_down = False

    # Initial spawn set
    for wt in ["tika", "easyocr", "indexing"] + ["common"] * 2:
        cmd = [sys.executable, this, "worker", wt]
        log.info("Spawning worker: %s", " ".join(cmd))
        p = subprocess.Popen(cmd)
        workers.append({"type": wt, "cmd": cmd, "proc": p, "restart_at": None})

    try:
        # Monitor loop: restart crashed/ended processes after 10s
        while True:
            now = time.time()
            for w in workers:
                p = w["proc"]
                # If process exists, check if it has ended
                if p is not None:
                    code = p.poll()
                    if code is not None:
                        # Ended or crashed
                        log.warning("Worker '%s' exited with code %s. Will restart in 10s.", w["type"], code)
                        w["proc"] = None
                        w["restart_at"] = now + 10
                # If process not running and we are not shutting down, maybe restart
                elif not shutting_down and w["restart_at"] is not None and now >= w["restart_at"]:
                    log.info("Restarting worker: %s", " ".join(w["cmd"]))
                    try:
                        p2 = subprocess.Popen(w["cmd"])
                        w["proc"] = p2
                        w["restart_at"] = None
                    except Exception as e:
                        # If spawn fails, try again in 10s
                        log.warning("Failed to restart worker '%s': %s. Retrying in 10s.", w["type"], e)
                        w["restart_at"] = now + 10

            time.sleep(1)
    except KeyboardInterrupt:
        # Immediate kill on Ctrl-C with warning
        shutting_down = True
        log.warning("Ctrl-C received. Killing all worker processes immediately.")
        for w in workers:
            p = w["proc"]
            if p is not None:
                try:
                    log.warning("Killing worker '%s' (pid=%s)", w["type"], getattr(p, "pid", "?"))
                    p.kill()
                except Exception:
                    pass
    finally:
        # Best-effort short wait for processes to exit
        for w in workers:
            p = w["proc"]
            if p is not None:
                try:
                    p.wait(timeout=1)
                except Exception:
                    pass


if __name__ == '__main__':
    cli()