import Image
import numpy as np
import subprocess
import re

FFMPEG = "./ffmpeg"
BASEDIR = "."

def video_info(path):
    cmd = [FFMPEG, '-i', path]
    p = subprocess.Popen(cmd, stderr=subprocess.PIPE, cwd=BASEDIR)
    stdout, stderr = p.communicate()

    out = {}

    # eg.:
    # Duration: 01:37:20.86, start: 0.000000, bitrate: 5465 kb/s
    #   Stream #0.0(eng): Video: h264 (Main), yuv420p, 1280x720, 2502 kb/s, 21.60 fps, 25 tbr, 3k tbn, 6k tbc

    dur_match = re.search(r'Duration: (\d\d):(\d\d):(\d\d).(\d\d)', stderr)

    if dur_match:
        h, m, s, ms = [int(x) for x in dur_match.groups()]
        out["duration"] = s + ms/100.0 + 60*(m + 60*h)
    else:
        out["duration"] = None

    wh_match = re.search(r'Stream .*[^\d](\d\d+)x(\d\d+)[^\d]', stderr)
    w,h = [int(x) for x in wh_match.groups()]
    out["width"] = w
    out["height"] = h

    return out

def video_frames(path, width=320, height=240, fps=30):
    cmd = [FFMPEG, '-i', path, 
           '-vf', 'scale=%d:%d'%(width,height),
           '-r', str(fps),
           '-an',
           '-vcodec', 'rawvideo', '-f', 'rawvideo',
           '-pix_fmt', 'rgb24',
           '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, cwd=BASEDIR)
    while True:
        arr = np.fromstring(p.stdout.read(width*height*3), dtype=np.uint8)
        if len(arr) == 0:
            p.wait()
            return
            
        yield arr.reshape((height, width, 3))

def frame_writer(first_frame, path, fps=30, ffopts=[]):
    fr = first_frame
    cmd =[FFMPEG, '-y', '-s', '%dx%d' % (fr.shape[1], fr.shape[0]),
          '-r', str(fps), 
          '-an',
          '-vcodec', 'rawvideo', '-f', 'rawvideo', 
          '-pix_fmt', 'rgb24',
          '-i', '-'] + ffopts + [path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=BASEDIR)
    return p

def frames_to_video(generator, path, fps=30, ffopts=[]):
    p = None 
    for fr in generator:
        if p is None:
            p = frame_writer(fr, path, fps, ffopts)
        p.stdin.write(fr.tostring())
    p.stdin.close()
    print 'done generating video'
    p.wait()

def np2image(np, path):
    "Save an image array to a file."
    im = Image.fromstring(
        'RGB', (np.shape[1], np.shape[0]), np.tostring())
    im.save(path)
