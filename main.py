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
import pandas as pd
import praw
from datetime import datetime

# Initialize Reddit API client
reddit = praw.Reddit(
    client_id=st.secrets["reddit"]["client_id"],
    client_secret=st.secrets["reddit"]["client_secret"],
    user_agent=st.secrets["reddit"]["user_agent"]
)

# Configure Streamlit page
st.set_page_config(
    page_title="Local Media Scraper",
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

def create_download_folder():
    """Create a timestamped download folder"""
    base_dir = "downloads"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    download_dir = os.path.join(base_dir, timestamp)
    os.makedirs(download_dir, exist_ok=True)
    return download_dir

def download_media(url, download_dir, media_type, index):
    """Download media file to local directory"""
    try:
        # Create a filename using media type, index, and file extension
        ext = os.path.splitext(url)[1]
        if not ext:
            ext = '.jpg' if media_type == 'image' else '.mp4'
        filename = f"{media_type}_{index}{ext}"
        filepath = os.path.join(download_dir, filename)
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        # Download with progress bar
        response = requests.get(url, headers=headers, stream=True)
        if response.status_code == 200:
            total_size = int(response.headers.get('content-length', 0))
            progress_text = st.empty()
            progress_bar = st.progress(0)
            
            with open(filepath, 'wb') as f:
                downloaded_size = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        if total_size:
                            progress = min(downloaded_size / total_size, 1.0)
                            progress_bar.progress(progress)
                            progress_text.text(f"Downloading {filename}: {progress:.1%}")
            
            progress_text.text(f"✅ Downloaded: {filename}")
            return filepath
        else:
            st.error(f"Failed to download {filename}: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        st.error(f"Download error for {url}: {str(e)}")
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

def extract_post_id(url):
    """Extract post ID from Reddit URL"""
    patterns = [
        r'/comments/([a-zA-Z0-9]+)/',
        r'reddit.com/(\w+)$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_reddit_media(url):
    """Extract media from Reddit posts using PRAW"""
    try:
        post_id = extract_post_id(url)
        if not post_id:
            st.error("Could not extract post ID from URL")
            return []

        submission = reddit.submission(id=post_id)
        media_urls = []

        try:
            # Handle galleries
            if hasattr(submission, 'gallery_data'):
                for item in submission.gallery_data['items']:
                    media_id = item['media_id']
                    metadata = submission.media_metadata[media_id]
                    if metadata['status'] == 'valid':
                        if metadata['e'] == 'Image':
                            image_url = metadata['s']['u']
                            media_urls.append(('image', image_url))

            # Handle direct images
            elif hasattr(submission, 'url'):
                url = submission.url
                if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                    media_urls.append(('image', url))

            # Handle videos
            if submission.is_video and hasattr(submission, 'media'):
                video_url = submission.media['reddit_video']['fallback_url']
                media_urls.append(('video', video_url))

            # Handle image previews
            elif hasattr(submission, 'preview'):
                try:
                    preview_url = submission.preview['images'][0]['source']['url']
                    media_urls.append(('image', preview_url))
                except (KeyError, IndexError):
                    pass

        except Exception as e:
            st.warning(f"Error processing media content: {str(e)}")

        # Clean URLs
        cleaned_urls = []
        for media_type, url in media_urls:
            cleaned_url = url.replace('&amp;', '&')
            if ('image', cleaned_url) not in cleaned_urls:
                cleaned_urls.append((media_type, cleaned_url))

        return cleaned_urls

    except praw.exceptions.PRAWException as e:
        st.error(f"Reddit API error: {str(e)}")
        return []
    except Exception as e:
        st.error(f"Unexpected error: {str(e)}")
        return []

def main():
    st.title("🎯 Local Media Scraper")
    
    # Main scraping functionality
    url = st.text_input("Enter URL to scrape:")
    
    if url:
        if st.button("Scan and Download Media"):
            with st.spinner("Scanning for media..."):
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                media_urls = []

                if 'reddit.com' in url:
                    media_urls.extend(get_reddit_media(url))
                else:
                    try:
                        response = requests.get(url, headers=headers)
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, 'html.parser')
                            media_urls.extend(extract_media_from_html(soup, url))
                    except Exception as e:
                        st.error(f"Error: {str(e)}")

                # Remove duplicates
                seen = set()
                media_urls = [x for x in media_urls if not (x[1] in seen or seen.add(x[1]))]

                if media_urls:
                    # Create download directory
                    download_dir = create_download_folder()
                    st.info(f"Downloading files to: {download_dir}")
                    
                    # Display results and download
                    df = pd.DataFrame(media_urls, columns=['Type', 'URL'])
                    st.dataframe(df)
                    
                    total_files = len(media_urls)
                    st.write(f"Found {total_files} media files")
                    
                    # Download all files
                    successful_downloads = 0
                    for idx, (media_type, url) in enumerate(media_urls, 1):
                        st.write(f"Downloading {media_type} {idx}/{total_files}")
                        if download_media(url, download_dir, media_type, idx):
                            successful_downloads += 1
                            time.sleep(0.5)  # Add small delay between downloads
                    
                    st.success(f"Downloaded {successful_downloads}/{total_files} files to {download_dir}")
                else:
                    st.warning("No media found")

if __name__ == "__main__":
    main()
