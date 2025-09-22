#!/usr/bin/env python3
"""
Script de synchronisation Google Drive vers GitHub
Supporte les sous-dossiers et le filtrage par type de fichier
"""

import os
import json
import io
import glob
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

def find_subfolder(service, parent_folder_id, subfolder_name):
    """Trouve l'ID d'un sous-dossier par son nom"""
    if not subfolder_name:
        return parent_folder_id
    
    print(f"🔍 Recherche du sous-dossier: {subfolder_name}")
    
    # Rechercher le sous-dossier
    query = f"'{parent_folder_id}' in parents and name='{subfolder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    
    response = service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)',
        pageSize=10
    ).execute()
    
    folders = response.get('files', [])
    
    if not folders:
        print(f"⚠️  Sous-dossier '{subfolder_name}' non trouvé, utilisation du dossier racine")
        return parent_folder_id
    
    folder_id = folders[0]['id']
    print(f"✅ Sous-dossier trouvé: {subfolder_name} (ID: {folder_id})")
    return folder_id

def list_files(service, folder_id, file_types=None, recursive=True):
    """
    Liste les fichiers du dossier
    
    Args:
        service: Service Google Drive
        folder_id: ID du dossier
        file_types: Liste des types de fichiers à inclure (ex: ['pdf'])
        recursive: Si True, inclut les sous-dossiers
    """
    all_files = []
    folders_to_process = [(folder_id, '')]
    processed_folders = set()
    
    while folders_to_process:
        current_folder_id, current_path = folders_to_process.pop(0)
        
        if current_folder_id in processed_folders:
            continue
        processed_folders.add(current_folder_id)
        
        page_token = None
        while True:
            # Requête pour lister les fichiers
            response = service.files().list(
                q=f"'{current_folder_id}' in parents and trashed = false",
                spaces='drive',
                fields='nextPageToken, files(id, name, mimeType, size, md5Checksum, modifiedTime)',
                pageToken=page_token,
                pageSize=100
            ).execute()
            
            items = response.get('files', [])
            
            for item in items:
                # Si c'est un dossier et qu'on est en mode récursif
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    if recursive:
                        new_path = f"{current_path}/{item['name']}" if current_path else item['name']
                        folders_to_process.append((item['id'], new_path))
                else:
                    # Ajouter le chemin relatif
                    item['relative_path'] = current_path
                    
                    # Filtrer par type si spécifié
                    if file_types:
                        # Vérifier l'extension
                        file_ext = Path(item['name']).suffix.lower().replace('.', '')
                        
                        if file_ext in file_types:
                            all_files.append(item)
                        elif item['mimeType'] == f'application/{file_ext}':
                            all_files.append(item)
                    else:
                        # Pas de filtre, ajouter tous les fichiers
                        all_files.append(item)
            
            page_token = response.get('nextPageToken')
            if not page_token:
                break
    
    print(f"📁 {len(all_files)} fichiers trouvés")
    return all_files

def download_file(service, file_info, output_dir, preserve_structure=True):
    """Télécharge un fichier et remplace les fichiers existants avec le même préfixe (5 premiers caractères)"""
    file_id = file_info['id']
    file_name = file_info['name']
    mime_type = file_info.get('mimeType', '')
    relative_path = file_info.get('relative_path', '')
    
    # Déterminer le dossier de sortie
    output_dir = Path(output_dir)
    if preserve_structure and relative_path:
        output_dir = output_dir / relative_path
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Chercher un fichier existant avec le même préfixe
    existing_file = find_existing_file_by_prefix(output_dir.parent if preserve_structure and relative_path else output_dir, 
                                                file_name, preserve_structure, relative_path)
    
    # Chemin de sortie (utiliser le nom du fichier existant si trouvé, sinon le nouveau nom)
    if existing_file:
        output_path = existing_file
        action = "🔄 Remplacé"
        print(f"🔍 Fichier avec préfixe identique trouvé: {existing_file.name} -> sera remplacé par {file_name}")
    else:
        output_path = output_dir / file_name
        action = "✅ Nouveau"
    
    try:
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
        
        if relative_path:
            print(f"{action} {relative_path}/{output_path.name}")
        else:
            print(f"{action} {output_path.name}")
        
        # Retourner le chemin final pour la mise à jour des métadonnées
        return str(output_path.relative_to(output_dir.parent if preserve_structure and relative_path else output_dir.parent))
        
    except Exception as e:
        print(f"❌ Erreur avec {file_name}: {e}")
        return False

def load_metadata(target_path):
    """Charge les métadonnées de la dernière sync"""
    metadata_file = Path(target_path) / '.sync-metadata.json'
    if metadata_file.exists():
        with open(metadata_file, 'r') as f:
            return json.load(f)
    return {'files': {}, 'config': {}}

def save_metadata(metadata, target_path):
    """Sauvegarde les métadonnées"""
    metadata_file = Path(target_path) / '.sync-metadata.json'
    metadata_file.parent.mkdir(exist_ok=True)
    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

