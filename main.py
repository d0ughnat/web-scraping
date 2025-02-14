import streamlit as st
import requests
import praw
import pandas as pd
import re
from urllib.parse import unquote

# Initialize Reddit API client
reddit = praw.Reddit(
    client_id=st.secrets["reddit"]["client_id"],
    client_secret=st.secrets["reddit"]["client_secret"],
    user_agent=st.secrets["reddit"]["user_agent"]
)

# Configure Streamlit page
st.set_page_config(
    page_title="Reddit Media Downloader",
    page_icon="📥",
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
                            media_urls.append(('image', image_url, f"gallery_{media_id}.jpg"))

            # Handle direct images
            elif hasattr(submission, 'url'):
                url = submission.url
                if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                    ext = url.split('.')[-1]
                    media_urls.append(('image', url, f"image.{ext}"))

            # Handle videos
            if submission.is_video and hasattr(submission, 'media'):
                video_url = submission.media['reddit_video']['fallback_url']
                media_urls.append(('video', video_url, "video.mp4"))

            # Handle image previews
            elif hasattr(submission, 'preview'):
                try:
                    preview_url = submission.preview['images'][0]['source']['url']
                    media_urls.append(('image', preview_url, "preview.jpg"))
                except (KeyError, IndexError):
                    pass

        except Exception as e:
            st.warning(f"Error processing media content: {str(e)}")

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
        st.error(f"Error: {str(e)}")
        return []

def main():
    st.title("📥 Reddit Media Downloader")
    
    # Input field for Reddit URL
    url = st.text_input("Enter Reddit post URL:")
    
    if url:
        if st.button("Scan Media"):
            with st.spinner("Scanning for media..."):
                media_urls = get_reddit_media(url)
                
                if media_urls:
                    # Display results in a table
                    df = pd.DataFrame(media_urls, columns=['Type', 'URL', 'Filename'])
                    st.dataframe(df[['Type', 'Filename']])
                    
                    # Create download buttons for each media file
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
                            else:
                                st.error(f"Failed to fetch {filename}")
                        except Exception as e:
                            st.error(f"Error downloading {filename}: {str(e)}")
                else:
                    st.warning("No media found in this post")

if __name__ == "__main__":
    main()
