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

### Automad Assembly Sync
Synchronizes assembly guide pages from Automad CMS via SFTP (SSH File Transfer Protocol). Downloads complete folder structures including page metadata (.txt files) and media files, while automatically excluding pages marked as private.

**Usage:**
```yaml
# Download and run the sync script directly
- name: Install dependencies
  run: pip install paramiko

- name: Download sync script
  run: |
    curl -o sync-automad.py \
         https://raw.githubusercontent.com/mekanika-dev/data-sync-actions/main/automad/sync-automad-sftp.py

- name: Run Automad sync
  env:
    AUTOMAD_HOST: ${{ secrets.AUTOMAD_HOST }}
    AUTOMAD_USER: ${{ secrets.AUTOMAD_USER }}
    AUTOMAD_PASSWORD: ${{ secrets.AUTOMAD_PASSWORD }}
    AUTOMAD_PORT: ${{ secrets.AUTOMAD_PORT }}
    REMOTE_PATH: "/var/www/html/automad-master/pages/assembly"
    TARGET_PATH: "assembly"
  run: python sync-automad.py
```

**Required Secrets:**
- `AUTOMAD_HOST` - SFTP server hostname or IP
- `AUTOMAD_USER` - SSH username
- `AUTOMAD_PASSWORD` - SSH password
- `AUTOMAD_PORT` - SSH port (typically 22)

**Features:**
- Uses SFTP (more secure than FTP, leverages existing SSH server)
- Preserves complete folder/subfolder structure
- Skips pages marked with `private: on` in metadata
- Uses MD5 checksums to avoid re-downloading unchanged files
- Tracks sync state in `.sync-metadata.json`
