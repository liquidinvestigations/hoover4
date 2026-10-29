# Vendored browser libraries

The frontend has no npm build. A browser library is a pinned file in this folder, and its
source and checksum are recorded here.

| File | Library | Source | SHA-256 |
|---|---|---|---|
| `tus.min.js` | tus-js-client 4.3.1, MIT licence (`tus.LICENSE`) | `dist/tus.min.js` of <https://registry.npmjs.org/tus-js-client/-/tus-js-client-4.3.1.tgz> | `8cbb1b63fccc3bba0ae73ad1deb160ce046c3750851d0c3e94921ae3ef070eb8` |

The npm registry gives the archive the integrity value
`sha512-ZLeYmjrkaU1fUsKbIi8JML52uAocjEZtBx4DKjRrqzrZa0O4MYwT6db+oqePlspV+FxXJAyFBc/L5gwUi2OFsg==`.
The archive has the SHA-256 `919f46808b2c689be9214df5c0f21879bee4a4599b34e212ada8f14de1db9bc0`.
The file is the unchanged bytes of the archive. Its last line names `tus.min.js.map`, which
is not copied, so a browser with open developer tools asks for it and gets 404.

To change the version, download the archive, compare its integrity value with the registry,
copy `package/dist/tus.min.js` and `package/LICENSE`, and change this table.
`website/frontend/assets/uploads.js` uses the `tus.Upload` options of this version.
