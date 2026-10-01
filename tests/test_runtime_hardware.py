"""Hardware mocks never use real GPUs, model weights, or production services."""

import importlib.util
from pathlib import Path
import subprocess

import pytest

from scoring.runtime.hardware import (BackendUnavailable, HardwareSelection,
                                      effective_gpu_layers, parse_devices, selection_status)
from scoring.runtime.manager import RuntimeManager, RuntimeProfile
from tests import test_runtime as runtime_fakes

FixedPorts = runtime_fakes.FixedPorts
healthy_request = runtime_fakes.RuntimeTests.healthy_request


class FakeProcess(runtime_fakes.FakeProcess):
    def __init__(self, returncode=None):
        self.pid = 5500
        self.returncode = returncode
        self.killed = False
        self.terminated = False

BINARIES = {name: f'/fixture/{name}' for name in ('cpu', 'cuda', 'rocm', 'vulkan')}
OUTPUTS = {
    'cuda': 'CUDA0: NVIDIA RTX A6000 (49140 MiB, 48000 MiB free)\nCUDA1: NVIDIA RTX A6000 (49140 MiB, 47000 MiB free)',
    'rocm': 'ROCm0: AMD Radeon (16384 MiB, 15000 MiB free)',
    'vulkan': 'Vulkan0: AMD Radeon (16384 MiB, 15000 MiB free)',
    'cpu': 'llama.cpp version fixture',
}


def hardware(tmp_path, usable=('cpu',), *, outputs=None):
    def run(command, **kwargs):
        backend = Path(command[0]).name
        assert command[1] == ('--version' if backend == 'cpu' else '--list-devices')
        assert kwargs['timeout'] == 20
        return subprocess.CompletedProcess(command, 0 if backend in usable else 1,
                                            (outputs or OUTPUTS)[backend] if backend in usable else '',
                                            '' if backend in usable else 'load failed')
    return HardwareSelection(BINARIES, runner=run, device_root=tmp_path)


@pytest.mark.parametrize('usable,expected', [
    (('cpu', 'cuda', 'vulkan'), 'cuda'),
    (('cpu', 'rocm', 'vulkan'), 'rocm'),
    (('cpu', 'vulkan'), 'vulkan'),
    (('cpu',), 'cpu'),
])
def test_backend_priority(tmp_path, usable, expected):
    selected = hardware(tmp_path, usable).select()
    assert selected.backend == expected


def test_override_and_unavailable(tmp_path):
    h = hardware(tmp_path, ('cpu', 'cuda', 'vulkan'))
    assert h.select('cpu').backend == 'cpu'
    assert h.select('vulkan').backend == 'vulkan'
    with pytest.raises(BackendUnavailable):
        h.select('rocm')
    with pytest.raises(ValueError):
        h.select('attacker')


def test_no_device_node_or_smi_dependency_and_multi_gpu(tmp_path):
    h = hardware(tmp_path, ('cpu', 'cuda'))
    assert not h.hints['nvidia_device_nodes']
    selected = selection_status(h.select(), 'auto', 'auto')
    assert selected['gpu_count'] == 2
    assert selected['total_vram_bytes'] == 2 * 49140 * 1024 ** 2
    assert selected['hardware_vendor'] == 'nvidia'
    assert len(selected['gpu_names']) == 2


def test_device_nodes_alone_do_not_prove_gpu(tmp_path):
    (tmp_path / 'nvidia0').touch()
    h = hardware(tmp_path)
    assert h.hints['nvidia_device_nodes']
    assert h.select().backend == 'cpu'
    assert h.capabilities['cuda'].error_code == 'backend_load_failed'


def test_software_vulkan_is_not_gpu(tmp_path):
    outputs = {**OUTPUTS, 'vulkan': 'Vulkan0: llvmpipe (2048 MiB, 2048 MiB free)'}
    assert hardware(tmp_path, ('cpu', 'vulkan'), outputs=outputs).select().backend == 'cpu'
    assert parse_devices('CUDA0: NVIDIA RTX A6000 (49140 MiB, 48000 MiB free)', 'vulkan') == []


@pytest.mark.parametrize('error,code', [(PermissionError(), 'device_permission_denied'),
                                      (FileNotFoundError(), 'backend_not_installed'),
                                      (subprocess.TimeoutExpired('probe', 20), 'backend_probe_failed')])
def test_probe_failure_contained(tmp_path, error, code):
    def fail(*_, **__):
        raise error
    h = HardwareSelection(BINARIES, runner=fail, device_root=tmp_path)
    assert h.capabilities['cuda'].error_code == code
    with pytest.raises(BackendUnavailable):
        h.select()


