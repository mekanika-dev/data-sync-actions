# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository provides reusable GitHub Actions for synchronizing data from external sources (Google Drive, Odoo ERP) to repositories. The actions are designed to be used as composite actions in GitHub workflows.

## Key Components

### Google Drive Sync (`google-drive/sync-drive.py`)
- Synchronizes files from Google Drive folders to repositories
- Uses 5-character prefix matching for file replacement (e.g., "M0142_report.pdf" replaces "M0142_old.pdf")
- Tracks metadata to avoid unnecessary re-downloads
- Preserves folder structure from Google Drive

### Odoo BOM Sync (`odoo/sync-odoo.py`)
- Fetches Bill of Materials data from Odoo ERP via XML-RPC
- Exports to CSV format with hierarchical structure
- Includes circular reference protection
- Optional HTML viewer (`odoo/bom_viewer.html`) for visualization

## Common Development Tasks

### Running the sync scripts locally:

```bash
# Google Drive sync
python google-drive/sync-drive.py \
  --credentials-json "$GOOGLE_CREDENTIALS_JSON" \
  --folder-id "YOUR_FOLDER_ID" \
  --output-path "./output" \
  --prefix-replace \
  --file-types "pdf,docx,xlsx"

# Odoo BOM sync (using environment variables)
export ODOO_URL="https://erp.example.com"
export ODOO_DB="database_name"
export ODOO_USERNAME="user@example.com"
export ODOO_API_KEY="api_key_here"

python odoo/sync-odoo.py \
  --reference "PROD-001" \
  --output "bom_export.csv"
```

### Testing changes:
- No formal test suite exists; test scripts manually with sample data
- Verify Google Drive authentication with service account credentials
- Test Odoo connection with environment variables or credentials file

## Architecture Notes

- Each integration is self-contained in its directory with its own `action.yml`
- Scripts are designed to run independently in GitHub Actions environment
- Authentication uses environment variables in production (organization secrets in GitHub)
- File replacement logic uses prefix matching (first 5 characters) rather than exact filename matching
- Metadata tracking prevents unnecessary re-downloads from Google Drive

## GitHub Actions Structure

Each action follows this pattern:
1. `action.yml` in the subdirectory defines the composite action
2. Python script is downloaded from the main branch during workflow execution
3. Credentials are passed via environment variables from organization secrets
4. Changes are automatically committed and pushed back to the repository

## Important Implementation Details

- Google Drive sync requires service account JSON credentials
- Odoo sync uses XML-RPC with API key authentication
- Both scripts are designed to fail gracefully with clear error messages
- The `shared/` directory is reserved for future common utilities but currently empty
- Odoo script supports both environment variables and local credentials file for flexibility