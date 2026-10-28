from memweave_eval.private_runtime import image_libc, node_wrapper


def test_libc_probe_is_offline_and_cached(monkeypatch):
    import memweave_eval.private_runtime as module
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        assert "none" in args and "--entrypoint" in args
        return "ID=alpine\nmusl libc 1.2.5"
    image_libc.cache_clear()
    monkeypatch.setattr(module.subprocess, "check_output", execute)
    assert image_libc("sha256:alpine", "linux/amd64") == "musl"
    assert image_libc("sha256:alpine", "linux/amd64") == "musl"
    assert len(calls) == 1
    image_libc.cache_clear()


def test_wrapper_preserves_node_and_fork_entry_without_global_library_path():
    shell, shim = node_wrapper()
    assert "LD_LIBRARY_PATH=" not in shell
    assert 'node.real' in shell and '--library-path' in shell
    assert 'process.execPath=' in shim and 'process.argv[0]' in shim
