# Hoover4 Website

This project is a full-stack Dioxus application in 3 parts:

- `frontend` - client interface that compiles to WASM and is deployed on browsers
- `backend` - server code running on x64 architectures
- `common` - definitions of shared API structures and constants

### Deployment

For development deployment, first deploy the `ai_services` and `main_services`. Then, fill out the network IPs where these are hosted in `.env.development`. See `.env.development.example` for required keys.