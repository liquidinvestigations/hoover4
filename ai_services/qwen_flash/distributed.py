"""Start one tensor-parallel rank on the local direct-link interface."""

import fcntl
import os
from pathlib import Path
import socket
import struct
import sys
import urllib.request


def local_rank(addresses):
    local = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, interface in socket.if_nameindex():
            request = struct.pack("256s", interface.encode())
            try:
                info = fcntl.ioctl(sock.fileno(), 0x8915, request)  # SIOCGIFADDR
            except OSError:
                continue
            address = socket.inet_ntoa(info[20:24])
            if address in addresses:
                local.append((addresses.index(address), interface))
    if len(local) != 1:
        raise SystemExit("This host must own exactly one configured rank address.")
    return local[0]


def rdma_port(interface, address):
    for port in Path("/sys/class/infiniband").glob("*/ports/*"):
        for gid in (port / "gids").iterdir():
            # An IPv4-mapped GID identifies the IP and device on this port.
            if socket.inet_pton(socket.AF_INET6, gid.read_text().strip()) != (
                bytes(10) + b"\xff\xff" + socket.inet_aton(address)
            ):
                continue
            attrs = port / "gid_attrs"
            if ((attrs / "ndevs" / gid.name).read_text().strip() == interface
                    and (attrs / "types" / gid.name).read_text().strip() == "RoCE v2"):
                return f"={port.parents[1].name}:{port.name}", gid.name
    raise SystemExit("The rank interface needs a matching RoCE v2 GID.")


def main(args):
    env = os.environ
    if args == ["--health"]:
        url = f"http://{env['QWEN_API_HOST']}:{env['VLLM_PORT']}/health"
        with urllib.request.urlopen(url, timeout=5):
            return
    addresses = env["QWEN_RANK_ADDRESSES"].split(",")
    rank, interface = local_rank(addresses)
    address = addresses[rank]
    adapter, gid = rdma_port(interface, address)
    env.update(VLLM_HOST_IP=address, NCCL_SOCKET_IFNAME="=" + interface,
               GLOO_SOCKET_IFNAME=interface, NCCL_IB_HCA=adapter, NCCL_IB_GID_INDEX=gid)
    args += ["--tensor-parallel-size", "2", "--nnodes", "2", "--node-rank", str(rank),
             "--master-addr", addresses[0], "--master-port", env["QWEN_MASTER_PORT"],
             "--distributed-executor-backend", "mp", "--additional-config", '{"ple_table_memory":"disk"}']
    if rank:
        args.append("--headless")
    else:
        args[args.index("--host") + 1] = env["AI_BIND_IP"]
        args[args.index("--port") + 1] = env["VLLM_PORT"]
        key = env.get("HOOVER4_GPU_API_KEY") or Path("/run/secrets/gpu_api_key").read_text().strip()
        if not key:
            raise SystemExit("The model server requires a GPU API key.")
        env["VLLM_API_KEY"] = key
    print(f"Starting rank {rank} on {interface} with {adapter} and GID {gid}.", flush=True)
    os.execvp("vllm", ["vllm", "serve", *args])


if __name__ == "__main__":
    main(sys.argv[1:])
