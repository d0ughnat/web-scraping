import streamlit as st
import praw
import os
import hashlib
import requests
import re
import io
import time
import tempfile
import zipfile
from datetime import datetime
from urllib.parse import urlparse, urlunparse, urljoin, unquote, parse_qs
from pathlib import Path
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import pandas as pd

# Page configuration
st.set_page_config(
    page_title="Reddit Media Scraper Pro",
    page_icon="🎯",
    layout="wide"
)

# Custom CSS
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
    .download-stats {
        margin: 10px 0;
        padding: 10px;
        background-color: #f8f9fa;
        border-radius: 5px;
    }
    .user-info {
        position: fixed;
        top: 10px;
        right: 10px;
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        font-size: 0.9em;
        z-index: 1000;
    }
    </style>
    """, unsafe_allow_html=True)

# Initialize Reddit client
@st.cache_resource
def get_reddit_client():
    return praw.Reddit(
        client_id=st.secrets["reddit"]["client_id"],
        client_secret=st.secrets["reddit"]["client_secret"],
        user_agent=st.secrets["reddit"]["user_agent"]
    )

def display_user_info():
    """Display current time and user information"""
    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(
        f"""
        <div class="user-info">
            <div>UTC: {current_time}</div>
            <div>User: {st.session_state.get('username', 'Guest')}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

