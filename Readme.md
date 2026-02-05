# Hoover4 Prototype

This repository contains the Hoover4 search engine prototype.


## Code

The layout of the code is as follows:
- `main_services` - definition of main databases and processing code. These require ample CPU and Disk resources.
- `ai_services` - definition of machine learning related services. These require GPU access with `nvidia-docker` on `GTX 3090` or later, with at least `24 GB` of dedicated video memory.
- `website` - the main website code. This is a full-stack Dioxus application that communicates with the services declared above.