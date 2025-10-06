# Data Sync Actions

Reusable GitHub Actions for synchronizing data from external sources to repositories.

## Available Actions

### 🗄️ Google Drive Sync
Synchronizes files from Google Drive folders to your repository.

**Usage:**
```yaml
- uses: mekanika-dev/data-sync-actions/google-drive@main
```

**Required Secrets:**
- `GOOGLE_DRIVE_CREDENTIALS` - Service account JSON
- `DRIVE_DOCS_FOLDER_ID` - Google Drive folder ID

### 📋 Odoo BOM Sync
Synchronizes Bill of Materials from Odoo ERP to your repository.

**Usage:**
```yaml
- uses: mekanika-dev/data-sync-actions/odoo@main
  with:
    bom_reference: 'M01424'
    output_path: 'bom/M01424.csv'
  env:
    ODOO_URL: ${{ secrets.ODOO_URL }}
    ODOO_DB: ${{ secrets.ODOO_DB }}
    ODOO_USERNAME: ${{ secrets.ODOO_USERNAME }}
    ODOO_API_KEY: ${{ secrets.ODOO_API_KEY }}
```

**Required Organization Secrets:**
- `ODOO_URL` - Odoo server URL
- `ODOO_DB` - Database name
- `ODOO_USERNAME` - Username
- `ODOO_API_KEY` - API key for authentication

**Inputs:**
- `bom_reference` (required) - Product reference to fetch BOM for
- `output_path` (optional) - Output path for CSV file (default: 'bom_export.csv')
- `filter_packaging` (optional) - Filter out packaging components (default: 'true')

## Features

- **Prefix-based file replacement** - Files with same 5-char prefix get replaced
- **Metadata tracking** - Avoids unnecessary re-downloads
- **Structure preservation** - Maintains folder hierarchy
- **Error handling** - Comprehensive logging and error reporting

## Setup

1. Make this repository public
2. Configure organization secrets
3. Use actions in your workflows

For detailed examples, see individual action directories.