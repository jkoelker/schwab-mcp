#!/usr/bin/env bash
#
# Deploy schwab-mcp services to Google Cloud Run.
#
# Usage:
#   ./deploy.sh [--mcp-only | --admin-only]
#
# Prerequisites:
#   - gcloud CLI authenticated and configured
#   - Docker or Podman available
#   - Cloud SQL instance already provisioned
#   - Required secrets stored in Google Secret Manager
#
# Environment variables (or edit the defaults below):
#   PROJECT_ID          - GCP project ID
#   REGION              - Cloud Run region (default: us-west1)
#   DB_INSTANCE         - Cloud SQL instance connection name
#   DB_PASSWORD_SECRET  - Secret Manager secret name for DB password
#   SCHWAB_CLIENT_ID_SECRET    - Secret for Schwab client ID
#   SCHWAB_CLIENT_SECRET_SECRET - Secret for Schwab client secret
#   MCP_OAUTH_SECRET           - Secret for MCP OAuth secret
#
set -euo pipefail

# --- Configuration ---
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-west1}"
DB_INSTANCE="${DB_INSTANCE:-}"
DB_NAME="${DB_NAME:-schwab_data}"
DB_USER="${DB_USER:-agent_user}"

# Secret Manager secret names (not the values!)
DB_PASSWORD_SECRET="${DB_PASSWORD_SECRET:-schwab-db-password}"
SCHWAB_CLIENT_ID_SECRET="${SCHWAB_CLIENT_ID_SECRET:-schwab-client-id}"
SCHWAB_CLIENT_SECRET_SECRET="${SCHWAB_CLIENT_SECRET_SECRET:-schwab-client-secret}"
MCP_OAUTH_SECRET="${MCP_OAUTH_SECRET:-schwab-mcp-oauth-secret}"

# Admin domain (used for Schwab callback URL)
ADMIN_DOMAIN="${ADMIN_DOMAIN:-}"

# Service names
MCP_SERVICE="schwab-mcp"
ADMIN_SERVICE="schwab-mcp-admin"

# --- Validation ---
if [[ -z "$PROJECT_ID" ]]; then
    echo "ERROR: PROJECT_ID is required. Set it or configure gcloud."
    exit 1
fi

if [[ -z "$DB_INSTANCE" ]]; then
    echo "ERROR: DB_INSTANCE is required (e.g., project:region:instance)."
    exit 1
fi

echo "=== Schwab MCP Cloud Run Deployment ==="
echo "Project:     $PROJECT_ID"
echo "Region:      $REGION"
echo "DB Instance: $DB_INSTANCE"
echo ""

# --- Helper ---

# gcloud run deploy --source uses the Dockerfile in the source directory.
# We copy the correct Dockerfile before each deploy and clean up after.
use_dockerfile() {
    local dockerfile="$1"
    cp "$dockerfile" Dockerfile
    trap 'rm -f Dockerfile' EXIT
}

deploy_mcp() {
    echo "--- Deploying MCP Server ($MCP_SERVICE) ---"

    use_dockerfile Dockerfile.mcp

    # Get the service URL after deploy for SERVER_URL env var
    # First deploy without it, then update
    gcloud run deploy "$MCP_SERVICE" \
        --source . \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --allow-unauthenticated \
        --port 8080 \
        --memory 512Mi \
        --timeout 300 \
        --max-instances 1 \
        --set-env-vars "SCHWAB_DB_INSTANCE=$DB_INSTANCE,SCHWAB_DB_NAME=$DB_NAME,SCHWAB_DB_USER=$DB_USER,JSON_OUTPUT=true" \
        --set-secrets "SCHWAB_CLIENT_ID=${SCHWAB_CLIENT_ID_SECRET}:latest,SCHWAB_CLIENT_SECRET=${SCHWAB_CLIENT_SECRET_SECRET}:latest,SCHWAB_DB_PASSWORD=${DB_PASSWORD_SECRET}:latest,MCP_OAUTH_CLIENT_SECRET=${MCP_OAUTH_SECRET}:latest" \
        --add-cloudsql-instances "$DB_INSTANCE"

    # Get the service URL and update SERVER_URL
    MCP_URL=$(gcloud run services describe "$MCP_SERVICE" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format 'value(status.url)')

    echo "MCP Server URL: $MCP_URL"

    # Update with the correct SERVER_URL
    gcloud run services update "$MCP_SERVICE" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --update-env-vars "SERVER_URL=$MCP_URL"

    echo "MCP Server deployed: $MCP_URL"
    echo ""
    echo "To connect from claude.ai, add this as a remote MCP server:"
    echo "  URL: ${MCP_URL}/mcp"
    echo ""
}

