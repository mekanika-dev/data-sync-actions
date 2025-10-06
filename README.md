# Data Sync Actions

Reusable GitHub Actions for synchronizing data from external sources to repositories.

## Available Actions

### Google Drive Sync
Synchronizes files from Google Drive folders to your repository.

**Usage:**
```yaml
- uses: mekanika-dev/data-sync-actions/google-drive@main
```

**Required Secrets:**
- `GOOGLE_DRIVE_CREDENTIALS` - Service account JSON
- `DRIVE_DOCS_FOLDER_ID` - Google Drive folder ID

### Odoo BOM Sync
Synchronizes Bill of Materials from Odoo ERP to your repository. 

**Usage:**
```yaml
- uses: mekanika-dev/data-sync-actions/odoo@main 
```

**Required Secrets:**
- `ODOO_URL` - Odoo server URL
- `ODOO_DB` - Database name
- `ODOO_USERNAME` - Username
- `ODOO_API_KEY` - API key for authentication

Note: this script is very specific to Mekanika BoM naming and hierarchy.
