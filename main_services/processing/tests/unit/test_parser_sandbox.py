"""The bubblewrap command of tasks/sandbox.py."""

from tasks import sandbox


def test_off_keeps_the_command(monkeypatch):
    monkeypatch.delenv("HOOVER4_PARSER_SANDBOX", raising=False)
    assert sandbox._wrap(["file", "/tmp/x"], {"env": {"A": "1"}}) == (["file", "/tmp/x"], {"env": {"A": "1"}})


def test_command_hides_the_worker(monkeypatch, tmp_path):
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "item").write_text("x")
    monkeypatch.setattr(sandbox, "HIDDEN", (str(tmp_path),))
    monkeypatch.setenv("S3_SECRET_KEY", "secret")
    argv = sandbox.command(["7z", "x", f"-o{plan}/out", str(plan / "item")],
                           env={"S3_SECRET_KEY": "secret", "MAGICK_THREAD_LIMIT": "1"})
    joined = " ".join(argv)
    assert "--unshare-net" in argv and "--clearenv" in argv
    assert "secret" not in joined
    assert "MAGICK_THREAD_LIMIT 1" in joined
    assert ["--tmpfs", str(tmp_path)] == argv[argv.index("--tmpfs"):argv.index("--tmpfs") + 2]
    assert ["--bind", str(plan), str(plan)] == argv[argv.index("--bind"):argv.index("--bind") + 3]
    assert argv[-4:] == ["7z", "x", f"-o{plan}/out", str(plan / "item")]


def test_hidden_roots_stay_hidden(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "HIDDEN", (str(tmp_path),))
    assert sandbox._visible(str(tmp_path / "missing" / "file")) is None


def test_shell_commands_are_refused(monkeypatch):
    monkeypatch.setenv("HOOVER4_PARSER_SANDBOX", "bwrap")
    try:
        sandbox._wrap("ls /tmp", {"shell": True})
    except ValueError:
        return
    raise AssertionError("a shell command passed")


def test_image_headers_are_read_in_a_child(monkeypatch, tmp_path):
    import io
    import subprocess

    from PIL import Image

    from tasks.P3_parse_files import image_loader

    picture = tmp_path / "a.png"
    Image.new("RGB", (40, 30)).save(picture)
    buffer = io.BytesIO()
    Image.new("RGB", (7, 9)).save(buffer, format="PNG")
    started = []
    monkeypatch.setenv("HOOVER4_PARSER_SANDBOX", "bwrap")
    monkeypatch.setattr(sandbox, "run", lambda args, **kw: started.append(args) or subprocess.run(args, **kw))
    assert image_loader.image_sizes([str(picture), str(tmp_path / "missing")]) == [(40, 30), None]
    assert image_loader.image_dimensions(buffer.getvalue()) == (7, 9)
    assert image_loader.image_dimensions(b"not an image") is None
    assert len(started) == 3


def test_a_hidden_link_gets_no_mount(monkeypatch, tmp_path):
    (tmp_path / "run").mkdir()
    (tmp_path / "var-run").symlink_to(tmp_path / "run")
    monkeypatch.setattr(sandbox, "HIDDEN", (str(tmp_path / "run"), str(tmp_path / "var-run")))
    argv = sandbox.command(["true"])
    assert ["--tmpfs", str(tmp_path / "run")] == argv[argv.index("--tmpfs"):argv.index("--tmpfs") + 2]
    assert str(tmp_path / "var-run") not in argv
