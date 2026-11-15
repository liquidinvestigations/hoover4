#!/usr/bin/env python3
"""Run SQL from stdin as the admin in a shared Manticore daemon of the site (shared.py). The password stays in the pod
environment. MT_STORE names the daemon, manticore (the default) or manticore-vectors.
Usage: mt.py admin
"""
import os, sys
import shared

STORE = os.environ.get('MT_STORE', 'manticore')

if __name__ == '__main__':
    if sys.argv[1:] != ['admin'] or STORE not in shared.MANTICORE:
        sys.exit(__doc__)
    sys.stdout.write(shared.manticore_sql(STORE, sys.stdin.read()))
