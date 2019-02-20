from pathlib import Path
import logging

import falcon
import youtube_dl


logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def check_ffmpeg_libav():
    import shutil
    import sys

    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        log.error(
            "either ffprobe or ffmpeg could not be located. "
            "ensure that ffmpeg is installed, and that both ffprobe and "
            "ffmpeg are in PATH."
        )
        sys.exit(-1)


check_ffmpeg_libav()

# https://github.com/rg3/youtube-dl/blob/master/youtube_dl/YoutubeDL.py#L140
YTDL_OPTS = dict(
    quiet=True,
    default_search="auto",
    noplaylist=True,
    outtmpl="cache/audio/%(id)s",
    postprocessors=[dict(key="FFmpegExtractAudio", preferredcodec="opus")],
)


# videos longer than this (in seconds) will be refused.
MAX_VIDEO_DURATION = 12 * 60


def s2m(seconds: int) -> str:
    """Convert seconds to minutes:seconds string."""
    minutes = seconds // 60
    return f"{minutes}:{seconds - minutes * 60:02}"


def response_for_duration(duration: int) -> dict:
    if duration > MAX_VIDEO_DURATION:
        return dict(
            ok=False,
            reason=(
                f"Video is too long at {duration}s ({s2m(duration)}). "
                f"Maximum duration is {MAX_VIDEO_DURATION}s "
                f"({s2m(MAX_VIDEO_DURATION)})."
            ),
        )
    else:
        return dict(ok=True)


class V1Status:
    def on_get(self, req: falcon.Request, res: falcon.Response) -> None:
        """Get current jukebox status."""
        res.media = dict(ok=True)


class V1Lookup:
    def on_get(
        self, req: falcon.Request, res: falcon.Response, search_term: str
    ) -> None:
        """Search for a specific video to request."""
        log.info(f"looking up '{search_term}'")
        with youtube_dl.YoutubeDL(YTDL_OPTS) as ytdl:
            info = ytdl.extract_info(search_term, download=False)
        try:
            choice = info["entries"][0]
        except KeyError:
            res.media = dict(
                ok=False,
                reason=f"Nothing found for search term '{search_term}",
            )
            res.status = falcon.HTTP_400
            return

        res.media = dict(
            **response_for_duration(choice["duration"]),
            token=choice["id"],
            video_info={
                k: choice.get(k)
                for k in (
                    "alt_title",
                    "artist",
                    "creator",
                    "description",
                    "title",
                    "track",
                    "uploader",
                    "webpage_url",
                    "viewcount",
                    "duration",
                )
            },
        )


class V1Enqueue:
    def on_get(
        self, req: falcon.Request, res: falcon.Response, video_id: str
    ) -> None:
        url = f"https://youtu.be/{video_id}"

        log.info(f"extracting info for {url}")
        with youtube_dl.YoutubeDL(YTDL_OPTS) as ytdl:
            info = ytdl.extract_info(url, download=False)

        audio_file_path = Path("./cache/audio") / f"{info['id']}.opus"

        if audio_file_path.exists():
            log.info(f"skipping download as {audio_file_path} already exists.")
            res.media = dict(ok=True)
            return

        duration_response = response_for_duration(info["duration"])
        if not duration_response["ok"]:
            res.media = duration_response
            res.status = falcon.HTTP_400
            return

        url = f"https://youtu.be/{info['id']}"

        log.info(f"downloading {url}")
        with youtube_dl.YoutubeDL(YTDL_OPTS) as ytdl:
            ytdl.download([url])

        log.info(f"this is where we queue up {audio_file_path}")

        res.media = dict(ok=True)


def create_app() -> falcon.API:
    app = falcon.API()
    app.add_route("/v1/status", V1Status())
    app.add_route("/v1/lookup/{search_term}", V1Lookup())
    app.add_route("/v1/enqueue/{video_id}", V1Enqueue())
    return app


application = create_app()