deploy_admin() {
    echo "--- Deploying Admin Service ($ADMIN_SERVICE) ---"

    use_dockerfile Dockerfile.admin

    # Determine callback URL upfront so the container can start.
    # On first deploy without ADMIN_DOMAIN, we use a placeholder and
    # update after the service URL is known.
    if [[ -n "$ADMIN_DOMAIN" ]]; then
        CALLBACK_URL="https://${ADMIN_DOMAIN}/datareceived"
    else
        # Check if service already exists to get its URL
        ADMIN_URL=$(gcloud run services describe "$ADMIN_SERVICE" \
            --project "$PROJECT_ID" \
            --region "$REGION" \
            --format 'value(status.url)' 2>/dev/null || true)
        if [[ -n "$ADMIN_URL" ]]; then
            CALLBACK_URL="${ADMIN_URL}/datareceived"
        else
            # First deploy: use a placeholder, will update after
            CALLBACK_URL="https://placeholder.invalid/datareceived"
        fi
    fi

    gcloud run deploy "$ADMIN_SERVICE" \
        --source . \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --no-allow-unauthenticated \
        --port 8080 \
        --memory 256Mi \
        --timeout 60 \
        --max-instances 1 \
        --set-env-vars "SCHWAB_DB_INSTANCE=$DB_INSTANCE,SCHWAB_DB_NAME=$DB_NAME,SCHWAB_DB_USER=$DB_USER,SCHWAB_CALLBACK_URL=$CALLBACK_URL" \
        --set-secrets "SCHWAB_CLIENT_ID=${SCHWAB_CLIENT_ID_SECRET}:latest,SCHWAB_CLIENT_SECRET=${SCHWAB_CLIENT_SECRET_SECRET}:latest,SCHWAB_DB_PASSWORD=${DB_PASSWORD_SECRET}:latest" \
        --add-cloudsql-instances "$DB_INSTANCE"

    ADMIN_URL=$(gcloud run services describe "$ADMIN_SERVICE" \
        --project "$PROJECT_ID" \
        --region "$REGION" \
        --format 'value(status.url)')

    echo "Admin Service deployed: $ADMIN_URL"

    # If we used a placeholder, update with the real URL now
    if [[ "$CALLBACK_URL" == *"placeholder.invalid"* ]]; then
        CALLBACK_URL="${ADMIN_URL}/datareceived"
        gcloud run services update "$ADMIN_SERVICE" \
            --project "$PROJECT_ID" \
            --region "$REGION" \
            --update-env-vars "SCHWAB_CALLBACK_URL=$CALLBACK_URL"
    fi

    echo ""
    echo "IMPORTANT: Update your Schwab Developer Portal callback URL to:"
    echo "  $CALLBACK_URL"
    echo ""
    echo "Admin dashboard: $ADMIN_URL"
    echo ""
}

# --- Main ---
case "${1:-all}" in
    --mcp-only)
        deploy_mcp
        ;;
    --admin-only)
        deploy_admin
        ;;
    all|"")
        deploy_admin
        deploy_mcp
        ;;
    *)
        echo "Usage: $0 [--mcp-only | --admin-only]"
        exit 1
        ;;
esac

echo "=== Deployment complete ==="
