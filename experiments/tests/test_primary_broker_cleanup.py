from memweave_eval.storage import file_digest
from memweave_eval.trusted_broker import TrustedBroker


def test_repeated_cleanup_retains_first_stop_proof_without_hiding_startup_failure(tmp_path):
    root=tmp_path/'broker';root.mkdir()
    (tmp_path/'control').mkdir()
    broker=TrustedBroker(root,tmp_path/'control','fixture-run','fixture-image',{})
    first=broker.stop();digest=file_digest(root/'controller-end.json')
    assert broker.stop()==first
    assert file_digest(root/'controller-end.json')==digest
    assert first=={'stopped':False,'terminal_available':False}
