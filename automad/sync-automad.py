#!/usr/bin/env python3
"""
Automad to GitHub Sync Script
Synchronizes assembly guide pages from Automad CMS via FTP
Preserves folder structure and tracks metadata to avoid unnecessary re-downloads
"""

import os
import json
import ftplib
import hashlib
import io
import re
from pathlib import Path
from datetime import datetime


def calculate_md5(file_path):
    """Calculate MD5 hash of a file"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def connect_ftp(host, user, password, port=21):
    """Connect to FTP server"""
    print(f"🔌 Connecting to {host}:{port}...")

    ftp = ftplib.FTP()
    ftp.connect(host, port)
    ftp.login(user, password)

    print(f"✅ Connected to FTP server")
    return ftp


def list_ftp_contents(ftp, path="/"):
    """
    Recursively list all files and directories in FTP path
    Returns: list of tuples (file_path, is_directory, size, modified_time)
    """
    items = []

    try:
        ftp.cwd(path)
    except ftplib.error_perm:
        print(f"⚠️  Cannot access {path}")
        return items

    try:
        # List directory contents
        lines = []
        ftp.dir(lines.append)

        for line in lines:
            # Parse FTP directory listing (Unix-style)
            parts = line.split(None, 8)
            if len(parts) < 9:
                continue

            permissions = parts[0]
            size = parts[4]
            # Modified time is in parts[5:8]
            name = parts[8]

            # Skip . and ..
            if name in ['.', '..']:
                continue

            is_directory = permissions.startswith('d')
            item_path = f"{path}/{name}" if path != "/" else f"/{name}"
            item_path = item_path.replace('//', '/')

            if is_directory:
                items.append((item_path, True, 0, None))
                # Recursively list subdirectories
                sub_items = list_ftp_contents(ftp, item_path)
                items.extend(sub_items)
            else:
                # Try to get file size
                try:
                    file_size = int(size)
                except ValueError:
                    file_size = 0

                items.append((item_path, False, file_size, None))

    except ftplib.error_perm as e:
        print(f"⚠️  Permission error listing {path}: {e}")

    return items


def download_file(ftp, remote_path, local_path):
    """Download a file from FTP server"""
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(local_path, 'wb') as f:
            ftp.retrbinary(f'RETR {remote_path}', f.write)
        return True
    except ftplib.error_perm as e:
        print(f"❌ Error downloading {remote_path}: {e}")
        return False


def download_file_to_memory(ftp, remote_path):
    """Download a file from FTP server to memory"""
    try:
        buffer = io.BytesIO()
        ftp.retrbinary(f'RETR {remote_path}', buffer.write)
        buffer.seek(0)
        return buffer.read()
    except ftplib.error_perm as e:
        print(f"⚠️  Error reading {remote_path}: {e}")
        return None


def is_private_page(content):
    """
    Check if an Automad page is marked as private
    Looks for 'private: on' in the metadata section
    """
    if not content:
        return False

    try:
        text = content.decode('utf-8', errors='ignore')
        # Look for 'private: on' (case insensitive, with flexible whitespace)
        pattern = r'(?i)^\s*private\s*:\s*on\s*$'
        return bool(re.search(pattern, text, re.MULTILINE))
    except Exception as e:
        print(f"⚠️  Error parsing page content: {e}")
        return False


def identify_private_folders(ftp, files, remote_base_path):
    """
    Identify folders that contain private pages
    Returns: set of folder paths to exclude
    """
    private_folders = set()

    # Group files by folder
    txt_files = [(path, size) for path, size in files if path.endswith('.txt')]

    print(f"🔍 Checking {len(txt_files)} pages for private status...")

    for remote_path, _ in txt_files:
        # Get folder path
        folder_path = str(Path(remote_path).parent)

        # Download and check if private
        content = download_file_to_memory(ftp, remote_path)
        if content and is_private_page(content):
            # Calculate relative folder path
            if folder_path.startswith(remote_base_path):
                relative_folder = folder_path[len(remote_base_path):].lstrip('/')
            else:
                relative_folder = folder_path.lstrip('/')

            private_folders.add(relative_folder)
            print(f"🔒 Skipping private page: {relative_folder}")

    return private_folders


def load_metadata(target_path):
    """Load sync metadata from previous run"""
    metadata_file = Path(target_path) / '.sync-metadata.json'
    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            return json.load(f)
    return {'files': {}, 'config': {}}


def save_metadata(metadata, target_path):
    """Save sync metadata"""
    metadata_file = Path(target_path) / '.sync-metadata.json'
    metadata_file.parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)


def sync_automad_files(ftp, remote_base_path, local_base_path, metadata):
    """
    Sync files from Automad FTP to local directory

    Args:
        ftp: FTP connection
        remote_base_path: Remote path on FTP server (e.g., /pages/assembly)
        local_base_path: Local directory to sync to
        metadata: Metadata dict to track file changes
    """
    local_base_path = Path(local_base_path)
    local_base_path.mkdir(parents=True, exist_ok=True)

    print(f"📋 Listing files from {remote_base_path}...")

    # List all files on FTP server
    all_items = list_ftp_contents(ftp, remote_base_path)

    # Filter for files only (not directories)
    files = [(path, size) for path, is_dir, size, mtime in all_items if not is_dir]

    print(f"📁 Found {len(files)} files")

    # Identify private folders to exclude
    private_folders = identify_private_folders(ftp, files, remote_base_path)

    # Statistics
    synced = 0
    skipped = 0
    private_skipped = 0

    for remote_path, size in files:
        # Calculate relative path
        if remote_path.startswith(remote_base_path):
            relative_path = remote_path[len(remote_base_path):].lstrip('/')
        else:
            relative_path = remote_path.lstrip('/')

        # Check if this file is in a private folder
        relative_folder = str(Path(relative_path).parent)
        is_in_private_folder = False

        # Check if file is in any private folder or subfolder
        for private_folder in private_folders:
            if relative_folder == private_folder or relative_folder.startswith(private_folder + '/'):
                is_in_private_folder = True
                break

        if is_in_private_folder:
            private_skipped += 1
            continue

        local_path = local_base_path / relative_path

        # Check if file needs to be downloaded
        needs_download = True

        if local_path.exists():
            # File exists - check metadata
            if relative_path in metadata['files']:
                stored_size = metadata['files'][relative_path].get('size')
                stored_md5 = metadata['files'][relative_path].get('md5')

                # If size matches and we have MD5, verify it
                if stored_size == size and stored_md5:
                    current_md5 = calculate_md5(local_path)
                    if current_md5 == stored_md5:
                        print(f"⏭️  Identical: {relative_path}")
                        skipped += 1
                        needs_download = False

        if needs_download:
            print(f"⬇️  Downloading: {relative_path}")
            if download_file(ftp, remote_path, local_path):
                synced += 1

                # Calculate MD5 for downloaded file
                md5_hash = calculate_md5(local_path)

                # Update metadata
                metadata['files'][relative_path] = {
                    'size': size,
                    'md5': md5_hash,
                    'synced_at': datetime.now().isoformat()
                }
            else:
                print(f"❌ Failed to download: {relative_path}")

    return synced, skipped, private_skipped


def main():
    # Configuration from environment variables
    host = os.environ.get('AUTOMAD_HOST')
    user = os.environ.get('AUTOMAD_USER')
    password = os.environ.get('AUTOMAD_PASSWORD')
    port = int(os.environ.get('AUTOMAD_PORT', '21'))
    remote_path = os.environ.get('REMOTE_PATH', '/pages/assembly').strip()
    target_path = os.environ.get('TARGET_PATH', 'assembly').strip()

    if not all([host, user, password]):
        print("❌ Missing required FTP credentials")
        print("   Required: AUTOMAD_HOST, AUTOMAD_USER, AUTOMAD_PASSWORD")
        return 1

    # Display configuration
    print(f"📋 Configuration:")
    print(f"   Host: {host}:{port}")
    print(f"   User: {user}")
    print(f"   Remote path: {remote_path}")
    print(f"   Local target: {target_path}")
    print()

    # Load metadata
    metadata = load_metadata(target_path)
    metadata['config'] = {
        'host': host,
        'port': port,
        'remote_path': remote_path,
        'last_sync': datetime.now().isoformat()
    }

    try:
        # Connect to FTP
        ftp = connect_ftp(host, user, password, port)

        # Sync files
        synced, skipped, private_skipped = sync_automad_files(ftp, remote_path, target_path, metadata)

        # Close FTP connection
        ftp.quit()
        print("✅ FTP connection closed")

        # Save metadata
        save_metadata(metadata, target_path)

        # Summary
        print(f"\n📊 Summary:")
        print(f"  ✅ Synced: {synced}")
        print(f"  ⏭️  Skipped (unchanged): {skipped}")
        print(f"  🔒 Skipped (private): {private_skipped}")
        print(f"  📁 Remote path: {remote_path}")
        print(f"  📂 Local path: {target_path}")

        return 0

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