def find_existing_file_by_prefix(output_dir, file_name, preserve_structure=True, relative_path=''):
    """
    Trouve un fichier existant avec les 5 premiers caractères identiques
    
    Args:
        output_dir: Dossier de destination
        file_name: Nom du nouveau fichier
        preserve_structure: Si True, respecte la structure des dossiers
        relative_path: Chemin relatif pour la structure
    
    Returns:
        Path du fichier existant ou None si pas trouvé
    """
    # Déterminer le dossier de recherche
    search_dir = Path(output_dir)
    if preserve_structure and relative_path:
        search_dir = search_dir / relative_path
    
    if not search_dir.exists():
        return None
    
    # Extraire les 5 premiers caractères (sans l'extension)
    file_stem = Path(file_name).stem
    if len(file_stem) < 5:
        return None
    
    prefix = file_stem[:5]
    file_ext = Path(file_name).suffix
    
    # Chercher les fichiers avec le même préfixe et extension
    pattern = f"{prefix}*{file_ext}"
    search_pattern = search_dir / pattern
    
    matching_files = list(search_dir.glob(pattern))
    
    # Retourner le premier fichier trouvé (il devrait y en avoir au maximum un)
    return matching_files[0] if matching_files else None

def main():
    # Configuration depuis les variables d'environnement
    root_folder_id = os.environ.get('DRIVE_DOCS_FOLDER_ID')
    subfolder_name = os.environ.get('SUBFOLDER_NAME', '').strip()
    target_path = os.environ.get('TARGET_PATH', 'docs').strip()
    file_types_str = os.environ.get('FILE_TYPES', '').strip()
    
    # Parser les types de fichiers
    file_types = None
    if file_types_str:
        file_types = [ft.strip().lower() for ft in file_types_str.split(',')]
    
    if not root_folder_id:
        print("❌ DRIVE_DOCS_FOLDER_ID manquant")
        return 1
    
    # Afficher la configuration
    print(f"📋 Configuration:")
    print(f"   Dossier racine ID: {root_folder_id}")
    print(f"   Sous-dossier: {subfolder_name if subfolder_name else 'racine'}")
    print(f"   Destination: {target_path}")
    print(f"   Types de fichiers: {file_types if file_types else 'tous'}")
    print()
    
    # Authentification
    service = authenticate()
    
    # Trouver le dossier cible
    folder_id = find_subfolder(service, root_folder_id, subfolder_name)
    
    # Charger les métadonnées
    metadata = load_metadata(target_path)
    metadata['config'] = {
        'folder_id': folder_id,
        'subfolder': subfolder_name,
        'file_types': file_types
    }
    
    # Lister les fichiers
    files = list_files(service, folder_id, file_types=file_types, recursive=True)
    
    # Statistiques
    synced = 0
    skipped = 0
    
    for file_info in files:
        file_name = file_info['name']
        relative_path = file_info.get('relative_path', '')
        
        # Construire le chemin complet du fichier
        if relative_path:
            full_file_path = Path(target_path) / relative_path / file_name
            file_key = f"{relative_path}/{file_name}"
        else:
            full_file_path = Path(target_path) / file_name
            file_key = file_name
        
        # Vérifier si le fichier existe déjà avec le nom exact
        if full_file_path.exists():
            # Fichier identique existant - vérifier le MD5 pour éviter la re-synchronisation
            if file_key in metadata['files']:
                if metadata['files'][file_key].get('md5') == file_info.get('md5Checksum'):
                    print(f"⏭️  Identique: {file_key}")
                    skipped += 1
                    continue
            
            # Même nom mais contenu différent - télécharger pour remplacer
            result = download_file(service, file_info, target_path, preserve_structure=True)
            if result:
                synced += 1
                metadata['files'][file_key] = {
                    'id': file_info['id'],
                    'md5': file_info.get('md5Checksum'),
                    'modified': file_info.get('modifiedTime'),
                    'size': file_info.get('size'),
                    'original_name': file_name
                }
            continue
        
        # Chercher si un fichier avec le même préfixe (5 premiers caractères) existe
        existing_file = find_existing_file_by_prefix(target_path, file_name, preserve_structure=True, relative_path=relative_path)
        
        if existing_file:
            # Fichier avec préfixe identique trouvé - remplacer
            result = download_file(service, file_info, target_path, preserve_structure=True)
            if result:
                synced += 1
                # Utiliser la clé du fichier existant pour les métadonnées
                existing_relative_path = str(existing_file.parent.relative_to(Path(target_path))) if existing_file.parent != Path(target_path) else ''
                if existing_relative_path and existing_relative_path != '.':
                    existing_file_key = f"{existing_relative_path}/{existing_file.name}"
                else:
                    existing_file_key = existing_file.name
                
                metadata['files'][existing_file_key] = {
                    'id': file_info['id'],
                    'md5': file_info.get('md5Checksum'),
                    'modified': file_info.get('modifiedTime'),
                    'size': file_info.get('size'),
                    'original_name': file_name
                }
        else:
            # Nouveau fichier - vérifier les métadonnées pour éviter la re-téléchargement
            if file_key in metadata['files']:
                if metadata['files'][file_key].get('md5') == file_info.get('md5Checksum'):
                    print(f"✓ À jour: {file_key}")
                    skipped += 1
                    continue
            
            # Télécharger le nouveau fichier
            result = download_file(service, file_info, target_path, preserve_structure=True)
            if result:
                synced += 1
                metadata['files'][file_key] = {
                    'id': file_info['id'],
                    'md5': file_info.get('md5Checksum'),
                    'modified': file_info.get('modifiedTime'),
                    'size': file_info.get('size'),
                    'original_name': file_name
                }
    
    # Sauvegarder les métadonnées
    save_metadata(metadata, target_path)
    
    # Résumé
    print(f"\n📊 Résumé:")
    print(f"  ✅ Synchronisés: {synced}")
    print(f"  ⏭️  Ignorés: {skipped}")
    print(f"  📁 Dossier: {subfolder_name if subfolder_name else 'racine'}")
    print(f"  📄 Types: {', '.join(file_types) if file_types else 'tous'}")
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())