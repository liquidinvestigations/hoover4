# Hoover4 Frontend

The frontend is a Dioxus WASM application that provides the Hoover4 user interface. It uses server functions to call the backend APIs and shares types via the `common` crate.

## Structure

- `assets/` - Static assets and global styles.
- `src/main.rs` - Dioxus entry point and application launch configuration.
- `src/app.rs` - Application root component, layout, and router.
- `src/routes.rs` - Route definitions for search, document view, file browser, and chatbot pages.
- `src/pages/` - Page-level UI compositions.
- `src/components/` - Reusable UI building blocks.
- `src/api/` - Server functions that proxy to the backend crate.

## Development

From this directory:

```bash
dx serve --platform web
```

## Navigation

-  [Go Back](../Readme.md)

