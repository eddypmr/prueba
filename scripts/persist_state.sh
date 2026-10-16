#!/usr/bin/env bash
set -euo pipefail

if git diff --quiet -- state.json; then
  echo "Sin cambios de estado que guardar."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# El archivo temporal sobrevive a git reset; los cambios solo son enviados
# por Telegram cuando el push que guarda la cola se ha confirmado.
cp state.json /tmp/onepiece_local_state.json

for attempt in 1 2 3; do
  git fetch origin main
  git show origin/main:state.json > /tmp/onepiece_remote_state.json 2>/dev/null \
    || echo '{}' > /tmp/onepiece_remote_state.json

  python merge_state.py \
    --local /tmp/onepiece_local_state.json \
    --remote /tmp/onepiece_remote_state.json \
    --output /tmp/onepiece_merged_state.json

  git reset --hard origin/main
  cp /tmp/onepiece_merged_state.json state.json

  if git diff --quiet -- state.json; then
    echo "La rama remota ya contiene estos cambios."
    exit 0
  fi

  git add state.json
  git commit -m "chore: persist stock state and Telegram outbox [skip ci]"

  if git push origin HEAD:main; then
    echo "Estado y cola guardados en GitHub."
    exit 0
  fi

  echo "Colisión en el push: reintentando fusión ($attempt/3)."
  cp state.json /tmp/onepiece_local_state.json
  sleep 2
done

echo "No se pudo confirmar el guardado de state.json: NO enviar avisos."
exit 1
