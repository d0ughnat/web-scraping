import streamlit as st
import requests
from urllib.parse import urlparse, urlunparse, urljoin, unquote
from bs4 import BeautifulSoup
import json
import re
import os
import hashlib
import time
import gdown
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaFileUpload


# Configure Streamlit page
st.set_page_config(
    page_title="Direct Drive Media Scraper",
    page_icon="🎯",
    layout="wide"
)

# Define styles
st.markdown("""
    <style>
    .main {
        padding: 2rem;
    }
    .stButton>button {
        width: 100%;
    }
    .success {
        color: #28a745;
    }
    .error {
        color: #dc3545;
    }
    </style>
    """, unsafe_allow_html=True)

def extract_folder_id(drive_link):
    """Extract Google Drive folder ID from URL"""
    patterns = [
        r'https://drive.google.com/drive/folders/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'folders/([a-zA-Z0-9_-]+)'
    ]
    for pattern in patterns:
        match = re.search(pattern, drive_link)
        if match:
            return match.group(1)
    return None

def upload_to_drive(file_path, folder_id):
    """Upload file to Google Drive using service account"""
    try:
        # Authenticate using service account credentials
        creds = Credentials.from_service_account_file('credentials.json')
        service = build('drive', 'v3', credentials=creds)

        # Prepare metadata
        file_metadata = {
            'name': os.path.basename(file_path),
            'parents': [folder_id]
        }

        media = MediaFileUpload(file_path, resumable=True)

        # Upload file
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()

        return f"https://drive.google.com/file/d/{file.get('id')}/view"

    except Exception as e:
        st.error(f"Upload error: {str(e)}")
        return None

def download_media(url, filename):
    """Download media file"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        os.makedirs('downloads', exist_ok=True)
        filepath = os.path.join('downloads', filename)
        
        response = requests.get(url, headers=headers, stream=True)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            return filepath
    except Exception as e:
        st.error(f"Download error: {str(e)}")
    return None

def extract_media_from_html(soup, base_url):
    """Extract media URLs from HTML"""
    media_urls = []
    
    # Find images
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-original')
        if src:
            width = img.get('width', '').strip('px') or '0'
            height = img.get('height', '').strip('px') or '0'
            try:
                if int(width) < 50 or int(height) < 50:
                    continue
            except ValueError:
                pass
            
            if not any(x in src.lower() for x in ['thumbnail', 'icon', 'avatar', 'emoji', 'loading']):
                if src.startswith('//'):
                    src = 'https:' + src
                elif not src.startswith(('http://', 'https://')):
                    src = urljoin(base_url, src)
                src = src.split('?')[0]
                media_urls.append(('image', src))
    
    # Find videos
    for video in soup.find_all(['video', 'source']):
        src = video.get('src') or video.get('data-src')
        if src:
            if src.startswith('//'):
                src = 'https:' + src
            elif not src.startswith(('http://', 'https://')):
                src = urljoin(base_url, src)
            media_urls.append(('video', src))
    
    return media_urls

def get_reddit_media(url, headers):
    """Extract media from Reddit posts"""
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        if not path.endswith('.json'):
            path += '.json'
        json_url = urlunparse(parsed._replace(path=path, query='', fragment=''))
        
        response = requests.get(json_url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            media_urls = []
            
            posts = data[0]['data']['children']
            for post in posts:
                post_data = post['data']
                
                # Handle videos
                if post_data.get('is_video', False):
                    video_url = post_data.get('media', {}).get('reddit_video', {}).get('fallback_url')
                    if video_url:
                        media_urls.append(('video', video_url.split('?')[0]))
                
                # Handle galleries
                elif post_data.get('is_gallery', False):
                    media_metadata = post_data.get('media_metadata', {})
                    for media_id in media_metadata:
                        media = media_metadata[media_id]
                        if media.get('status') == 'valid' and media.get('e') == 'Image':
                            image_url = media['s'].get('u', '')
                            if image_url:
                                media_urls.append(('image', image_url.split('?')[0]))
                
                # Handle direct images
                elif post_data.get('url', ''):
                    url = post_data['url']
                    if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
                        media_urls.append(('image', url))
            
            return media_urls
    except Exception as e:
        st.error(f"Error processing Reddit URL: {str(e)}")
    return []

def main():
    st.title("🎯 Direct Drive Media Scraper")
    
    # Get Drive folder link
    drive_link = st.text_input("Paste Google Drive folder link (set sharing to 'Anyone with the link can edit'):")
    folder_id = extract_folder_id(drive_link) if drive_link else None

    # Main scraping functionality
    url = st.text_input("Enter URL to scrape:")
    
    if url:
        if st.button("Scan for Media"):
            with st.spinner("Scanning for media..."):
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                media_urls = []

                if 'reddit.com' in url:
                    media_urls.extend(get_reddit_media(url, headers))
                else:
                    try:
                        response = requests.get(url, headers=headers)
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            media_urls.extend(extract_media_from_html(soup, url))
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

                # Remove duplicates and show results
                seen = set()
                media_urls = [x for x in media_urls if not (x[1] in seen or seen.add(x[1]))]
                st.session_state.media_urls = media_urls

                # Display results
                if media_urls:
                    df = pd.DataFrame(media_urls, columns=['Type', 'URL'])
                    st.dataframe(df)
                else:
                    st.warning("No media found")

    # Download and upload section
    if st.session_state.get('media_urls') and folder_id:
        if st.button("Save to Google Drive"):
            progress_bar = st.progress(0)
            status_text = st.empty()
            total = len(st.session_state.media_urls)
            
            for idx, (media_type, url) in enumerate(st.session_state.media_urls):
                filename = f"{media_type}_{hashlib.md5(url.encode()).hexdigest()[:8]}{os.path.splitext(url)[1]}"
                filepath = download_media(url, filename)
                
                if filepath:
                    drive_link = upload_to_drive(filepath, folder_id)
                    os.remove(filepath)
                    if drive_link:
                        st.markdown(f"✅ [Uploaded: {filename}]({drive_link})")
                
                progress_bar.progress((idx + 1) / total)
                status_text.text(f"Processed {idx + 1}/{total} files")
            
            status_text.text("Processing complete!")

if __name__ == "__main__":
    main()
