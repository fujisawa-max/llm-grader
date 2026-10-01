#!/usr/bin/env python3
"""Host-side GPU exposure selection. Does not run models or change Docker configuration."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def amd_render_devices(device_root, sys_root):
    """A DRM render node is vendor-neutral; select only PCI vendor 0x1002 (AMD)."""
    devices = []
    for device in sorted((device_root / 'dri').glob('renderD*')):
        vendor_file = sys_root / 'class/drm' / device.name / 'device/vendor'
        try:
            vendor = int(vendor_file.read_text().strip(), 16)
        except (OSError, ValueError):
            continue
        if vendor == 0x1002:
            devices.append(device)
    return devices


def compose_command(arguments, *, device_root=Path('/dev'), sys_root=Path('/sys'),
                    runner=subprocess.run):
    env = dict(os.environ)
    files = ['compose.yaml']
    messages = []
    if list(device_root.glob('nvidia[0-9]*')):
        try:
            info = runner(['docker', 'info', '--format', '{{json .Runtimes}}'],
                          check=True, capture_output=True, text=True, timeout=15)
            available = 'nvidia' in json.loads(info.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            available = False
        if available:
            files.append('compose.runtime-nvidia.yaml')
            messages.append('NVIDIA Toolkit runtime detected: exposing all GPUs.')
        else:
            messages.append('NVIDIA device found but Toolkit runtime not confirmed; no GPU reservation requested.')
    # NVIDIA wins even if it exposes DRM nodes or another GPU is also installed.
    render = [] if 'compose.runtime-nvidia.yaml' in files else amd_render_devices(device_root, sys_root)
    if render:
        groups = {path.stat().st_gid for path in render}
        if len(groups) != 1:
            raise RuntimeError('Render nodes use different groups; use an explicit deployment override.')
        env['GPU_RENDER_GID'] = str(groups.pop())
        files.append('compose.runtime-amd.yaml')
        kfd = device_root / 'kfd'
        if kfd.exists():
            env['GPU_KFD_GID'] = str(kfd.stat().st_gid)
            files.append('compose.runtime-rocm.yaml')
        messages.append('AMD DRM render devices detected: exposing GPU devices with their host groups.')
    if len(files) == 1:
        messages.append('No GPU exposure selected; RuntimeManager remains CPU-capable.')
    command = ['docker', 'compose', '--project-directory', str(ROOT)]
    for file in files:
        command += ['-f', str(ROOT / file)]
    return command + arguments, env, messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('compose_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.compose_args
    if arguments[:1] == ['--']:
        arguments = arguments[1:]
    command, env, messages = compose_command(arguments or ['up', '-d', '--build'])
    for message in messages:
        print(message, file=sys.stderr)
    if args.dry_run:
        print(shlex.join(command))
        for name in ('GPU_RENDER_GID', 'GPU_KFD_GID'):
            if name in env:
                print(f'{name}={env[name]}')
    else:
        raise SystemExit(subprocess.run(command, env=env, cwd=ROOT).returncode)


if __name__ == '__main__':
    main()
