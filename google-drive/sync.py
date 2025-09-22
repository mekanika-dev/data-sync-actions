#!/usr/bin/env python3
"""
Script simple de synchronisation Google Drive vers GitHub
"""

import os
import json
import io
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

def authenticate():
    """Authentification Google Drive"""
    creds_file = 'credentials.json'
    
    if os.path.exists(creds_file):
        creds = service_account.Credentials.from_service_account_file(
            creds_file,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
    else:
        # Depuis variable d'environnement
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        creds_info = json.loads(creds_json)
        creds = service_account.Credentials.from_service_account_info(
            creds_info,
            scopes=['https://www.googleapis.com/auth/drive.readonly']
        )
    
    service = build('drive', 'v3', credentials=creds)
    print("✅ Connecté à Google Drive")
    return service

def list_files(service, folder_id):
    """Liste les fichiers du dossier"""
    results = []
    page_token = None
    
    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            spaces='drive',
            fields='nextPageToken, files(id, name, mimeType, size, md5Checksum, modifiedTime)',
            pageToken=page_token,
            pageSize=100
        ).execute()
        
        results.extend(response.get('files', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break
    
    print(f"📁 {len(results)} fichiers trouvés")
    return results

def download_file(service, file_info, output_dir):
    """Télécharge un fichier"""
    file_id = file_info['id']
    file_name = file_info['name']
    mime_type = file_info.get('mimeType', '')
    
    # Créer le dossier si nécessaire
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Chemin de sortie
    output_path = output_dir / file_name
    
    try:
        # Google Docs -> export en PDF
        if mime_type == 'application/vnd.google-apps.document':
            request = service.files().export_media(
                fileId=file_id,
                mimeType='application/pdf'
            )
            output_path = output_path.with_suffix('.pdf')
        # Google Sheets -> export en CSV
        elif mime_type == 'application/vnd.google-apps.spreadsheet':
            request = service.files().export_media(
                fileId=file_id,
                mimeType='text/csv'
            )
            output_path = output_path.with_suffix('.csv')
        # Fichier normal
        else:
            request = service.files().get_media(fileId=file_id)
        
        # Télécharger
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        
        while not done:
            status, done = downloader.next_chunk()
        
        # Écrire le fichier
        fh.seek(0)
        with open(output_path, 'wb') as f:
            f.write(fh.read())
        
        print(f"✅ {output_path.name}")
        return True
        
    except Exception as e:
        print(f"❌ Erreur avec {file_name}: {e}")
        return False

def load_metadata():
    """Charge les métadonnées de la dernière sync"""
    metadata_file = Path('docs/.sync-metadata.json')
    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            return json.load(f)
    return {'files': {}}

def save_metadata(metadata):
    """Sauvegarde les métadonnées"""
    metadata_file = Path('docs/.sync-metadata.json')
    metadata_file.parent.mkdir(exist_ok=True)
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

def main():
    # Configuration
    folder_id = os.environ.get('DRIVE_FOLDER_ID')
    output_dir = 'docs'
    
    if not folder_id:
        print("❌ DRIVE_FOLDER_ID manquant")
        return 1
    
    # Authentification
    service = authenticate()
    
    # Charger les métadonnées
    metadata = load_metadata()
    
    # Lister les fichiers
    files = list_files(service, folder_id)
    
    # Filtrer les types de fichiers supportés
    supported_types = [
        'application/pdf',
        'application/vnd.google-apps.document',
        'application/vnd.google-apps.spreadsheet',
        'image/png',
        'image/jpeg',
        'text/plain',
        'text/csv'
    ]
    
    # Statistiques
    synced = 0
    skipped = 0
    
    for file_info in files:
        mime_type = file_info.get('mimeType', '')
        file_name = file_info['name']
        
        # Vérifier le type
        if mime_type not in supported_types and not file_name.endswith(('.pdf', '.png', '.jpg', '.jpeg', '.txt', '.csv')):
            print(f"⏭️  Ignoré (type non supporté): {file_name}")
            skipped += 1
            continue
        
        # Vérifier si mise à jour nécessaire
        file_key = file_name
        if file_key in metadata['files']:
            if metadata['files'][file_key].get('md5') == file_info.get('md5Checksum'):
                print(f"✓ À jour: {file_name}")
                skipped += 1
                continue
        
        # Télécharger
        if download_file(service, file_info, output_dir):
            synced += 1
            # Mettre à jour les métadonnées
            metadata['files'][file_key] = {
                'id': file_info['id'],
                'md5': file_info.get('md5Checksum'),
                'modified': file_info.get('modifiedTime')
            }
    
    # Sauvegarder les métadonnées
    save_metadata(metadata)
    
    # Résumé
    print(f"\n📊 Résumé:")
    print(f"  ✅ Synchronisés: {synced}")
    print(f"  ⏭️  Ignorés: {skipped}")
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())