#!/usr/bin/env bash
# Storage cleanup for Viral Shorts AI.
#
# HONEST SCOPE: this script can only delete what it can reach.
#   - S3 objects: needs S3_BUCKET + AWS credentials in the environment.
#                 Without them it lists what it *would* clean and exits.
#   - Local ./data: deleted directly (you own the disk).
#   - Docker volumes: only with your explicit confirmation (never automatic).
#   - Database rows: NOT deleted by this script - a commented SQL snippet
#                 below shows the query; run it yourself via psql.
#
# Usage:
#   ./scripts/cleanup.sh [DAYS]        # default DAYS=30, dry run
#   DRY_RUN=0 ./scripts/cleanup.sh 60  # actually delete objects older than 60 days
set -euo pipefail

cd "$(dirname "$0")/.."

DAYS="${1:-30}"
DRY_RUN="${DRY_RUN:-1}"

echo "=== Viral Shorts AI cleanup (older than ${DAYS} days, DRY_RUN=${DRY_RUN}) ==="
echo ""

# ---------------------------------------------------------------------------
# 1. What we would clean (always listed, even without credentials)
# ---------------------------------------------------------------------------
echo "Cleanup targets:"
echo "  - s3://\${S3_BUCKET}/uploads/raw/      original uploads older than ${DAYS}d"
echo "  - s3://\${S3_BUCKET}/renders/clips/    rendered shorts older than ${DAYS}d"
echo "  - ./data/tmp/                          local transcode scratch files"
echo "  - DB rows in jobs/clips               via SQL snippet below (manual step)"
echo ""

# ---------------------------------------------------------------------------
# 2. S3 cleanup - requires credentials; refuses to guess without them
# ---------------------------------------------------------------------------
if [ -z "${S3_BUCKET:-}" ]; then
  echo "S3_BUCKET is not set - cannot touch S3. Set S3_BUCKET (and AWS credentials)"
  echo "to enable S3 cleanup. Listing intent only; nothing was deleted."
  echo ""
else
  if ! command -v aws >/dev/null 2>&1; then
    echo "ERROR: 'aws' CLI not found but S3_BUCKET is set. Install awscli to proceed." >&2
    exit 1
  fi
  for PREFIX in "uploads/raw/" "renders/clips/"; do
    echo "--- s3://${S3_BUCKET}/${PREFIX} ---"
    CUTOFF=$(date -d "${DAYS} days ago" +%Y-%m-%d)
    echo "(objects with LastModified before ${CUTOFF})"
    if [ "$DRY_RUN" = "1" ]; then
      echo "DRY RUN - would delete:"
      aws s3 ls "s3://${S3_BUCKET}/${PREFIX}" --recursive || true
    else
      echo "Deleting objects older than ${DAYS} days..."
      # NOTE: aws s3 ls output parsing; for large buckets prefer S3 lifecycle
      # rules instead (see README 'Storage cleanup').
      aws s3 ls "s3://${S3_BUCKET}/${PREFIX}" --recursive | \
        awk -v cutoff="$CUTOFF" '$1 < cutoff {print $4}' | \
        while read -r key; do
          [ -n "$key" ] && aws s3 rm "s3://${S3_BUCKET}/${PREFIX}${key}"
        done
    fi
  done
fi
echo ""

# ---------------------------------------------------------------------------
# 3. Local scratch files
# ---------------------------------------------------------------------------
if [ -d ./data/tmp ]; then
  echo "--- ./data/tmp ---"
  if [ "$DRY_RUN" = "1" ]; then
    echo "DRY RUN - would delete files older than ${DAYS} days:"
    find ./data/tmp -type f -mtime "+${DAYS}" -print || true
  else
    find ./data/tmp -type f -mtime "+${DAYS}" -delete
    echo "Deleted local scratch files older than ${DAYS} days."
  fi
else
  echo "(no ./data/tmp directory - nothing local to clean)"
fi
echo ""

# ---------------------------------------------------------------------------
# 4. Docker volumes - guidance only, never automatic
# ---------------------------------------------------------------------------
cat <<'EOF'
--- Docker volumes ---
This script will NOT prune volumes automatically (that could delete the
database). If you need the disk space back, inspect first:

    docker volume ls
    docker system df -v

and remove only volumes you recognise, e.g.:

    docker volume rm <volume-name>
EOF
echo ""

# ---------------------------------------------------------------------------
# 5. Database rows - manual SQL snippet (run via psql yourself)
# ---------------------------------------------------------------------------
cat <<EOF
--- Database (manual step) ---
This script does not delete DB rows. To remove jobs/clips older than ${DAYS}
days, connect with psql and run:

    DELETE FROM clips WHERE created_at < NOW() - INTERVAL '${DAYS} days';
    DELETE FROM jobs  WHERE created_at < NOW() - INTERVAL '${DAYS} days';

(Adjust table/column names to match backend/app/models.py.)
EOF

echo ""
echo "Done. Re-run with DRY_RUN=0 to actually delete (S3 + local files)."
