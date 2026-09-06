# Scenario DB web workspace

React/TypeScript SPA for pipeline, timeline, evidence, scenario browsing and
structured architecture queries. It supplements the Streamlit Workbench.

## Development

Use Node.js 24 and npm. Start the Scenario DB API on port 18000, then run:

```sh
npm ci
npm run dev
```

Vite serves the SPA on loopback port 5173 and proxies `/api` to the local API.
The backend still requires PostgreSQL and its normal runtime dependencies.

## Validation and serving

```sh
npm run lint
npm test
npm run build
```

Build output goes to `web/dist`. Restart FastAPI after building to enable its
optional `/` SPA entry point and `/assets` mount. `npm run preview` previews
static output; API forwarding is configured for the Vite development server.

Simulation runs require a selected variant, explicit execution conditions and
credentials when backend authentication is enabled. Runs are previews and are
not automatically saved. Do not embed server API secrets in build configuration.

See [navigation and saved-result links](../docs/guides/spa-navigation.md).
The prediction/measurement comparison tab remains unavailable in this SPA;
use the existing Streamlit dashboard for that workflow.
