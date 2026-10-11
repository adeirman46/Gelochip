#!/bin/sh
# Start (or restart) the pandachip-eda IIC-OSIC-TOOLS container.
# PandaChip is mounted at an identical path inside the container so the
# toolbin/ wrappers can pass file paths through unchanged.
set -e
PANDACHIP_ROOT=$(cd "$(dirname "$0")/.." && pwd)
IMAGE=${PANDACHIP_EDA_IMAGE:-hpretl/iic-osic-tools:latest}

docker rm -f pandachip-eda 2>/dev/null || true
docker run -d --name pandachip-eda \
  --restart unless-stopped \
  --network host \
  --user "$(id -u):$(id -g)" \
  -e DISPLAY="${DISPLAY:-:0}" \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v "$PANDACHIP_ROOT:$PANDACHIP_ROOT" \
  -v "$PANDACHIP_ROOT:/home/irman/pandachip" \
  -v /tmp/claude-1000:/tmp/claude-1000 \
  --entrypoint /bin/bash \
  "$IMAGE" -c "sleep infinity"

# Allow the container (same uid, local socket) to open windows on this display
DISPLAY="${DISPLAY:-:0}" xhost +SI:localuser:"$(id -un)" +local: >/dev/null 2>&1 || true
echo "pandachip-eda container running ($IMAGE)"
