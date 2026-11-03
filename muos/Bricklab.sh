#!/bin/bash
# Bricklab for muOS / PortMaster-family firmware: same folder as Brickchord.
BRICK_EDITION=lab exec "$(cd "$(dirname "$0")" && pwd)/Brickchord.sh"
