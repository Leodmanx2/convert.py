#!/usr/bin/env python3
"""
This is a Python 3 script for batch encoding files to be played in an
HMTL5 video element. It requires that ffmpeg be in the search path. To use,
simply invoke it from the directory containing the files you wish to encode.
The outputs will be created in a subdirectory called 'hardsubbed'.
"""

__version__ = "1.1.0"

import os
from subprocess import run
import sys
from glob import glob
import re
import json

def get_audio_flags(codec, channels, index):
    # If the audio is stereo AAC, we can skip re-encoding to preserve quality
    if codec == "aac" and channels == "2":
        return ["-c:a", "copy",
                "-map", "0:a:{}".format(index)]
    if codec != "none":
        return ["-c:a", "aac",
                "-b:a", "192k",
                "-ac", "2",
                "-map", "0:a:{}".format(index)]
    return []

def get_filter_flags(codec, index, subfile):
    # Hard-subbing picture-based subtitles requires a different filter from
    # text-based subtitles
    if codec in ("dvd_subtitle", "hdmv_pgs_subtitle"):
        subfilter = "[0:v][0:s:{}]overlay[burned];".format(index)
    elif codec != "none":
        subfilter = "[0:v]subtitles='{}':si={}[burned];".format(subfile, index)
    else:
        subfilter = "[0:v]null[burned];"
    return ["-filter_complex", "{}[burned]scale=-16:min(720\\,ih)[v]".format(subfilter),
            "-map", "[v]"]

def get_key(file):
    match = re.match(r"\[(.+)\] (.+) - (\d+) .*", file)
    return match.group(2) if match else file

def print_stream_info(streams):
    stream_index = 0
    for stream in streams:
        tags = stream["tags"]
        stream_title = tags.get("title", "No Title")
        stream_language = tags.get("language", "Unknown")
        print("{}: {} ({})".format(stream_index, stream_title, stream_language))
        stream_index += 1

def main():
    if not os.path.exists('hardsubbed'):
        try:
            os.mkdir("hardsubbed")
        except OSError as error:
            print(error, file=sys.stderr)
            sys.exit()

    chosen_tracks = {}

    file_list = glob("*.mkv") + glob("*.mp4")
    file_list = sorted(file_list)

    # Do a first pass through all the files to select the streams to be used.
    # We collect all this information at the beginning so that the process does
    # not need to be monitored for prompts. The onus is on the user to supply
    # valid 0-based stream indices. If an invalid stream number is given, the
    # encode will simply fail. We assume the stream indices will be identical
    # for all files of a particular series.
    for file in file_list:
        key = get_key(file)

        if key in chosen_tracks:
            continue

        results = run(["ffprobe",
                       "-hide_banner",
                       "-loglevel", "error",
                       "-i", file,
                       "-show_entries", "stream=codec_type,codec_name,channels:stream_tags=language,title",
                       "-of", "json"],
                      capture_output=True)
        if results.returncode != 0:
            print("probe failed with code: {}".format(results.returncode), file=sys.stderr)

        stream_data = json.loads(results.stdout.decode("utf-8"))

        audio_streams = [stream for stream in stream_data["streams"] if stream["codec_type"] == "audio"]
        subtitle_streams = [stream for stream in stream_data["streams"] if stream["codec_type"] == "subtitle"]

        if len(audio_streams) > 1:
            print("Please choose which audio stream to use for {}:".format(key))
            print_stream_info(audio_streams)
            audio_stream = int(input("Choice: "))
            audio_channels = audio_streams[audio_stream]["channels"]
            audio_codec = audio_streams[audio_stream]["codec_name"]
        elif len(audio_streams) == 1:
            audio_stream = 0
            audio_channels = audio_streams[audio_stream]["channels"]
            audio_codec = audio_streams[audio_stream]["codec_name"]
        else:
            audio_stream = -1
            audio_channels = -1
            audio_codec = "none"

        if len(subtitle_streams) > 1:
            print("Please choose which subtitle stream to use for {}:".format(key))
            print_stream_info(subtitle_streams)
            subtitle_stream = int(input("Choice: "))
            subtitle_codec = subtitle_streams[subtitle_stream]["codec_name"]
        elif len(subtitle_streams) == 1:
            subtitle_stream = 0
            subtitle_codec = subtitle_streams[subtitle_stream]["codec_name"]
        else:
            subtitle_stream = -1
            subtitle_codec = "none"

        chosen_tracks[key] = {"audio_index": audio_stream,
                              "subtitle_index": subtitle_stream,
                              "audio_codec": audio_codec,
                              "audio_channels": audio_channels,
                              "subtitle_codec": subtitle_codec}

    for file in file_list:
        print("Encoding {}...".format(file))
        # If the encodes proceed too slowly, erase "-preset:v veryslow"
        # or choose a suitable preset like 'fast'.
        video_flags = ["-c:v", "libx264",
                       "-profile:v", "main",
                       "-preset:v", "veryslow",
                       "-crf", "18",
                       "-tune", "animation",
                       "-bf", "16",
                       "-aq-mode", "2",
                       "-pix_fmt", "yuv420p"]

        key = get_key(file)
        track_info = chosen_tracks[key]

        audio_codec = track_info["audio_codec"]
        audio_channels = track_info["audio_channels"]
        audio_index = track_info["audio_index"]
        audio_flags = get_audio_flags(audio_channels, audio_codec, audio_index)

        # TODO: Search for sub file if not embedded
        subtitle_codec = track_info["subtitle_codec"]
        subtitle_index = track_info["subtitle_index"]
        filter_flags = get_filter_flags(subtitle_codec, subtitle_index, file)

        try:
            encode_results = run(["ffmpeg", "-hide_banner",
                                  "-loglevel", "warning",
                                  "-stats",
                                  "-i", "{}".format(file)] +
                                 video_flags +
                                 audio_flags +
                                 filter_flags +
                                 ["hardsubbed/{}.mp4".format(os.path.splitext(file)[0])])
            if encode_results.returncode != 0:
                print("encode failed with invocation: {}".format(encode_results.args), file=sys.stderr)
            print("Done\n")
        except OSError as error:
            print(error, file=sys.stderr)
            print("skipping file\n", file=sys.stderr)
            continue

if __name__ == "__main__":
    main()
