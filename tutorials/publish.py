"""Publishing: YouTube + TikTok upload stubs.

Both are OFF unless credentials are configured — the assembler's job ends at
"MP4 in storage", publishing is a separate explicit act. Platform notes that
shape this module (verified Aug 2026):

- YouTube Data API: one video.insert costs 1600 quota units against a 10k/day
  default — ~6 uploads/day until Google approves a quota extension. Apply
  before launch at scale. Set selfDeclaredMadeForKids correctly and the
  AI-generated content disclosure (altered/synthetic media flag).
- TikTok Content Posting API: apps must pass audit before posting publicly;
  unaudited apps can only create PRIVATE drafts. Complete the audit first.
"""
import json
import os


def youtube_enabled():
    return bool(os.environ.get("YT_CLIENT_SECRETS") or os.environ.get("YT_TOKEN_JSON"))


def tiktok_enabled():
    return bool(os.environ.get("TIKTOK_ACCESS_TOKEN"))


def upload_youtube(video_path, title, description, tags=(), made_for_kids=False):
    """Upload via YouTube Data API v3. Requires google-api-python-client and
    OAuth credentials in YT_TOKEN_JSON (refresh-token flow; a serverless
    worker can't do the interactive consent dance)."""
    if not youtube_enabled():
        return {"skipped": "YouTube credentials not configured"}
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = Credentials.from_authorized_user_info(
        json.loads(os.environ["YT_TOKEN_JSON"]),
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    yt = build("youtube", "v3", credentials=creds)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": list(tags)[:30],
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": os.environ.get("YT_PRIVACY", "unlisted"),
            "selfDeclaredMadeForKids": made_for_kids,
            # Platform AI-content disclosure.
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    return {"youtube_video_id": response["id"],
            "url": f"https://youtu.be/{response['id']}"}


def upload_tiktok(video_path, title):
    """TikTok Content Posting API (direct post). Left as a guarded stub:
    posting publicly requires a platform-audited app, and the upload flow
    (init -> chunked PUT -> publish poll) is worth wiring only once the
    audit is granted."""
    if not tiktok_enabled():
        return {"skipped": "TikTok credentials not configured"}
    return {"skipped": "TikTok direct post not implemented — complete the "
                       "Content Posting API audit, then wire the chunked "
                       "upload flow here"}
