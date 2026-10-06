# Tika configuration

`deploy.py` generates `tika-config.json` from `hoover4.ini` before it starts the main services.
The generated file is ignored by Git.

The service uses four parser processes by default, with one GiB of heap for each process.
The default container memory limit is six GiB.
The worker concurrency equals the parser process count.
Deployment fails when the memory limit cannot cover all parser heaps plus one GiB.

The server parses the outer document only.
Embedded document text needs a separate reader.
The output limit is 20,000,000 characters.
A reached output limit keeps the truncated text and its metadata flag.
