# Deployment

How to serve the platform to someone who is not sitting at this machine.

## Decide the exposure first

This is the choice everything else hangs on, so make it deliberately.

| | Who can reach it | What they must install | Security posture |
|---|---|---|---|
| **`tailscale serve`** | Only devices in your tailnet | Tailscale, on their device | Authenticated at the network layer. No public surface at all. |
| **`tailscale funnel`** | Anyone on the internet who knows the URL | Nothing — any browser | A shared password is the *only* control. |

**Prefer `tailscale serve`.** It is one word different in the command and it removes
the entire public attack surface. Funnel is the right answer only when "they must be
able to open a link on any device without installing anything" is a hard requirement —
for example a reviewer who cannot install software on a managed laptop.

If you use Funnel, understand what it publishes: the hostname is issued a public TLS
certificate, and every certificate is recorded in Certificate Transparency logs within
minutes. **The URL is not a secret and is trivially discoverable.** Do not treat it as
a control.

Either way, configure the password. The auth layer is defence in depth under `serve`
and the only defence under `funnel`.

## What the shared password does and does not do

It does: keep anonymous visitors out of the API and the UI.

It does **not**:

- **Identify anyone.** Everyone uses one credential, so nothing in `data/runs/`, the
  annotations, or the evaluation scorecards can attribute an action to a person.
  `reviewer_id` in the rubric remains a self-declared string — see `docs/EVALUATION.md`.
  Being "behind a login" does not make the blinding enforceable.
- **Rate-limit anything.** There is no lockout and no throttle. Password length is the
  entire defence against online guessing, which is why `rcp serve` refuses anything
  shorter than 16 characters.
- **Cap spending.** `POST /api/runs` consumes OpenRouter credits with no quota.
- **Contain a breach.** The service account is in the `docker` group, which is
  root-equivalent on this host. Treat public exposure as temporary.

There is also no logout: browsers cache Basic credentials until every window is closed.

## First-time setup

```bash
# 1. Build the web UI. Without this the API serves no frontend and simply 404s /,
#    silently -- src/rcp/api/main.py mounts webapp/dist only if it exists.
cd webapp && npm ci && npm run build && cd ..

# 2. Set a password and lock the file down. .env is mode 664 by default and is
#    about to hold this alongside OPENROUTER_API_KEY.
echo "RCP_AUTH_PASSWORD=$(openssl rand -base64 24)" >> .env
chmod 600 .env

# 3. Confirm the preflight checks pass.
.venv/bin/rcp doctor          # the "api auth" row should read "configured"

# 4. Install the service.
sudo cp deploy/rcp.service /etc/systemd/system/rcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now rcp
journalctl -u rcp -f
```

Verify locally before exposing anything:

```bash
curl -i   http://127.0.0.1:8000/api/health     # expect 401 + WWW-Authenticate
curl -s -u rcp:<password> http://127.0.0.1:8000/api/health | head -c 60   # expect {"ok":true...
```

## Publishing

Tailnet-only:

```bash
sudo tailscale serve --bg 8000
```

Public:

```bash
sudo tailscale funnel --bg 8000
tailscale funnel status
```

Funnel needs three things enabled first, none of which are on by default:

1. **MagicDNS** and **HTTPS certificates** for the tailnet, in the admin console.
2. The **`funnel` node attribute** granted to this machine in the tailnet policy file
   (`nodeAttrs` → `"attr": ["funnel"]`). The first `tailscale funnel` run prints the
   exact link.
3. `sudo`, unless you set `tailscale set --operator=$USER`.

Funnel's public side accepts only ports 443, 8443 and 10000; `funnel 8000` maps local
8000 to public 443. Unlike `serve`, Funnel forwards **no identity headers** — the
traffic is anonymous, which is why the password is not optional.

## Tearing it down

```bash
sudo tailscale funnel reset      # stop publishing (do this as soon as the review ends)
sudo systemctl stop rcp
```

## Things that will look like bugs but are not

- **A restart abandons in-flight runs.** `RunManager` keeps live run state in process.
  The `data/runs/<id>/` directory survives, so after a crash or `systemctl restart` the
  UI shows those runs frozen at their last status. They cannot be resumed.
- **One worker, always.** For the same reason, never add `--workers` to the unit file.
  `rcp serve` passes uvicorn an app object rather than an import string specifically so
  that uvicorn rejects a worker count.
- **PDFs load slowly over Funnel.** Traffic is relayed through Tailscale's
  infrastructure, and the reader currently downloads a whole PDF before painting page 1
  (`disableRange`/`disableStream` in `webapp/src/components/pdf/pdfEngine.ts`). The
  backend serves byte ranges correctly; those two flags are what to revisit.
- **Do not add `--forwarded-allow-ips='*'` to uvicorn.** `proxy_headers` is already on
  and defaults to trusting loopback, which is exactly where Tailscale's proxy connects
  from. Widening it would let anyone spoof the client IP in your logs.

## Hardening the unit file further

`deploy/rcp.service` already sets `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`
and `ReadWritePaths`. Do **not** add these without testing a full simulation afterwards:

- `ProtectSystem=strict` — `data/` becomes read-only, `data_dir()`'s `mkdir` fails, and
  every run dies.
- `ProtectHome=yes` — hides `~/.docker/config.json`, breaking the docker CLI that the
  OpenModelica backend shells out to.
- `PrivateNetwork=yes` — no OpenRouter, no OpenAlex.

Failures from these surface only when a run reaches `run_modelica`, potentially twenty
minutes in.
