import streamlit as st
import praw
import os
from yt_dlp import YoutubeDL
from datetime import datetime
import re
import hashlib
import requests
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import tempfile
import zipfile
import io
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Page configuration
st.set_page_config(
    page_title="Reddit Media Downloader",
    page_icon="🎥",
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
            <div>User: d0ughnat</div>
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

def download_image(url, output_path):
    """Download image from URL"""
    try:
        response = requests.get(url)
        response.raise_for_status()
        
        with open(output_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        st.error(f"Image download error: {str(e)}")
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
            info = ydl.extract_info(url, download=False)
            if not info:
                return False
            ydl.download([url])
            return True
            
    except Exception as e:
        st.error(f"Download error: {str(e)}")
        return False

def update_progress(d, progress_bar):
    """Update download progress bar"""
    if d['status'] == 'downloading':
        try:
            total = d.get('total_bytes', 0) or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                progress = downloaded / total
                progress_bar.progress(progress)
        except:
            pass

def get_subreddit_media(subreddit_name, limit, sort_by="hot", include_videos=True, include_images=True):
    """Scrape media posts from a subreddit"""
    reddit = get_reddit_client()
    try:
        subreddit = reddit.subreddit(subreddit_name)
        media_posts = []
        
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
            if post.is_video and include_videos:
                if hasattr(post, 'media') and post.media and 'reddit_video' in post.media:
                    media_posts.append({
                        'type': 'video',
                        'url': post.url,
                        'title': post.title,
                        'id': post.id,
                        'direct_url': post.media['reddit_video']['fallback_url']
                    })
            elif include_images and hasattr(post, 'url'):
                url = post.url.lower()
                if any(url.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif']):
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
                safe_filename = get_safe_filename(post['title'], post['id']) + file_extension
                temp_path = os.path.join(temp_dir, safe_filename)
                
                success = False
                if post['type'] == 'video':
                    success = download_reddit_video(post['url'], temp_path)
                else:
                    success = download_image(post['url'], temp_path)
                
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
        creds_data = st.secrets["gcp_service_account"]
        
        creds = Credentials.from_service_account_info(dict(creds_data))
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

def upload_zip_to_drive(zip_data, filename, folder_id):
    """Upload zip data directly to Google Drive"""
    try:
        # Save zip data to temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_file.write(zip_data)
            temp_path = temp_file.name

        # Upload to Drive
        drive_url = upload_to_drive(temp_path, folder_id)
        
        # Clean up
        os.unlink(temp_path)
        
        return drive_url

    except Exception as e:
        st.error(f"Drive upload error: {str(e)}")
        return None

def main():
    display_user_info()
    st.title("🎥 Reddit Media Downloader")
    
    # Drive folder ID input in sidebar
    with st.sidebar:
        st.header("Google Drive Settings")
        drive_folder_id = st.text_input(
            "Drive Folder ID:",
            help="Enter the Google Drive folder ID where files should be uploaded"
        )
        enable_drive_upload = st.checkbox("Enable Google Drive Upload", value=False)
    
    # Tab selection
    tab1, tab2 = st.tabs(["Single Post Download", "Subreddit Scraper"])
    
    with tab1:
        url_or_id = st.text_input(
            "Enter Reddit post URL or ID:",
            help="You can enter either a full Reddit post URL or just the post ID"
        )
        
        if st.button("Download Single Video", use_container_width=True):
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
                
                if not submission.is_video:
                    st.error("This post does not contain a Reddit-hosted video")
                    return
                    
                progress_text = st.empty()
                progress_bar = st.progress(0)
                progress_text.text("Starting download...")
                
                output_path = get_safe_filename(submission.title, submission.id) + '.mp4'
                
                with st.spinner('Downloading video with audio...'):
                    if download_reddit_video(submission.url, output_path, progress_bar):
                        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                            st.video(output_path)
                            
                            # Google Drive upload option
                            if enable_drive_upload:
                                if not drive_folder_id:
                                    st.error("Please enter a Google Drive folder ID in the sidebar")
                                else:
                                    with st.spinner("Uploading to Google Drive..."):
                                        drive_url = upload_to_drive(output_path, drive_folder_id)
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
                                
                            progress_text.text("Download completed successfully!")
                        else:
                            st.error("Download failed: Output file is empty or missing")
                            
                        if os.path.exists(output_path):
                            os.remove(output_path)
                            
            except Exception as e:
                st.error(f"Error: {str(e)}")
                if 'output_path' in locals() and os.path.exists(output_path):
                    os.remove(output_path)
    
    with tab2:
        col1, col2, col3 = st.columns(3)
        
        with col1:
            subreddit_name = st.text_input("Subreddit name:", help="Enter subreddit name without r/")
        
        with col2:
            post_limit = st.number_input("Number of posts to scrape:", min_value=1, max_value=100, value=10)
        
        with col3:
            sort_by = st.selectbox("Sort by:", ["hot", "new", "top"])
        
        col4, col5 = st.columns(2)
        
        with col4:
            include_videos = st.checkbox("Include videos", value=True)
        
        with col5:
            include_images = st.checkbox("Include images", value=True)
        
        if st.button("Scrape and Download Media", use_container_width=True):
            if not subreddit_name:
                st.error("Please enter a subreddit name")
                return
                
            if not (include_videos or include_images):
                st.error("Please select at least one media type (videos or images)")
                return
                
            try:
                progress_text = st.empty()
                progress_bar = st.progress(0)
                progress_text.text("Fetching posts from subreddit...")
                
                media_posts = get_subreddit_media(
                    subreddit_name,
                    post_limit,
                    sort_by,
                    include_videos,
                    include_images
                )
                
                if not media_posts:
                    st.warning("No media posts found matching your criteria")
                    return
                
                st.info(f"Found {len(media_posts)} media posts")
                
                progress_text.text("Starting batch download...")
                zip_data = batch_download_media(media_posts, progress_text, progress_bar)
                
                progress_text.text("Download completed!")
                
                # Google Drive upload option
                if not drive_folder_id:
                        st.error("Please enter a Google Drive folder ID in the sidebar")
                else:
                    with st.spinner("Uploading to Google Drive..."):
                      zip_filename = f"reddit_{subreddit_name}_media_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
                      drive_url = upload_zip_to_drive(zip_data, zip_filename, drive_folder_id)
                      if drive_url:
                        st.success(f"Uploaded to Drive: [View File]({drive_url})")
                
                # Local download option
                st.download_button(
                    label="📦 Download All Media (ZIP)",
                    data=zip_data,
                    file_name=f"reddit_{subreddit_name}_media_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip",
                    use_container_width=True
                )
                
            except Exception as e:
                st.error(f"Error during subreddit scraping: {str(e)}")
    
    # Instructions
    with st.expander("Instructions and Tips"):
        st.markdown("""
        ### Google Drive Upload:
        1. Enable Google Drive upload in the sidebar
        2. Enter the folder ID from your Google Drive
        3. The folder ID is the last part of the URL when you open the folder in Drive
        
        ### Single Post Download:
        1. Find a Reddit post containing a video
        2. Copy either:
           - The full post URL (e.g., `https://reddit.com/r/subreddit/comments/...)`
           - Just the post ID (the random characters after `/comments/` in the URL)
        3. Paste it into the input field
        4. Click "Download Single Video"
        
        ### Subreddit Scraper:
        1. Enter the subreddit name (without r/)
        2. Choose the number of posts to scan
        3. Select sorting method
        4. Choose media types to include
        5. Click "Scrape and Download Media"
        6. Download the ZIP file or upload to Drive
        
        ### Notes:
        - Video downloads only work with videos hosted directly on Reddit
        - Downloads the best available quality with audio for videos
        - Supported image formats: JPG, JPEG, PNG, GIF
        - All temporary files are automatically cleaned up
        - Large subreddit scrapes may take some time
        - Google Drive uploads require proper service account configuration
        """)

if __name__ == "__main__":
    main()
