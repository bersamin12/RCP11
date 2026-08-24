/// <reference types="vite/client" />

// Required for the `?worker` import that constructs the pdf.js worker. Without
// it `tsc -b` -- the first half of `npm run build` -- cannot resolve the suffix.
