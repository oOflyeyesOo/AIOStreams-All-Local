# Deploy from a Docker management app

Use [compose.manager.yml](compose.manager.yml) for Portainer, Dockge or another
Docker Compose stack editor on a Linux **x86-64 / amd64** server or NAS. It uses
prebuilt images and named volumes: no Git checkout, source builds or host folders
are required. This is a Docker Standalone stack, not a Swarm or Kubernetes manifest.
ARM hosts are not currently covered by the published image set.

## Paste and deploy

1. Create a Compose stack named `aio-local` in your management app.
2. Paste the **entire** contents of `compose.manager.yml` into its editor.
3. Set `ADDON_PASSWORD` in the stack's environment settings. Use a password without
   quotes, dollar signs, hash characters or line breaks. The default is `admin`.
4. Deploy, then open `http://YOUR-SERVER:8088` and sign in as `admin`.
5. Enter your server address and provider keys in the portal, choose **Connect my
   stack**, and copy the manifest URL into your player.

First startup can take several minutes while services initialize and build
their caches. The setup controller allows up to ten minutes for service health
before reporting a startup failure.

The setup controller and portal maintenance tools mount the host Docker socket.
Both therefore have Docker-engine control. Protect portal credentials and keep its
port on a trusted network. See [COMPOSE.md](COMPOSE.md).

The controller applies settings to this Compose project only. Keep the project
name stable. Change provider keys in the portal; a manager redeploy initially uses
its own environment, so choose **Connect my stack** again after redeploying to
reapply saved keys.

## Image access and versions

Images are published under `ghcr.io/ooflyeyesoo/aio-local-*` with `latest` and
full commit-SHA tags. The six packaged images are `aiostreams`, `kitsu`, `portal`,
`bootstrap`, `controller`, and `postgres-init`. Wait for all six builds to succeed
before installing a new revision. Set `AIO_IMAGE_TAG` to a successful commit SHA to
keep all packaged components on the same release.

This repository is private. If its GHCR packages are private, add a GHCR registry
credential with read permission in your Docker management app before deployment.

| Setting | Default | Purpose |
| --- | --- | --- |
| `ADDON_PASSWORD` | `admin` | Master secret for portal authentication, protected endpoints, and internal AIOStreams access key |
| `PORT_PORTAL` | `8088` | Host port for the setup page |
| `AIO_IMAGE_TAG` | `latest` | Tag shared by packaged components |
| `AIO_IMAGE_PREFIX` | `ghcr.io/ooflyeyesoo/aio-local` | Image namespace, useful for forks/local builds |
| `INTERNAL_BIND_IP` | `127.0.0.1` | Bind internal dashboards and web players to a trusted LAN IP when needed |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | Host Docker socket path |

Do not run a source installation and a manager installation with the default
ports on the same host at the same time.

## Storage, updates and removal

`aio-config` stores saved settings and the packaged UI/Compose definition. Each
application has its own named data volume. Back up all volumes before upgrades.
Pull the new images, redeploy through your management app, then choose
**Connect my stack**. Upgrades refresh packaged files while preserving saved
provider keys and application data.

Stopping the stack stops its containers. Removing the stack without deleting
volumes keeps its data available for redeployment under the same project name.

## Stack profiles vs. Manager deployment

### Source Compose Profiles (`docker-compose.yml`)

When deploying from source, profiles let you run only the components you need:

- **`core`** (default lean stack): AIOStreams, AIOMetadata, Posters+, SubSense, Anime Kitsu, StremThru Store, LumiereDB, and backing databases/cache.
- **`scrapers`** (recommended for full indexing): Adds Prowlarr, Flaresolverr/Byparr, Zilean DMM hash cache, and InfiniDysk Usenet.
- **`tunnel`**: Automated Cloudflare Tunnel ingress (`cloudflared`).
- **`all`**: Activates all continuous services simultaneously.

### Packaged Manager Deployment (`compose.manager.yml`)

The packaged manager configuration automatically includes all continuous
microservices without profile flags, while allowing full host-port customization
via `PORT_<SERVICE>` environment variables.

## Source Compose option

Clone the repository and use `docker-compose.yml` for custom settings or local builds:

```sh
docker compose --profile scrapers up -d --build --remove-orphans
```

To build the manager images locally, tag all targets consistently:

```sh
for target in portal controller aiostreams bootstrap postgres-init; do
  docker build -f docker/packaged/Dockerfile --target "$target" -t "aio-local-$target:local" .
done
docker build -f docker/anime-kitsu/Dockerfile -t aio-local-kitsu:local .
AIO_IMAGE_PREFIX=aio-local AIO_IMAGE_TAG=local docker compose -f compose.manager.yml up -d
```

For maintainers, `python3 scripts/generate_manager_compose.py` regenerates the
manager configuration from the source stack (requires `PyYAML==6.0.3`).

## Host ports and firewall

Every published host port in `compose.manager.yml` can be set as `PORT_<SERVICE>`
(hyphens become underscores), including `PORT_LUMIEREDB`, `PORT_AIOSTREAMS`,
`PORT_AIOMETADATA`, and `PORT_PORTAL`. Cloudflare Tunnel remains disabled unless
its `tunnel` profile is selected and a token supplied.

Tracing tools (`tools/trace_proxy.py`, `tests/trace_requests.py`) are opt-in test
instruments, not deployed in the normal manager stack.