def extract_post_id(url_or_id):
    """Extract Reddit post ID from URL or direct ID input"""
    if not url_or_id:
        return None
        
    # Direct ID
    if len(url_or_id) >= 6 and '/' not in url_or_id:
        return url_or_id
        
    # URL patterns
    patterns = [
        r'reddit\.com/r/\w+/comments/(\w+)',
        r'redd\.it/(\w+)',
        r'/comments/(\w+)',
        r'reddit\.com/\w+/(\w+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
            
    return None

def get_safe_filename(title, post_id):
    """Generate a safe filename from post title and ID"""
    # Clean the title
    safe_title = re.sub(r'[^\w\-_]', '_', title)
    safe_title = safe_title[:50]  # Limit length
    
    return f"{safe_title}_{post_id}"

def extract_folder_id(drive_link):
    """Extract Google Drive folder ID from URL"""
    if not drive_link:
        return None
        
    # Clean up the input
    drive_link = drive_link.strip()
    
    # Handle direct folder ID input
    if re.match(r'^[a-zA-Z0-9_-]{33}$', drive_link):
        return drive_link
    
    patterns = [
        r'https://drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)(?:\?.*)?$',
        r'id=([a-zA-Z0-9_-]+)',
        r'folders/([a-zA-Z0-9_-]+)(?:\?.*)?$'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, drive_link)
        if match:
            folder_id = match.group(1)
            return folder_id.split('?')[0]
            
    return None

def download_media(url, output_path, media_type='generic', progress_bar=None):
    """Universal media download function"""
    try:
        if media_type == 'video':
            return download_reddit_video(url, output_path, progress_bar)
        else:
            return download_file(url, output_path)
    except Exception as e:
        st.error(f"Download error: {str(e)}")
        return False

def download_file(url, output_path):
    """Download generic file from URL"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        st.error(f"File download error: {str(e)}")
        return False

def download_reddit_video(url, output_path, progress_bar=None):
    """Download Reddit video with audio using yt-dlp"""
    try:
        ydl_opts = {
            'format': 'bv*+ba/b',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
            'progress_hooks': [
                lambda d: update_progress(d, progress_bar) if progress_bar else None
            ]
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            return True
            
    except Exception as e:
        st.error(f"Video download error: {str(e)}")
        return False

def update_progress(d, progress_bar):
    """Update download progress bar"""
    if d['status'] == 'downloading' and progress_bar:
        try:
            total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                progress = downloaded / total
                progress_bar.progress(progress)
        except:
            pass

def get_subreddit_media(subreddit_name, limit, sort_by="hot", media_types=None):
    """Scrape media posts from a subreddit"""
    reddit = get_reddit_client()
    try:
        subreddit = reddit.subreddit(subreddit_name)
        media_posts = []
        
        if media_types is None:
            media_types = ['images', 'videos']
        
        # Get posts based on sort type
        if sort_by == "hot":
            posts = subreddit.hot(limit=limit)
        elif sort_by == "new":
            posts = subreddit.new(limit=limit)
        elif sort_by == "top":
            posts = subreddit.top(limit=limit)
        else:
            posts = subreddit.hot(limit=limit)
        
        for post in posts:
            # Handle video posts
            if post.is_video and 'videos' in media_types:
                if hasattr(post, 'media') and post.media and 'reddit_video' in post.media:
                    media_posts.append({
                        'type': 'video',
                        'url': post.url,
                        'title': post.title,
                        'id': post.id,
                        'direct_url': post.media['reddit_video']['fallback_url']
                    })
            
            # Handle image posts
            elif 'images' in media_types:
                # Gallery images
                if hasattr(post, 'gallery_data'):
                    try:
                        for item in post.gallery_data['items']:
                            media_id = item['media_id']
                            metadata = post.media_metadata[media_id]
                            if metadata['status'] == 'valid' and metadata['e'] == 'Image':
                                image_url = metadata['s']['u'].replace('&amp;', '&')
                                media_posts.append({
                                    'type': 'image',
                                    'url': image_url,
                                    'title': post.title,
                                    'id': f"{post.id}_{media_id}"
                                })
                    except Exception as e:
                        st.warning(f"Error processing gallery post: {str(e)}")
                
                # Direct images
                elif hasattr(post, 'url'):
                    url = post.url.lower()
                    if any(url.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                        media_posts.append({
                            'type': 'image',
                            'url': post.url,
                            'title': post.title,
                            'id': post.id
                        })
        
        return media_posts
    except Exception as e:
        st.error(f"Error accessing subreddit: {str(e)}")
        return []

def batch_download_media(media_posts, progress_placeholder, progress_bar):
    """Download multiple media files and create a zip archive"""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        total_posts = len(media_posts)
        successful_downloads = 0
        
        with tempfile.TemporaryDirectory() as temp_dir:
            for i, post in enumerate(media_posts, 1):
                progress_placeholder.text(f"Downloading {i}/{total_posts}: {post['title']}")
                progress_bar.progress(i/total_posts)
                
                file_extension = '.mp4' if post['type'] == 'video' else os.path.splitext(post['url'])[1]
                if not file_extension:
                    file_extension = '.jpg'  # Default extension for images
                
                safe_filename = get_safe_filename(post['title'], post['id']) + file_extension
                temp_path = os.path.join(temp_dir, safe_filename)
                
                success = download_media(
                    post['url'],
                    temp_path,
                    post['type'],
                    progress_bar if post['type'] == 'video' else None
                )
                
                if success and os.path.exists(temp_path):
                    zip_file.write(temp_path, safe_filename)
                    successful_downloads += 1
                
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        
        progress_placeholder.text(f"Successfully downloaded {successful_downloads}/{total_posts} files")
    
    return zip_buffer.getvalue()

def upload_to_drive(file_path, folder_id):
    """Upload file to Google Drive using service account"""
    try:
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")
            
        if not folder_id or not validate_drive_folder(folder_id):
            raise ValueError("Invalid Drive folder ID")
        
        # Get credentials from secrets
        creds_data = st.secrets["gcp_service_account"]
        
        # Create credentials using service account info
        creds = service_account.Credentials.from_service_account_info(
            info=dict(creds_data),
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        
        service = build('drive', 'v3', credentials=creds)
        
        # Verify folder exists and is accessible
        try:
            service.files().get(fileId=folder_id, supportsAllDrives=True).execute()
        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError("Drive folder not found or not accessible")
            else:
                raise
        
        file_metadata = {
            'name': os.path.basename(file_path),
            'parents': [folder_id]
        }
        
        mime_type = 'application/octet-stream'
        if file_path.endswith('.mp4'):
            mime_type = 'video/mp4'
        elif file_path.endswith('.zip'):
            mime_type = 'application/zip'
        elif any(file_path.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
            mime_type = f'image/{os.path.splitext(file_path)[1][1:]}'
        
        media = MediaFileUpload(
            file_path,
            mimetype=mime_type,
            resumable=True,
            chunksize=1024*1024
        )
        
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        
        return f"https://drive.google.com/file/d/{file.get('id')}/view"
        
    except ValueError as e:
        st.error(str(e))
        return None
    except HttpError as e:
        error_message = "Drive API error: "
        if e.resp.status == 404:
            error_message += "Folder not found or not accessible"
        elif e.resp.status == 403:
            error_message += "Permission denied. Check folder sharing settings"
        else:
            error_message += str(e)
        st.error(error_message)
        return None
    except Exception as e:
        st.error(f"Upload error: {str(e)}")
        return None

def upload_zip_to_drive(zip_data, filename, folder_id):
    """Upload zip data directly to Google Drive"""
    try:
        if not validate_drive_folder(folder_id):
            st.error("Invalid Drive folder ID")
            return None
            
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_file.write(zip_data)
            temp_path = temp_file.name

        st.info(f"Uploading {filename} to Google Drive... This may take a while.")
        
        drive_url = upload_to_drive(temp_path, folder_id)
        
        os.unlink(temp_path)
        
        if not drive_url:
            raise Exception("Upload failed. Check the folder permissions and ID.")
        
        return drive_url

    except Exception as e:
        st.error(f"Drive upload error: {str(e)}")
        return None

def display_user_info():
    """Display current time and user information"""
    current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(
        f"""
        <div class="user-info">
            <div>UTC: {current_time}</div>
            <div>User: {st.session_state.get('username', 'Guest')}</div>
        </div>
        """,
        unsafe_allow_html=True
    )
def main():
    display_user_info()
    st.title("🎯 Reddit Media Scraper Pro")
    
    # Drive settings in sidebar
    with st.sidebar:
        st.header("Google Drive Settings")
        drive_folder = st.text_input(
            "Drive Folder ID:",
            help="Enter the Google Drive folder ID where files should be uploaded"
        )
        enable_drive_upload = st.checkbox("Enable Google Drive Upload", value=False)
    
    # Main tabs
    tab1, tab2 = st.tabs(["Single Post Download", "Subreddit Scraper"])
    
    # Single Post Download Tab
    with tab1:
        url_or_id = st.text_input(
            "Enter Reddit post URL or ID:",
            help="You can enter either a full Reddit post URL or just the post ID"
        )
        
        if st.button("Download Single Post Media", use_container_width=True):
            if not url_or_id:
                st.error("Please enter a valid Reddit post URL or ID")
                return
                
            try:
                post_id = extract_post_id(url_or_id)
                if not post_id:
                    st.error("Could not extract post ID from input")
                    return
                    
                reddit = get_reddit_client()
                submission = reddit.submission(id=post_id)
                
                progress_text = st.empty()
                progress_bar = st.progress(0)
                progress_text.text("Analyzing post...")

                # Handle different types of media posts
                if submission.is_video:
                    # Video post
                    progress_text.text("Starting video download...")
                    output_path = get_safe_filename(submission.title, submission.id) + '.mp4'
                    
                    with st.spinner('Downloading video with audio...'):
                        if download_reddit_video(submission.url, output_path, progress_bar):
                            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                                st.video(output_path)
                                
                                # Handle Google Drive upload
                                if enable_drive_upload:
                                    if not drive_folder:
                                        st.error("Please enter a Google Drive folder ID in the sidebar")
                                    else:
                                        with st.spinner("Uploading to Google Drive..."):
                                            drive_url = upload_to_drive(output_path, drive_folder)
                                            if drive_url:
                                                st.success(f"Uploaded to Drive: [View File]({drive_url})")
                                
                                # Local download option
                                with open(output_path, 'rb') as f:
                                    st.download_button(
                                        label="💾 Download Video",
                                        data=f,
                                        file_name=output_path,
                                        mime="video/mp4",
                                        use_container_width=True
                                    )
                            else:
                                st.error("Download failed: Output file is empty or missing")
                            
                            if os.path.exists(output_path):
                                os.remove(output_path)
                
                elif hasattr(submission, 'gallery_data'):
                    # Gallery post
                    progress_text.text("Processing image gallery...")
                    images = []
                    for item in submission.gallery_data['items']:
                        media_id = item['media_id']
                        metadata = submission.media_metadata[media_id]
                        if metadata['status'] == 'valid' and metadata['e'] == 'Image':
                            image_url = metadata['s']['u'].replace('&amp;', '&')
                            images.append({
                                'url': image_url,
                                'id': media_id
                            })
                    
                    if images:
                        # Create ZIP file for gallery
                        with tempfile.TemporaryDirectory() as temp_dir:
                            zip_buffer = io.BytesIO()
                            with zipfile.ZipFile(zip_buffer, 'w') as zip_file:
                                for idx, img in enumerate(images):
                                    progress_bar.progress((idx + 1) / len(images))
                                    filename = f"gallery_image_{idx + 1}{os.path.splitext(img['url'])[1]}"
                                    filepath = os.path.join(temp_dir, filename)
                                    if download_file(img['url'], filepath):
                                        zip_file.write(filepath, filename)
                            
                            if enable_drive_upload and drive_folder:
                                with st.spinner("Uploading gallery to Google Drive..."):
                                    zip_filename = f"{get_safe_filename(submission.title, submission.id)}_gallery.zip"
                                    drive_url = upload_zip_to_drive(zip_buffer.getvalue(), zip_filename, drive_folder)
                                    if drive_url:
                                        st.success(f"Uploaded gallery to Drive: [View File]({drive_url})")
                            
                            st.download_button(
                                label="📦 Download Gallery (ZIP)",
                                data=zip_buffer.getvalue(),
                                file_name=f"{get_safe_filename(submission.title, submission.id)}_gallery.zip",
                                mime="application/zip",
                                use_container_width=True
                            )
                    else:
                        st.error("No valid images found in gallery")
                
                elif hasattr(submission, 'url'):
                    # Single image post
                    if any(submission.url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                        progress_text.text("Downloading image...")
                        filename = get_safe_filename(submission.title, submission.id) + os.path.splitext(submission.url)[1]
                        
                        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(submission.url)[1]) as temp_file:
                            if download_file(submission.url, temp_file.name):
                                st.image(temp_file.name)
                                
                                if enable_drive_upload and drive_folder:
                                    with st.spinner("Uploading to Google Drive..."):
                                        drive_url = upload_to_drive(temp_file.name, drive_folder)
                                        if drive_url:
                                            st.success(f"Uploaded to Drive: [View File]({drive_url})")
                                
                                with open(temp_file.name, 'rb') as f:
                                    st.download_button(
                                        label="💾 Download Image",
                                        data=f,
                                        file_name=filename,
                                        mime=f"image/{os.path.splitext(submission.url)[1][1:]}",
                                        use_container_width=True
                                    )
                            
                            os.unlink(temp_file.name)
                    else:
                        st.error("This post does not contain downloadable media")
                else:
                    st.error("This post does not contain downloadable media")
                
                progress_text.text("Processing complete!")
                progress_bar.progress(1.0)
                
            except Exception as e:
                st.error(f"Error processing post: {str(e)}")
    
    # Subreddit Scraper Tab
    with tab2:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            subreddit_name = st.text_input("Subreddit name:", help="Enter subreddit name without r/")
        
        with col2:
            post_limit = st.number_input("Number of posts to scrape:", min_value=1, max_value=100, value=10)
        
        with col3:
            sort_by = st.selectbox("Sort by:", ["hot", "new", "top"])
        
        # Media type selection
        media_types = st.multiselect(
            "Select media types to scrape",
            ["images", "videos"],
            default=["images", "videos"]
        )
        
        if st.button("Scrape and Download Media", use_container_width=True):
            if not subreddit_name:
                st.error("Please enter a subreddit name")
                return
                
            if not media_types:
                st.error("Please select at least one media type")
                return
                
            try:
                progress_text = st.empty()
                progress_bar = st.progress(0)
                progress_text.text("Fetching posts from subreddit...")
                
                media_posts = get_subreddit_media(subreddit_name, post_limit, sort_by, media_types)
                
                if not media_posts:
                    st.warning("No media posts found matching your criteria")
                    return
                
                st.info(f"Found {len(media_posts)} media posts")
                
                # Display media posts in a dataframe
                df = pd.DataFrame([
                    {
                        'Type': post['type'],
                        'Title': post['title'],
                        'URL': post['url']
                    } for post in media_posts
                ])
                st.dataframe(df)
                
                progress_text.text("Starting batch download...")
                zip_data = batch_download_media(media_posts, progress_text, progress_bar)
                
                if zip_data:
                    # Generate filename with timestamp
                    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    zip_filename = f"reddit_{subreddit_name}_media_{timestamp}.zip"
                    
                    # Handle Google Drive upload
                    if enable_drive_upload:
                        if not drive_folder:
                            st.error("Please enter a Google Drive folder ID in the sidebar")
                        else:
                            with st.spinner("Uploading to Google Drive..."):
                                drive_url = upload_zip_to_drive(zip_data, zip_filename, drive_folder)
                                if drive_url:
                                    st.success(f"Uploaded to Drive: [View File]({drive_url})")
                    
                    # Local download option
                    st.download_button(
                        label="📦 Download All Media (ZIP)",
                        data=zip_data,
                        file_name=zip_filename,
                        mime="application/zip",
                        use_container_width=True
                    )
                    
                    progress_text.text("Download package ready!")
                    progress_bar.progress(1.0)
                
            except Exception as e:
                st.error(f"Error during subreddit scraping: {str(e)}")
    
    # Footer with instructions
    with st.expander("📖 Instructions and Tips"):
        st.markdown("""
        ### Google Drive Upload:
        1. Enable Google Drive upload in the sidebar
        2. Enter the folder ID from your Google Drive
        3. The folder ID is the last part of the URL when you open the folder in Drive
        
        ### Single Post Download:
        1. Find a Reddit post containing media (video, image, or gallery)
        2. Copy either:
           - The full post URL (e.g., `https://reddit.com/r/subreddit/comments/...)`
           - Just the post ID (the random characters after `/comments/` in the URL)
        3. Paste it into the input field
        4. Click "Download Single Post Media"
        
        ### Subreddit Scraper:
        1. Enter the subreddit name (without r/)
        2. Choose the number of posts to scan (max 100)
        3. Select sorting method (hot, new, or top)
        4. Choose media types to include
        5. Click "Scrape and Download Media"
        6. Download the ZIP file or upload to Drive
        
        ### Notes:
        - Video downloads include audio when available
        - Supported image formats: JPG, JPEG, PNG, GIF, WEBP
        - All temporary files are automatically cleaned up
        - Large subreddit scrapes may take some time
        - Downloaded files are named using post titles and IDs
        """)

if __name__ == "__main__":
    if "username" not in st.session_state:
        st.session_state.username = "d0ughnat"
    main()
