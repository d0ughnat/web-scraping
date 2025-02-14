import streamlit as st
import requests
import praw
import pandas as pd
import re
from urllib.parse import unquote, parse_qs, urlparse
import time

# Initialize Reddit API client
reddit = praw.Reddit(
    client_id=st.secrets["reddit"]["client_id"],
    client_secret=st.secrets["reddit"]["client_secret"],
    user_agent=st.secrets["reddit"]["user_agent"]
)

# Configure Streamlit page
st.set_page_config(
    page_title="Reddit Media Search Downloader",
    page_icon="🔍",
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

def extract_search_query(url):
    """Extract search query from Reddit search URL"""
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    return query_params.get('q', [None])[0]

def get_media_from_submission(submission):
    """Extract media from a single Reddit submission"""
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
                        media_urls.append(('image', image_url, f"gallery_{submission.id}_{media_id}.jpg"))

        # Handle direct images
        elif hasattr(submission, 'url'):
            url = submission.url
            if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                ext = url.split('.')[-1]
                media_urls.append(('image', url, f"{submission.id}_image.{ext}"))

        # Handle videos
        if submission.is_video and hasattr(submission, 'media'):
            video_url = submission.media['reddit_video']['fallback_url']
            media_urls.append(('video', video_url, f"{submission.id}_video.mp4"))

        # Handle image previews
        elif hasattr(submission, 'preview'):
            try:
                preview_url = submission.preview['images'][0]['source']['url']
                media_urls.append(('image', preview_url, f"{submission.id}_preview.jpg"))
            except (KeyError, IndexError):
                pass

    except Exception as e:
        st.warning(f"Error processing media content for post {submission.id}: {str(e)}")

    return media_urls

def get_reddit_search_media(query, limit=50, media_only=True):
    """Search Reddit and extract media from results"""
    try:
        media_urls = []
        search_results = []

        # Use Reddit's search
        if media_only:
            # Search only media posts
            search_results = reddit.subreddit('all').search(query, sort='hot', limit=limit, params={'type': 'link'})
        else:
            # Search all posts
            search_results = reddit.subreddit('all').search(query, sort='hot', limit=limit)

        with st.progress(0) as progress_bar:
            for i, post in enumerate(search_results):
                # Update progress
                progress_bar.progress((i + 1) / limit)
                
                # Skip non-media posts if media_only is True
                if media_only and not (hasattr(post, 'preview') or post.is_video or 
                                     hasattr(post, 'gallery_data') or 
                                     (hasattr(post, 'url') and any(post.url.lower().endswith(ext) 
                                      for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4']))):
                    continue
                
                media_urls.extend(get_media_from_submission(post))
                time.sleep(0.1)  # Small delay to avoid rate limiting

        # Clean URLs and remove duplicates
        cleaned_urls = []
        seen = set()
        for media_type, url, filename in media_urls:
            cleaned_url = unquote(url).replace('&amp;', '&')
            if cleaned_url not in seen:
                seen.add(cleaned_url)
                cleaned_urls.append((media_type, cleaned_url, filename))

        return cleaned_urls

    except Exception as e:
        st.error(f"Error during search: {str(e)}")
        return []

def main():
    st.title("🔍 Reddit Media Search Downloader")
    
    # Input options
    col1, col2 = st.columns([3, 1])
    
    with col1:
        search_input = st.text_input("Enter search term or Reddit search URL:")
    
    with col2:
        limit = st.number_input("Number of posts to scan:", min_value=10, max_value=100, value=50)
    
    media_only = st.checkbox("Only search media posts", value=True)
    
    if search_input:
        # Extract query if it's a URL, otherwise use the input directly
        if 'reddit.com/search' in search_input:
            query = extract_search_query(search_input)
            if not query:
                st.error("Couldn't extract search query from URL")
                return
        else:
            query = search_input
        
        if st.button("Search and Scan Media"):
            with st.spinner(f"Searching Reddit for '{query}' and scanning for media..."):
                media_urls = get_reddit_search_media(query, limit, media_only)
                
                if media_urls:
                    # Display results in a table
                    df = pd.DataFrame(media_urls, columns=['Type', 'URL', 'Filename'])
                    st.write(f"Found {len(media_urls)} media files")
                    st.dataframe(df[['Type', 'Filename']])
                    
                    # Add "Download All" buttons
                    st.write("Download Options:")
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        # Count images
                        image_count = sum(1 for t, _, _ in media_urls if t == 'image')
                        if image_count > 0:
                            if st.button(f"Download All Images ({image_count})"):
                                for media_type, url, filename in media_urls:
                                    if media_type == 'image':
                                        try:
                                            response = requests.get(url)
                                            if response.status_code == 200:
                                                st.download_button(
                                                    label=f"Save {filename}",
                                                    data=response.content,
                                                    file_name=filename,
                                                    mime="image/jpeg"
                                                )
                                        except Exception as e:
                                            st.error(f"Error downloading {filename}: {str(e)}")
                    
                    with col2:
                        # Count videos
                        video_count = sum(1 for t, _, _ in media_urls if t == 'video')
                        if video_count > 0:
                            if st.button(f"Download All Videos ({video_count})"):
                                for media_type, url, filename in media_urls:
                                    if media_type == 'video':
                                        try:
                                            response = requests.get(url)
                                            if response.status_code == 200:
                                                st.download_button(
                                                    label=f"Save {filename}",
                                                    data=response.content,
                                                    file_name=filename,
                                                    mime="video/mp4"
                                                )
                                        except Exception as e:
                                            st.error(f"Error downloading {filename}: {str(e)}")
                    
                    # Individual download buttons
                    st.write("Individual Files:")
                    for media_type, url, filename in media_urls:
                        try:
                            response = requests.get(url)
                            if response.status_code == 200:
                                st.download_button(
                                    label=f"Download {filename}",
                                    data=response.content,
                                    file_name=filename,
                                    mime=f"{'image' if media_type == 'image' else 'video'}/{'jpeg' if media_type == 'image' else 'mp4'}"
                                )
                        except Exception as e:
                            st.error(f"Error downloading {filename}: {str(e)}")
                else:
                    st.warning("No media found in search results")

if __name__ == "__main__":
    main()
