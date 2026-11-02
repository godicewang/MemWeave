import pytest

from memweave_eval.compose_review import review_local_compose


def test_only_frozen_task_local_services_are_admitted(tmp_path):
    (tmp_path/'Dockerfile').write_text('FROM public\n')
    source=tmp_path/'docker-compose.yaml'
    source.write_text('services:\n  main:\n    build: .\n    expose: ["8000"]\n')
    result=review_local_compose(source)
    assert set(result['services'])=={'main'} and not result['host_mounts']
    for key,value in [('privileged','true'),('volumes','[/var/run/docker.sock:/socket]'),
                      ('ports','[8080:80]'),('network_mode','host')]:
        source.write_text('services:\n  main:\n    build: .\n    '+key+': '+value+'\n')
        with pytest.raises(ValueError):review_local_compose(source)
    source.write_text('services:\n  main:\n    build: ../outside\n')
    with pytest.raises(ValueError):review_local_compose(source)
