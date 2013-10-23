# Use FFmpeg to create a python generator with encoded webm data from the screen.

# Linux-only (depends on on x11grab and alsa devices)

# Video --
# https://trac.ffmpeg.org/wiki/How%20to%20grab%20the%20desktop%20%28screen%29%20with%20FFmpeg
# ffmpeg -video_size 1024x768 -framerate 25 -f x11grab -i :0.0+100,200 -f alsa -ac 2 -i pulse output.flv
# `videodevice' is in form [hostname]:display_number.screen_number[+x_offset,y_offset]

# Audio --
# http://ffmpeg.org/ffmpeg-devices.html#alsa-1
# `audiodevice' can also be in the form: hw:CARD[,DEV[,SUBDEV]]

import ingest

def screencast(framerate=25, videosize=(1920,1080), xyoffset=(0,0), videodevice=":0.0", 
               audiodevice="pulse",
               chunksize=2**20):
    input_spec = ["./ffmpeg", 
                  "-video_size", "%dx%d" % videosize,
                  "-framerate", "%d" % (framerate),
                  "-f", "x11grab",
                  "-i", "%s+%d,%d" % (videodevice, xyoffset[0], xyoffset[1]),
                  "-f", "alsa",
                  "-ac", "2",
                  "-i", audiodevice]

    for c in ingest.encode(input_spec, chunksize=chunksize):
        yield c