@pytest.mark.parametrize('value,backend,expected', [
    ('auto', 'cpu', 0), ('auto', 'cuda', 'auto'), ('auto', 'rocm', 'auto'),
    ('auto', 'vulkan', 'auto'), (12, 'cuda', 12), (0, 'cuda', 0), (-1, 'cuda', -1),
])
def test_gpu_layers(value, backend, expected):
    assert effective_gpu_layers(value, backend) == expected
    for bad in ('alll', -9, True):
        with pytest.raises(ValueError):
            effective_gpu_layers(bad, backend)


def profile(tmp_path, **kwargs):
    model = tmp_path / 'fixture.gguf'
    model.touch()
    return RuntimeProfile(runtime_id='fixture', model_id='alias', model_path=str(model),
                          vision=False, backend='auto', gpu_layers='auto',
                          log_path=str(tmp_path / 'runtime.log'), startup_timeout_seconds=0.1,
                          **kwargs)


def test_manager_resolved_command_and_explicit_layer_override(tmp_path):
    h = hardware(tmp_path, ('cpu', 'cuda'))
    p = profile(tmp_path)
    p.gpu_layers = 7
    commands = []
    m = RuntimeManager({'fixture': p}, hardware=h, port_allocator=FixedPorts(),
                       launcher=lambda command, log: commands.append(command) or FakeProcess(),
                       request=healthy_request)
    ready = m.start('fixture')
    assert commands[0][0] == '/fixture/cuda'
    assert commands[0][commands[0].index('-ngl') + 1] == '7'
    assert ready['hardware']['gpu_count'] == 2
    assert p.gpu_layers == 7  # configuration is not rewritten
    m.close()


def test_unavailable_override_keeps_manager_alive(tmp_path):
    p = profile(tmp_path)
    p.backend = 'cuda'
    m = RuntimeManager({'fixture': p}, hardware=hardware(tmp_path))
    assert m.status('fixture')['state'] == 'unavailable'
    with pytest.raises(BackendUnavailable):
        m.start('fixture')
    assert m.status('fixture')['error_code'] == 'backend_unavailable'
    m.close()


@pytest.mark.parametrize('backend,error', [('cuda', b'CUDA error: out of memory\n'),
                                         ('vulkan', b'VK_ERROR_INITIALIZATION_FAILED\n')])
def test_auto_gpu_failure_retries_cpu_once(tmp_path, backend, error):
    commands = []
    def launch(command, log):
        commands.append(command)
        if command[0] != '/fixture/cpu':
            log.write(error)
            log.flush()
            return FakeProcess(returncode=1)
        return FakeProcess()
    m = RuntimeManager({'fixture': profile(tmp_path)}, hardware=hardware(tmp_path, ('cpu', backend)),
                       port_allocator=FixedPorts(), launcher=launch, request=healthy_request)
    ready = m.start('fixture')
    assert len(commands) == 2
    assert ready['hardware']['backend'] == 'cpu'
    assert ready['hardware']['fallback_reason'] in {'gpu_out_of_memory', 'backend_load_failed'}
    assert commands[-1][commands[-1].index('-ngl') + 1] == '0'
    m.close()


def test_explicit_gpu_failure_does_not_silently_switch(tmp_path):
    p = profile(tmp_path)
    p.backend = 'cuda'
    def launch(command, log):
        log.write(b'CUDA error: out of memory\n')
        log.flush()
        return FakeProcess(returncode=1)
    m = RuntimeManager({'fixture': p}, hardware=hardware(tmp_path, ('cpu', 'cuda')),
                       port_allocator=FixedPorts(), launcher=launch)
    with pytest.raises(RuntimeError):
        m.start('fixture')
    assert m.status('fixture')['error_code'] == 'gpu_out_of_memory'
    m.close()


