"""Send data to a command in a container through `kubectl exec -i` without an end of input. Standard library only.

In a Kata container the output of `kubectl exec -i` stops after 32 KiB once the client closes the standard input
(measured with the Kata runtime of the site: the command then waits until a timeout). The output is complete while
the standard input stays open. run() therefore never closes the standard input. The command in the container reads
exactly the number of bytes that run() sends (head -c), so it sees the end of its input there, and kubectl ends when
the command ends. The same function works in gVisor and runc containers.
"""
import os
import shutil
import subprocess

# The wrapper reads the size from its first argument, and runs the command of the other arguments with exactly that
# many bytes on its standard input.
WRAPPER = 'size=$1; shift; head -c "$size" | "$@"'


def size_of(parts):
    """The byte count of parts: bytes, or paths of files."""
    return sum(len(p) if isinstance(p, (bytes, bytearray)) else os.path.getsize(p) for p in parts)


def run(kubectl_exec, command, parts=(), stdout=None, stderr=None, size=None):
    """Run command (argv in the container) through kubectl_exec (the kubectl argv up to and without `--`, with -i) and
    write parts to its standard input. parts are bytes or paths of files, or an iterable of byte chunks when size
    gives their total. stdout and stderr are open files or None for no output. Return the exit code."""
    total = size_of(parts) if size is None else size
    argv = [*kubectl_exec, '--', 'sh', '-c', WRAPPER, 'podexec', str(total), *command]
    process = subprocess.Popen([str(a) for a in argv], stdin=subprocess.PIPE,
                               stdout=stdout if stdout is not None else subprocess.DEVNULL,
                               stderr=stderr if stderr is not None else subprocess.DEVNULL)
    try:
        for part in parts:
            if isinstance(part, (bytes, bytearray)):
                process.stdin.write(part)
            else:
                with open(part, 'rb') as source:
                    shutil.copyfileobj(source, process.stdin, 1 << 20)
        process.stdin.flush()
    except BrokenPipeError:
        pass
    code = process.wait()
    try:
        process.stdin.close()
    except BrokenPipeError:
        pass
    return code
