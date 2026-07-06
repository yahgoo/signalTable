#!/bin/bash
# Run this on the VPS (via password SSH) to authorize your Mac's SSH key.
# After this, the agent can connect key-based without a password.
# Command: ssh ubuntu@43.156.46.66  (then paste and run this script)

PUB_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINugZMtAzDCGlRX7zTHmDbSAgiUc9lQ3bMnNSA5kvR81 kmsum"

mkdir -p ~/.ssh
chmod 700 ~/.ssh

if grep -qF "${PUB_KEY}" ~/.ssh/authorized_keys 2>/dev/null; then
  echo "Key already authorized."
else
  echo "${PUB_KEY}" >> ~/.ssh/authorized_keys
  chmod 600 ~/.ssh/authorized_keys
  echo "Key added to ~/.ssh/authorized_keys"
fi

echo "Test with: ssh -i ~/.ssh/id_ed25519 ubuntu@43.156.46.66 'echo success'"