def load_helper():
    path = Path(__file__).resolve().parents[1] / 'scripts/runtime-compose.py'
    spec = importlib.util.spec_from_file_location('runtime_compose', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render_fixture(tmp_path, vendor):
    device_root = tmp_path / 'dev'
    sys_root = tmp_path / 'sys'
    (device_root / 'dri').mkdir(parents=True)
    (device_root / 'dri/renderD128').touch()
    vendor_file = sys_root / 'class/drm/renderD128/device/vendor'
    vendor_file.parent.mkdir(parents=True)
    vendor_file.write_text(vendor)
    return device_root, sys_root


def override_files(command):
    return [Path(arg).name for arg in command if arg.endswith('.yaml')]


@pytest.mark.parametrize('vendor', ['0x10de', '0x1002'])
def test_nvidia_with_drm_selects_nvidia_only(tmp_path, vendor, monkeypatch):
    monkeypatch.delenv('GPU_RENDER_GID', raising=False)
    monkeypatch.delenv('GPU_KFD_GID', raising=False)
    helper = load_helper()
    device_root, sys_root = render_fixture(tmp_path, vendor)
    (device_root / 'nvidia0').touch()
    (device_root / 'kfd').touch()
    def info(*_, **__):
        return subprocess.CompletedProcess([], 0, '{"nvidia": {}}')
    cmd, env, _ = helper.compose_command(['config'], device_root=device_root,
                                        sys_root=sys_root, runner=info)
    assert override_files(cmd) == ['compose.yaml', 'compose.runtime-nvidia.yaml']
    assert 'GPU_RENDER_GID' not in env
    assert 'GPU_KFD_GID' not in env


@pytest.mark.parametrize('kfd', [False, True])
def test_amd_vendor_selects_drm_and_optional_rocm(tmp_path, kfd):
    helper = load_helper()
    device_root, sys_root = render_fixture(tmp_path, '0x1002')
    if kfd:
        (device_root / 'kfd').touch()
    cmd, env, _ = helper.compose_command(['config'], device_root=device_root, sys_root=sys_root)
    expected = ['compose.yaml', 'compose.runtime-amd.yaml']
    if kfd:
        expected.append('compose.runtime-rocm.yaml')
        assert env['GPU_KFD_GID'] == str((device_root / 'kfd').stat().st_gid)
    assert override_files(cmd) == expected
    assert env['GPU_RENDER_GID'] == str((device_root / 'dri/renderD128').stat().st_gid)


@pytest.mark.parametrize('vendor', ['0x10de', '0x8086', 'unknown', ''])
def test_other_or_unknown_drm_does_not_select_amd(tmp_path, vendor):
    device_root, sys_root = render_fixture(tmp_path, vendor)
    cmd, _, _ = load_helper().compose_command(['config'], device_root=device_root, sys_root=sys_root)
    assert override_files(cmd) == ['compose.yaml']


def test_no_gpu_uses_base_only(tmp_path):
    cmd, _, _ = load_helper().compose_command(['config'], device_root=tmp_path, sys_root=tmp_path)
    assert override_files(cmd) == ['compose.yaml']


def test_vulkan_build_installs_shader_dependencies():
    dockerfile = (Path(__file__).resolve().parents[1] / 'Dockerfile.runtime').read_text()
    vulkan_stage = dockerfile.split('FROM ubuntu:24.04 AS vulkan-build', 1)[1].split('FROM ${LLAMA_SERVER_IMAGE}', 1)[0]
    install = vulkan_stage.split('apt-get install', 1)[1].split('&& rm', 1)[0]
    for package in ('spirv-headers', 'glslang-tools', 'libvulkan-dev', 'glslc'):
        assert package in install.split()
    assert '-DGGML_VULKAN=ON' in vulkan_stage
    assert '-DLLAMA_BUILD_UI=OFF' in vulkan_stage
    assert 'cmake --build /build --target llama-server' in vulkan_stage
    assert 'npm' not in install.split()


@pytest.mark.parametrize('backend', ['cpu', 'cuda', 'rocm', 'vulkan'])
def test_real_manager_subprocess_backend_wiring(tmp_path, backend):
    from tests.runtime_fixture import runtime_service
    with runtime_service(tmp_path, hardware_backend=backend) as (client, _, process):
        status = client.status('ornith_rubric_draft')
        assert status['hardware']['backend'] == backend
        ready = client.start('ornith_rubric_draft')
        assert ready['hardware']['gpu_count'] == (0 if backend == 'cpu' else 2)
        assert ready['profile']['gpu_layers'] == (0 if backend == 'cpu' else 'auto')
        assert client.health('ornith_rubric_draft')['ok']
        client.stop('ornith_rubric_draft')
        assert process.poll() is None



def test_nvidia_without_toolkit_leaves_cpu_compose(tmp_path):
    helper = load_helper()
    (tmp_path / 'nvidia0').touch()
    def no_toolkit(*_, **__):
        return subprocess.CompletedProcess([], 0, '{"runc": {}}')
    cmd, _, messages = helper.compose_command(['config'], device_root=tmp_path, runner=no_toolkit)
    assert not any('nvidia.yaml' in arg for arg in cmd)
    assert any('not confirmed' in message for message in messages)


def test_permission_stderr_and_empty_enumeration_are_unusable(tmp_path):
    def permission(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, '', 'Permission denied opening /dev/dri/renderD128')
    h = HardwareSelection(BINARIES, runner=permission, device_root=tmp_path)
    assert h.capabilities['vulkan'].error_code == 'device_permission_denied'
    def empty(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, 'Available devices:', '')
    h = HardwareSelection(BINARIES, runner=empty, device_root=tmp_path)
    assert h.capabilities['vulkan'].error_code == 'gpu_not_accessible'
    assert h.select().backend == 'cpu'
    assert selection_status(h.select(), 'auto', 0)['fallback_reason'] == 'no_usable_gpu'
