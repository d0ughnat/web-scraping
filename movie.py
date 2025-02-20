import streamlit as st
import praw
import os
from yt_dlp import YoutubeDL
from datetime import datetime

# Initialize Reddit client
reddit = praw.Reddit(
    client_id=st.secrets["reddit"]["client_id"],
    client_secret=st.secrets["reddit"]["client_secret"],
    user_agent=st.secrets["reddit"]["user_agent"]
)

def download_reddit_video(url, output_path):
    """Download Reddit video with audio using yt-dlp"""
    try:
        ydl_opts = {
            'format': 'bv*+ba/b',  # Best video + best audio / best combined format
            'outtmpl': output_path,
            'quiet': False,  # Set to True to hide download progress
            'no_warnings': False,  # Set to True to hide warnings
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        
        with YoutubeDL(ydl_opts) as ydl:
            # First get info to verify video exists
            try:
                info = ydl.extract_info(url, download=False)
                st.info(f"Found video: {info.get('title', 'Untitled')}")
            except Exception as e:
                st.error(f"Error extracting video info: {str(e)}")
                return False
            
            # Then download
            ydl.download([url])
            
        return True
    except Exception as e:
        st.error(f"Download error: {str(e)}")
        return False

# Streamlit UI
st.title("Reddit Video Downloader")

# Display current time
current_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
st.write(f"Current UTC time: {current_time}")

url_or_id = st.text_input("Enter Reddit post URL or ID:")

if st.button("Download Video"):
    if url_or_id:
        try:
            # Convert ID to full URL if needed
            if '/' not in url_or_id:
                submission = reddit.submission(id=url_or_id)
                url = submission.url  # Use direct URL instead of permalink
            else:
                url = url_or_id
                
            with st.spinner('Downloading video with audio...'):
                output_path = 'downloaded_video.mp4'
                
                # Download video with audio
                if download_reddit_video(url, output_path):
                    # Check if file exists and has size
                    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                        # Display video
                        st.video(output_path)
                        st.success("Video downloaded successfully!")
                        
                        # Add download button
                        with open(output_path, 'rb') as f:
                            st.download_button(
                                label="Download Video",
                                data=f,
                                file_name="reddit_video.mp4",
                                mime="video/mp4"
                            )
                    else:
                        st.error("Download failed: Output file is empty or missing")
                
                # Clean up
                if os.path.exists(output_path):
                    os.remove(output_path)
                    
        except Exception as e:
            st.error(f"Error: {str(e)}")
            if os.path.exists('downloaded_video.mp4'):
                os.remove('downloaded_video.mp4')
    else:
        st.error("Please enter a valid Reddit post URL or ID")
