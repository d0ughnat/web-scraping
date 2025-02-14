import streamlit as st
import requests
import praw
import pandas as pd
from urllib.parse import unquote
import time
import prawcore

# Initialize Reddit API client
reddit = praw.Reddit(
    client_id=st.secrets["reddit"]["client_id"],
    client_secret=st.secrets["reddit"]["client_secret"],
    user_agent=st.secrets["reddit"]["user_agent"]
)

# Configure Streamlit page
st.set_page_config(
    page_title="Reddit Media Scraper",
    page_icon="\U0001F4E5",
    layout="wide"
)

def extract_media_from_submission(submission):
    """Extract media from a single Reddit submission"""
    media_urls = []
    try:
        if hasattr(submission, 'gallery_data'):
            for item in submission.gallery_data['items']:
                media_id = item['media_id']
                metadata = submission.media_metadata[media_id]
                if metadata['status'] == 'valid':
                    if metadata['e'] == 'Image':
                        image_url = metadata['s']['u']
                        media_urls.append(('image', image_url, f"gallery_{submission.id}_{media_id}.jpg"))

        elif hasattr(submission, 'url'):
            url = submission.url
            if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                ext = url.split('.')[-1]
                media_urls.append(('image', url, f"{submission.id}_image.{ext}"))

        if submission.is_video and hasattr(submission, 'media'):
            video_url = submission.media['reddit_video']['fallback_url']
            media_urls.append(('video', video_url, f"{submission.id}_video.mp4"))

        elif hasattr(submission, 'preview'):
            try:
                preview_url = submission.preview['images'][0]['source']['url']
                media_urls.append(('image', preview_url, f"{submission.id}_preview.jpg"))
            except (KeyError, IndexError):
                pass

    except Exception as e:
        st.warning(f"Error processing media content for post {submission.id}: {str(e)}")

    return media_urls

def get_subreddit_media(subreddit_name, limit=50, sort='hot'):
    """Get media from a subreddit"""
    try:
        media_urls = []
        subreddit = reddit.subreddit(subreddit_name)

        if sort == 'hot':
            posts = subreddit.hot(limit=limit)
        elif sort == 'new':
            posts = subreddit.new(limit=limit)
        elif sort == 'top':
            posts = subreddit.top(limit=limit)
        else:
            st.error("Invalid sorting option.")
            return []

        progress_bar = st.progress(0)
        for i, post in enumerate(posts):
            progress_bar.progress((i + 1) / limit)
            media_urls.extend(extract_media_from_submission(post))
            time.sleep(0.1)
        progress_bar.empty()

        return list(dict.fromkeys(media_urls))

    except prawcore.exceptions.NotFound:
        st.error(f"The subreddit r/{subreddit_name} does not exist.")
    except prawcore.exceptions.Forbidden:
        st.error(f"The subreddit r/{subreddit_name} is private or banned.")
    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")
    return []

def get_post_media(post_url):
    """Get media from a specific post"""
    try:
        submission = reddit.submission(url=post_url)
        return extract_media_from_submission(submission)
    except Exception as e:
        st.error(f"Error accessing post: {str(e)}")
        return []

def main():
    st.title("\U0001F4E5 Reddit Media Scraper")

    scrape_type = st.radio("What would you like to scrape?", ["Single Post", "Subreddit"])

    if scrape_type == "Single Post":
        post_url = st.text_input("Enter Reddit post URL:")
        if post_url:
            if st.button("Scrape Post"):
                with st.spinner("Scraping media from post..."):
                    media_urls = get_post_media(post_url)
                    if media_urls:
                        st.success(f"Found {len(media_urls)} media files")
                        display_media_downloads(media_urls)
                    else:
                        st.warning("No media found in this post")

    else:
        col1, col2, col3 = st.columns([2, 1, 1])

        with col1:
            subreddit_name = st.text_input("Enter subreddit name (without r/, e.g., 'all' for r/all):")
        with col2:
            sort_by = st.selectbox("Sort by:", ['hot', 'new', 'top'])
        with col3:
            limit = st.number_input("Number of posts to scan:", min_value=1, max_value=500, value=100)

        if subreddit_name:
            if st.button("Scrape Subreddit"):
                with st.spinner(f"Scraping media from r/{subreddit_name}..."):
                    media_urls = get_subreddit_media(subreddit_name, limit, sort_by)
                    if media_urls:
                        st.success(f"Found {len(media_urls)} media files")
                        display_media_downloads(media_urls)
                    else:
                        st.warning("No media found in this subreddit")

def display_media_downloads(media_urls):
    df = pd.DataFrame(media_urls, columns=['Type', 'URL', 'Filename'])
    st.dataframe(df[['Type', 'Filename']])

    st.write("Download Options:")
    col1, col2 = st.columns(2)

    with col1:
        image_urls = [(url, filename) for type_, url, filename in media_urls if type_ == 'image']
        if image_urls:
            st.write(f"Images found: {len(image_urls)}")
            for url, filename in image_urls:
                try:
                    response = requests.get(url)
                    if response.status_code == 200:
                        st.download_button(
                            label=f"Download {filename}",
                            data=response.content,
                            file_name=filename,
                            mime="image/jpeg"
                        )
                except Exception as e:
                    st.error(f"Error downloading {filename}: {str(e)}")

    with col2:
        video_urls = [(url, filename) for type_, url, filename in media_urls if type_ == 'video']
        if video_urls:
            st.write(f"Videos found: {len(video_urls)}")
            for url, filename in video_urls:
                try:
                    response = requests.get(url)
                    if response.status_code == 200:
                        st.download_button(
                            label=f"Download {filename}",
                            data=response.content,
                            file_name=filename,
                            mime="video/mp4"
                        )
                except Exception as e:
                    st.error(f"Error downloading {filename}: {str(e)}")

if __name__ == "__main__":
    main()
