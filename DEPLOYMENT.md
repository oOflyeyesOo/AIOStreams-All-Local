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

First startup can take several minutes while Comet and the other services build
their caches. The setup controller allows up to ten minutes for service health
before reporting a startup failure.

Portainer's [Web editor instructions](https://docs.portainer.io/user/docker/stacks/add)
describe where to paste the file. In Dockge, choose **Compose** to create a stack,
paste the same file, add environment values and deploy. Other Compose editors can
use the same file; product-specific UI paths may differ.

The Docker socket is required by the setup controller. It can control the host
Docker engine, as described in [COMPOSE.md](COMPOSE.md). Only the controller mounts
that socket; the portal talks to it through a separate local Unix socket. No
privileged container or nested Docker daemon is needed for this deployment.

The controller applies settings to this Compose project only. Keep the project
name stable. Change provider keys in the portal; a manager redeploy initially uses
its own environment, so choose **Connect my stack** again after redeploying to
reapply saved keys. Editing arbitrary service settings in the manager is not
persisted by the setup button, which uses the packaged Compose definition. Use
the source deployment for custom Compose definitions.

## Image access and versions

Images are built by [Build Docker manager images](../../actions/workflows/build-manager-images.yml)
on pushes to `main`. Wait for **all eight builds** to succeed before installing a
new revision. They are published under `ghcr.io/ooflyeyesoo/aio-local-*` with
`latest` and full commit-SHA tags. Set `AIO_IMAGE_TAG` to a successful commit SHA to
keep all packaged components on the same release. Upstream services still use
their own image tags, usually `latest`.

This repository is private. If its GHCR packages are private, add a GHCR registry
credential with permission to read those packages in your Docker management app
before deployment. Publishing a workflow does not make packages publicly readable.
The source deployment below remains available without these packaged images.

| Setting | Default | Purpose |
| --- | --- | --- |
| `ADDON_PASSWORD` | `admin` | Portal and local application password |
| `PORT_PORTAL` | `8088` | Host port for the setup page |
| `AIO_IMAGE_TAG` | `latest` | Tag shared by packaged components |
| `AIO_IMAGE_PREFIX` | `ghcr.io/ooflyeyesoo/aio-local` | Image namespace, useful for forks/local builds |
| `INTERNAL_BIND_IP` | `127.0.0.1` | Bind internal dashboards and web players to a trusted LAN IP when needed |
| `DOCKER_SOCKET` | `/var/run/docker.sock` | Host Docker socket path |

Do not run a source installation and a manager installation with the default
ports on the same host at the same time. The full stack also publishes service
ports listed in the Compose file, including 3001, 8082 and 8085.

## Storage, updates and removal

`aio-config` stores saved settings and the packaged UI/Compose definition. Each
application has its own named data volume. Docker prefixes the volume names with
your stack name. Back up all these volumes before upgrades. Do not remove volumes
when recreating the stack. Pull the new images, redeploy through your management
app, then choose **Connect my stack**. Upgrades refresh packaged files while
preserving saved provider keys and application data.

Stopping the stack stops its containers. Removing the stack without deleting
volumes keeps its data available for redeployment under the same project name.
Existing checkout-based installations use bind-mounted `data/` and `.env`; they
are not automatically migrated into named volumes. Keep that installation until
you have backed it up and deliberately migrated its data.

## Source Compose option

For custom settings or building locally, clone/download the repository into your
server's stack folder and use `docker-compose.yml`:

```sh
docker compose --profile all up -d --build --remove-orphans
```

Dockge can manage this folder directly when it is inside its configured stacks
directory. The source file needs the rest of the repository beside it; pasting it
alone into an editor will not supply its scripts. `--remove-orphans` also removes
the retired Hidden Cinemeta container from this project.

To build the manager images locally, tag all targets consistently:

```sh
for target in portal controller aiostreams sootio stremio-web bootstrap postgres-init; do
  docker build -f docker/packaged/Dockerfile --target "$target" -t "aio-local-$target:local" .
done
docker build -f docker/anime-kitsu/Dockerfile -t aio-local-kitsu:local .
AIO_IMAGE_PREFIX=aio-local AIO_IMAGE_TAG=local docker compose -f compose.manager.yml up -d
```

For maintainers, `python3 scripts/generate_manager_compose.py` regenerates the
manager configuration from the source stack (requires `PyYAML==6.0.3`). CI checks
that the committed generated file is current.

## Optional Cinemeta tool

[Hidden Cinemeta](https://hidden-cinemeta.vercel.app/) is linked from the portal.
It is an external, optional tool; this project no longer builds, starts or polls
a Hidden Cinemeta server.
