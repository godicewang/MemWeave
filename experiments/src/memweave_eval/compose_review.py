"""Admission for the selected local-service tasks; no host mounts or privileges."""
from __future__ import annotations

from .spec import load_yaml
from .storage import file_digest


def review_local_compose(path):
    value=load_yaml(path)
    if set(value)-{'services','version'} or not isinstance(value.get('services'),dict):
        raise ValueError('unreviewed Compose top-level capability')
    root=path.parent.resolve()
    forbidden={'volumes','devices','privileged','network_mode','ports','pid','ipc','cap_add',
               'security_opt','container_name','extra_hosts','env_file','secrets','configs'}
    builds={}
    for name,service in value['services'].items():
        if not isinstance(service,dict) or forbidden.intersection(service):
            raise ValueError('Compose requests an unreviewed host capability')
        build=service.get('build')
        if not build or service.get('image'):
            raise ValueError('selected sidecars must build from frozen local source')
        context=build if isinstance(build,str) else build.get('context')
        target=(root/context).resolve()
        if target!=root and root not in target.parents:
            raise ValueError('Compose build context escapes task environment')
        if isinstance(build,dict) and set(build)-{'context','dockerfile'}:
            raise ValueError('unreviewed Compose build options')
        dockerfile=target/(build.get('dockerfile','Dockerfile')if isinstance(build,dict)else 'Dockerfile')
        if not dockerfile.is_file() or not dockerfile.resolve().is_relative_to(root):
            raise ValueError('Compose Dockerfile outside selected source')
        builds[name]={'context':str(target.relative_to(root)),'dockerfile_sha256':file_digest(dockerfile)}
    return {'compose_sha256':file_digest(path),'services':builds,
            'host_ports':False,'host_mounts':False,'elevated_container_capabilities':False}
