#!/usr/bin/env python3
"""Run a shell script in a Kata guest through the agent debug console and print its output.

The guest must run with the kernel parameters agent.debug_console and agent.debug_console_vport=1026.
Usage (as root): guest-console.py <sandbox id> <script file>
"""
import socket, sys, time

sandbox, script = sys.argv[1], open(sys.argv[2], 'rb').read()
s = socket.socket(socket.AF_UNIX)
s.settimeout(30)
s.connect(f'/run/kata/{sandbox}/ch-vm.sock')
s.sendall(b'CONNECT 1026\n')
reply = s.recv(64)
if not reply.startswith(b'OK'):
    raise SystemExit(f'debug console refused the connection: {reply!r}')
s.sendall(b"sh -s <<'GUEST_SCRIPT_END'\n" + script + b"\nGUEST_SCRIPT_END\nexit\n")
output, deadline = b'', time.time() + 60
while time.time() < deadline:
    try:
        chunk = s.recv(65536)
    except socket.timeout:
        break
    if not chunk:
        break
    output += chunk
sys.stdout.write(output.decode(errors='replace'))
