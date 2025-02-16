import streamlit as st
import requests
from urllib.parse import urlparse, urlunparse, urljoin, unquote
from bs4 import BeautifulSoup
import json
import random
import re
import os
import hashlib
import time
import gdown
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaFileUpload
import praw
import zipfile

# Initialize Reddit API
reddit = praw.Reddit(
    client_id=st.secrets["reddit"]["client_id"],
    client_secret=st.secrets["reddit"]["client_secret"],
    user_agent=st.secrets["reddit"]["user_agent"]
)

# Configure Streamlit page
st.set_page_config(
    page_title="Subreddit Media Scraper",
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

def create_zip_file(files):
    """Create a zip file containing downloaded media"""
    zip_path = "downloads/media_files.zip"
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for file in files:
            if os.path.exists(file):
                zipf.write(file, os.path.basename(file))
    return zip_path

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
        creds = Credentials.from_service_account_file('credentials.json')
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {
            'name': os.path.basename(file_path),
            'parents': [folder_id]
        }

        media = MediaFileUpload(file_path, resumable=True)
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

def scrape_subreddit(subreddit_name, limit, media_types, sort_by='hot'):
    """Scrape media from an entire subreddit"""
    try:
        media_urls = []
        subreddit = reddit.subreddit(subreddit_name)
        
        # Get posts based on sort method
        if sort_by == 'hot':
            posts = subreddit.hot(limit=limit)
        elif sort_by == 'new':
            posts = subreddit.new(limit=limit)
        elif sort_by == 'top':
            posts = subreddit.top(limit=limit)
        else:
            posts = subreddit.hot(limit=limit)

        for post in posts:
            try:
                # Handle galleries
                if hasattr(post, 'gallery_data') and 'images' in media_types:
                    for item in post.gallery_data['items']:
                        media_id = item['media_id']
                        metadata = post.media_metadata[media_id]
                        if metadata['status'] == 'valid' and metadata['e'] == 'Image':
                            image_url = metadata['s']['u']
                            media_urls.append(('image', image_url, post.title))

                # Handle direct images
                elif hasattr(post, 'url') and 'images' in media_types:
                    url = post.url
                    if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                        media_urls.append(('image', url, post.title))

                # Handle videos
                if post.is_video and hasattr(post, 'media') and 'videos' in media_types:
                    video_url = post.media['reddit_video']['fallback_url']
                    media_urls.append(('video', video_url, post.title))

                # Handle image previews
                elif hasattr(post, 'preview') and 'images' in media_types:
                    try:
                        preview_url = post.preview['images'][0]['source']['url']
                        media_urls.append(('image', preview_url, post.title))
                    except (KeyError, IndexError):
                        pass

                time.sleep(0.5)  # Rate limiting

            except Exception as e:
                st.warning(f"Error processing post: {str(e)}")
                continue

        # Clean URLs and remove duplicates
        cleaned_urls = []
        seen = set()
        for media_type, url, title in media_urls:
            cleaned_url = unquote(url).replace('&amp;', '&')
            if cleaned_url not in seen:
                seen.add(cleaned_url)
                cleaned_urls.append((media_type, cleaned_url, title))

        return cleaned_urls

    except Exception as e:
        st.error(f"Error scraping subreddit: {str(e)}")
        return []

def main():
    st.title("🎯 Subreddit Media Scraper")
    
    # Download option selection
    download_option = st.radio(
        "Choose download option:",
        ["Local Download", "Google Drive Upload"]
    )
    
    # Show Drive folder input only if Drive option is selected
    if download_option == "Google Drive Upload":
        drive_link = st.text_input("Paste Google Drive folder link (set sharing to 'Anyone with the link can edit'):")
        folder_id = extract_folder_id(drive_link) if drive_link else None
    else:
        folder_id = None

    # Subreddit input
    subreddit_name = st.text_input("Enter subreddit name (without r/):")
    
    # Media type selection
    media_types = st.multiselect(
        "Select media types to scrape",
        ["images", "videos"],
        default=["images"]
    )

    # Post sorting and limit
    col1, col2 = st.columns(2)
    with col1:
        sort_by = st.selectbox(
            "Sort posts by",
            ["hot", "new", "top"]
        )
    with col2:
        post_limit = st.number_input(
            "Number of posts to scan",
            min_value=1,
            max_value=1000,
            value=50
        )

    if subreddit_name and st.button("Scan Subreddit"):
        with st.spinner(f"Scanning r/{subreddit_name} for media..."):
            media_urls = scrape_subreddit(subreddit_name, post_limit, media_types, sort_by)
            st.session_state.media_urls = media_urls

            # Display results
            if media_urls:
                df = pd.DataFrame(media_urls, columns=['Type', 'URL', 'Post Title'])
                st.dataframe(df)
                st.success(f"Found {len(media_urls)} media items")
            else:
                st.warning("No media found")

    # Download section
    if st.session_state.get('media_urls'):
        if download_option == "Google Drive Upload" and folder_id:
            if st.button("Save to Google Drive"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(st.session_state.media_urls)
                
                for idx, (media_type, url, title) in enumerate(st.session_state.media_urls):
                    safe_title = re.sub(r'[^\w\-_]', '_', title)[:50]
                    ext = os.path.splitext(url)[1] or ('.mp4' if media_type == 'video' else '.jpg')
                    filename = f"{safe_title}_{hashlib.md5(url.encode()).hexdigest()[:8]}{ext}"
                    
                    filepath = download_media(url, filename)
                    
                    if filepath:
                        drive_link = upload_to_drive(filepath, folder_id)
                        os.remove(filepath)
                        if drive_link:
                            st.markdown(f"✅ [Uploaded: {filename}]({drive_link})")
                    
                    progress_bar.progress((idx + 1) / total)
                    status_text.text(f"Processed {idx + 1}/{total} files")
                
                status_text.text("Processing complete!")
        
        elif download_option == "Local Download":
            if st.button("Download Files"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                total = len(st.session_state.media_urls)
                downloaded_files = []
                
                for idx, (media_type, url, title) in enumerate(st.session_state.media_urls):
                    safe_title = re.sub(r'[^\w\-_]', '_', title)[:50]
                    ext = os.path.splitext(url)[1] or ('.mp4' if media_type == 'video' else '.jpg')
                    filename = f"{safe_title}_{hashlib.md5(url.encode()).hexdigest()[:8]}{ext}"
                    
                    filepath = download_media(url, filename)
                    if filepath:
                        downloaded_files.append(filepath)
                        st.markdown(f"✅ Downloaded: {filename}")
                    
                    progress_bar.progress((idx + 1) / total)
                    status_text.text(f"Downloaded {idx + 1}/{total} files")
                
                if downloaded_files:
                    zip_path = create_zip_file(downloaded_files)
                    with open(zip_path, "rb") as fp:
                        st.download_button(
                            label="Download ZIP file",
                            data=fp,
                            file_name="media_files.zip",
                            mime="application/zip"
                        )
                    
                    # Clean up downloaded files
                    for file in downloaded_files:
                        if os.path.exists(file):
                            os.remove(file)
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                
                status_text.text("Download complete!")

if __name__ == "__main__":
    main()
